"""Dependency installer — check and install ACCELA, SLSsteam, .NET runtime."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile

from paths import (
    find_accela_root,
    find_slssteam_root,
    check_slssteam_installed,
    check_accela_installed,
    find_lumalinux_root,
    check_lumalinux_installed,
    check_lumalinux_active,
    find_cloudredirect_root,
    check_cloudredirect_installed,
    check_cloudredirect_active,
    check_cloudredirect_authed,
    verify_slssteam_injected,
    _lumalinux_injected_in_steam_sh,
    _cloudredirect_injected_in_steam_sh,
    get_slssteam_config_path,
    get_slssteam_config_dir,
)
from dotnet import find_dotnet_path, ensure_dotnet_available
from subprocess_env import clean_env

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

INSTALL_STATE = {
    "status": "idle",
    "progress": "",
    "error": None,
}

CR_INSTALL_STATE = {
    "status": "idle",
    "progress": "",
    "error": None,
}

LL_INSTALL_STATE = {
    "status": "idle",
    "progress": "",
    "error": None,
}

# Combined state for the "Quick Install" flow, which chains the three
# installers below in dependency order.
QUICK_INSTALL_STATE = {
    "status": "idle",
    "step": None,
    "stepIndex": 0,
    "totalSteps": 3,
    "progress": "",
    "error": None,
}


# Upstream Headcrab is hosted at Deadboy666/h3adcr-b. The `headcrab.pages.dev`
# alias serves the same file from main. We fetch the raw GitHub URL directly
# so we can guarantee what we patch.
_HEADCRAB_RAW_URL = "https://raw.githubusercontent.com/Deadboy666/h3adcr-b/main/headcrab.sh"

# String replacements applied to the downloaded headcrab.sh BEFORE we run it.
#
# Three classes of patch:
#
#   1) no-op the Steam-killing lines (killall steam | true,
#      wheresteam -exitsteam variants) — in SteamOS Game Mode,
#      gamescope-session-plus counts 5 Steam exits of < 60 s each as a
#      crash loop and triggers `short_session_recover` which wipes
#      ~/.local/share/Steam and drops the user to OOBE. Even outside that
#      race, the kill mid-install is what forced our handlers' `restartSteam`
#      to fire prematurely. We no-op all kill paths. Steam stays alive for
#      the full install; the handler fires one controlled `steam -shutdown`
#      after install_*() returns success.
#
#   2) atomic .so copies (atomic-so-copy) — upstream's wheresteamdir() uses
#      `cp -f $InstallDir/<file>.so $...SLSsteamInstallDir/`, which truncates
#      the destination file in place. On re-installs (Enable CR after Install
#      Dependencies, or any later Repair) Steam is already running with those
#      .so files mmap'd, and the in-place rewrite leaves the kernel serving
#      pages from a file whose on-disk content has been swapped underneath —
#      Steam crashes / its UI subsystem (CEF) disconnects mid-install, the
#      handler's await never resolves, and the user sees "CloudRedirect: not
#      found" because no restartSteam ever fired. Replacing `cp -f X DST/` with
#      `cp -f X DST/X.lumadeck-new && mv -f DST/X.lumadeck-new DST/X` keeps
#      the running Steam pinned to the old inode (it stays valid until Steam
#      exits) and atomically swaps the path to a fresh inode for the next
#      Steam launch.
#
#   3) atomic CR wget (atomic-cr-wget) — exactly the same bug class as (2)
#      but for cloud_redirect.so, which upstream downloads via
#      `wget -O cloud_redirect.so $CloudRedirectLib`. `wget -O` is also an
#      in-place overwrite: open(O_TRUNC) + write. Same corruption window for
#      a running Steam that has cloud_redirect.so mmap'd. Manifests as
#      latent memory corruption that fires at unrelated code paths later
#      (mz_zip_end → getpid PLT SEGV; libcrypto OPENSSL_cleanup abort; C++
#      exception unwind abort during shutdown). Different crash signatures,
#      same root cause. Fix mirrors (2): download to .lumadeck-new and only
#      mv on success.
#
# If upstream changes the wording of these lines, the patch fails and the
# user gets an explicit "headcrab format changed" error instead of a silent
# half-broken install.
_HEADCRAB_PATCHES: tuple[tuple[str, str, str], ...] = (
    (
        r"killall steam \| true",
        ": # LumaDeck: skip mid-install Steam kill (restart fires at end of install_*)",
        "nuketheclient",
    ),
    (
        r"wheresteam -exitsteam",
        ": # LumaDeck: skipped short-session relaunch",
        "exitsteam-A",
    ),
    (
        r"wheresteam -clearbeta steam://exit",
        ": # LumaDeck: skipped short-session relaunch",
        "exitsteam-B",
    ),
    (
        r"wheresteam -clearbeta -exitsteam",
        ": # LumaDeck: skipped short-session relaunch",
        "exitsteam-C",
    ),
    (
        r"cp -f \$InstallDir/(\S+\.so) (\S+SLSsteamInstallDir)/",
        r"cp -f $InstallDir/\1 \2/\1.lumadeck-new && mv -f \2/\1.lumadeck-new \2/\1",
        "atomic-so-copy",
    ),
    (
        r'wget -O cloud_redirect\.so "\$CloudRedirectLib" &> /dev/null',
        r'wget -O cloud_redirect.so.lumadeck-new "$CloudRedirectLib" &> /dev/null && mv -f cloud_redirect.so.lumadeck-new cloud_redirect.so',
        "atomic-cr-wget",
    ),
)

_SESSION_TRACKER_RESET = (
    "# LumaDeck: reset gamescope-session short-session counter so even if a "
    "patched call slips through it can't accumulate towards recovery.\n"
    "rm -f /tmp/steamos-short-session-tracker 2>/dev/null\n"
)


def _patch_headcrab_script(content: str) -> str:
    """Apply the Game-Mode safety patches to a freshly downloaded headcrab.sh.

    Raises RuntimeError if any patch fails to apply — that means upstream
    changed the wording of a line we patch, and the user needs an updated
    plugin rather than a silently broken install.
    """
    failed: list[str] = []
    for pattern, replacement, label in _HEADCRAB_PATCHES:
        content, n = re.subn(pattern, replacement, content)
        if n == 0:
            failed.append(label)
    if failed:
        raise RuntimeError(
            "headcrab.sh format changed upstream — these LumaDeck patches "
            f"failed to apply: {failed}. Update _HEADCRAB_PATCHES."
        )
    # Prepend the tracker reset so it runs before anything else in the script.
    # We keep the shebang on line 1 and inject right after it.
    if content.startswith("#!"):
        first_nl = content.find("\n")
        if first_nl != -1:
            content = content[: first_nl + 1] + _SESSION_TRACKER_RESET + content[first_nl + 1:]
        else:
            content = content + "\n" + _SESSION_TRACKER_RESET
    else:
        content = _SESSION_TRACKER_RESET + content
    return content


# enter-the-wired (ciscosweater) downloads headcrab.sh via curl right before
# executing it. We rewrite those curl calls to `cp` from our pre-patched local
# copy so the in-place patches survive the indirection.
_ENTER_THE_WIRED_HEADCRAB_PATTERN = re.compile(
    r'curl -fsSL --retry 3 --retry-delay 2 (?:"\$SLS_URL"|"https://raw\.githubusercontent\.com/Deadboy666/h3adcr-b/main/headcrab\.sh\?t=\$\(date \+%s\)") -o "\$tmp_headcrab_script"'
)


def _patch_enter_the_wired(content: str, patched_headcrab_path: str) -> str:
    """Rewrite enter-the-wired so it copies our patched headcrab instead of curl'ing.

    Raises RuntimeError if no occurrence of the curl line was found (upstream
    has been refactored and the patch needs an update).
    """
    replacement = f'cp "{patched_headcrab_path}" "$tmp_headcrab_script"'
    new_content, n = _ENTER_THE_WIRED_HEADCRAB_PATTERN.subn(replacement, content)
    if n == 0:
        raise RuntimeError(
            "enter-the-wired format changed upstream — could not find the "
            "headcrab fetch line to redirect. Update _ENTER_THE_WIRED_HEADCRAB_PATTERN."
        )
    return new_content


def check_dependencies() -> dict:
    """Check if ACCELA, SLSsteam, and .NET runtime are available."""
    accela_installed = check_accela_installed()
    slssteam_installed = check_slssteam_installed()
    accela_root = find_accela_root()

    # .NET 9 detection — delegated to backend/dotnet.py so the path list and
    # the version check (--list-runtimes must mention "Microsoft.NETCore.App 9.")
    # live in one place. Same lookup used by ensure_dotnet_available() during
    # install, so the Dependencies panel and the installer agree on what
    # "installed" means.
    dotnet_path = find_dotnet_path()
    dotnet_available = dotnet_path is not None

    return {
        "success": True,
        "accela": accela_installed,
        "accelaPath": accela_root,
        "slssteam": slssteam_installed,
        "slssteamPath": find_slssteam_root(),
        "dotnet": dotnet_available,
        "dotnetPath": dotnet_path,
        # LumaDeck-specific: report on lumalinux + CloudRedirect too. These
        # aren't installed by enter-the-wired (that only covers ACCELA + .NET
        # + SLSsteam) — the user installs them manually. The plugin only
        # detects and reports their state for the Settings UI to display.
        # `*_active` is True when the .so is mapped into a running process
        # (i.e. LD_PRELOAD actually took effect, not just present on disk).
        "lumalinux": check_lumalinux_installed(),
        "lumalinuxPath": find_lumalinux_root(),
        "lumalinuxActive": check_lumalinux_active(),
        # Per-session health resolved into a single state — fetched separately
        # via get_lumalinux_health() so the UI consumes the same shape as
        # SLSsteam health (symmetric). Used by Settings → Dependencies and the
        # main page HealthBanner.
        "cloudredirect": check_cloudredirect_installed(),
        "cloudredirectPath": find_cloudredirect_root(),
        "cloudredirectActive": check_cloudredirect_active(),
        # True if ~/.config/CloudRedirect/tokens_<provider>.json exists. The
        # provider sign-in flow is GUI-only inside the CR Flatpak — gamemode
        # can't drive it, so the UI uses this to nudge the user to desktop
        # mode after we drop the .so + flatpak in place.
        "cloudredirectAuthed": check_cloudredirect_authed(),
    }


async def _download(url: str, dest: str) -> bool:
    """Download `url` to `dest` with curl. Returns True on success."""
    dl = await asyncio.create_subprocess_exec(
        "curl", "-fsSL", "-o", dest, url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=clean_env(),
    )
    await dl.wait()
    return dl.returncode == 0


async def install_dependencies() -> dict:
    """Run the Game-Mode-safe variant of enter-the-wired.

    enter-the-wired chains ACCELA + SLSsteam + headcrab.sh. Headcrab as-is
    kills Steam several times in quick succession; in gamemode that trips
    the gamescope-session crash-loop detector and SteamOS wipes the Steam
    install. We:
      1. Download enter-the-wired + accela + fix-deps as usual.
      2. Download headcrab.sh ourselves and apply _HEADCRAB_PATCHES (replace
         killall with steam -shutdown, skip the short-cycle relaunches).
      3. Patch enter-the-wired so its internal curl(headcrab.sh) becomes
         cp(our_patched_copy).
      4. Run the patched enter-the-wired exactly like upstream meant to —
         ACCELA, SLSsteam, the patched headcrab, then .NET 9 on our end.

    If upstream wording of any patched line changes, the install fails fast
    with a clear "format changed" error instead of bricking Steam.
    """
    global INSTALL_STATE
    INSTALL_STATE = {"status": "installing", "progress": "Starting installer...", "error": None}
    logger.info("LumaDeck: install_dependencies() entered")

    tmp_dir = None
    try:
        BASE_URL = "https://raw.githubusercontent.com/ciscosweater/enter-the-wired/main"
        tmp_dir = tempfile.mkdtemp(prefix="lumadeck_etw_")
        scripts = {
            "enter-the-wired": f"{BASE_URL}/enter-the-wired",
            "accela": f"{BASE_URL}/accela",
            "fix-deps": f"{BASE_URL}/fix-deps",
        }

        for name, url in scripts.items():
            INSTALL_STATE["progress"] = f"Downloading {name}..."
            logger.info("LumaDeck: downloading %s", name)
            dest = os.path.join(tmp_dir, name)
            if not await _download(url, dest):
                INSTALL_STATE["status"] = "failed"
                INSTALL_STATE["error"] = f"Failed to download {name}"
                logger.error("LumaDeck: download failed: %s", name)
                return {"success": False}
            os.chmod(dest, 0o700)

        main_script = os.path.join(tmp_dir, "enter-the-wired")
        try:
            with open(main_script, "r", encoding="utf-8", errors="replace") as f:
                first_line = f.readline(256)
            if not first_line.startswith("#"):
                INSTALL_STATE["status"] = "failed"
                INSTALL_STATE["error"] = "Downloaded file does not look like a shell script"
                return {"success": False}
        except Exception as read_exc:
            INSTALL_STATE["status"] = "failed"
            INSTALL_STATE["error"] = f"Cannot read installer script: {read_exc}"
            return {"success": False}

        # Pre-fetch headcrab.sh and apply our Game-Mode safety patches.
        INSTALL_STATE["progress"] = "Downloading + patching headcrab.sh..."
        logger.info("LumaDeck: fetching headcrab.sh")
        headcrab_path = os.path.join(tmp_dir, "headcrab_patched.sh")
        if not await _download(_HEADCRAB_RAW_URL, headcrab_path):
            INSTALL_STATE["status"] = "failed"
            INSTALL_STATE["error"] = "Failed to download headcrab.sh"
            return {"success": False}
        try:
            with open(headcrab_path, "r", encoding="utf-8") as f:
                hc_content = f.read()
            hc_content = _patch_headcrab_script(hc_content)
            with open(headcrab_path, "w", encoding="utf-8") as f:
                f.write(hc_content)
            os.chmod(headcrab_path, 0o700)
            logger.info("LumaDeck: headcrab.sh patched OK (%d bytes)", len(hc_content))
        except RuntimeError as exc:
            INSTALL_STATE["status"] = "failed"
            INSTALL_STATE["error"] = str(exc)
            logger.error("LumaDeck: headcrab patch failed: %s", exc)
            return {"success": False}

        # Patch enter-the-wired so it cp's our patched headcrab instead of curl'ing.
        try:
            with open(main_script, "r", encoding="utf-8") as f:
                etw_content = f.read()
            etw_content = _patch_enter_the_wired(etw_content, headcrab_path)
            with open(main_script, "w", encoding="utf-8") as f:
                f.write(etw_content)
            logger.info("LumaDeck: enter-the-wired patched OK")
        except RuntimeError as exc:
            INSTALL_STATE["status"] = "failed"
            INSTALL_STATE["error"] = str(exc)
            logger.error("LumaDeck: enter-the-wired patch failed: %s", exc)
            return {"success": False}

        INSTALL_STATE["progress"] = "Running installer..."
        # Pipe `yes y` into bash so any interactive prompt that survives the
        # script chain (ACCELAINSTALL is the only known case) gets confirmed.
        # None of the bash scripts use `read` themselves and pacman calls are
        # --noconfirm, so the y's are absorbed only by ACCELAINSTALL.
        process = await asyncio.create_subprocess_shell(
            f"yes y | bash {main_script}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=tmp_dir,
            env=clean_env(),
        )

        async def _read_output():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                INSTALL_STATE["progress"] = line.decode("utf-8", errors="replace").strip()

        asyncio.create_task(_read_output())
        await process.wait()

        if process.returncode == 0:
            # #19: enter-the-wired/Headcrab can exit 0 even when a transient
            # wget drop left steam.sh unpatched (its wgets are `&> /dev/null`).
            # Verify the post-condition (INJECT_SLS in steam.sh) instead of
            # trusting the exit code, so we don't report a green "done" that
            # isn't functional.
            sls_check = verify_slssteam_injected()
            if not sls_check.get("already_ok"):
                INSTALL_STATE["status"] = "failed"
                INSTALL_STATE["error"] = (
                    "Installer finished but SLSsteam was not injected into "
                    "steam.sh (likely a transient network drop during Headcrab's "
                    "downloads). Click Install / Reinstall Dependencies again to "
                    "retry."
                )
                logger.error(
                    "LumaDeck: install_dependencies post-check failed: %s",
                    sls_check.get("error"),
                )
            else:
                # #13: force SafeMode: yes — SLSsteam's own recommendation for
                # Steam Deck gamemode. It auto-disables SLSsteam on an unknown
                # steamclient.so hash so a Steam update can't make it inject
                # against changed offsets and break gamemode. Headcrab's
                # editconfig() races SLSsteam creating config.yaml and leaves it
                # at the default (no), so seed the config if it's not there yet
                # and flip the flag — same approach as DisableCloud for CR.
                _seed_slssteam_config_if_missing()
                sm_ok, sm_msg = _set_safemode_yes(get_slssteam_config_path())
                logger.info("LumaDeck: SafeMode repair: ok=%s (%s)", sm_ok, sm_msg)
                # enter-the-wired installed SLSsteam + ACCELA but does NOT install
                # .NET 9. ACCELA's depot downloads and Steamless features need it,
                # so we install it here in the same "Install / Reinstall" click.
                # ensure_dotnet_available() is a no-op if .NET 9 is already there.
                INSTALL_STATE["progress"] = "Installing .NET 9 runtime if missing..."
                loop = asyncio.get_event_loop()
                dotnet_ok = await loop.run_in_executor(None, ensure_dotnet_available)
                if dotnet_ok:
                    INSTALL_STATE["status"] = "done"
                    INSTALL_STATE["progress"] = "Installation complete!"
                else:
                    INSTALL_STATE["status"] = "done"
                    INSTALL_STATE["progress"] = (
                        "SLSsteam and ACCELA installed. .NET 9 install failed — "
                        "click Install / Reinstall Dependencies again to retry."
                    )
        else:
            INSTALL_STATE["status"] = "failed"
            INSTALL_STATE["error"] = f"Installer exited with code {process.returncode}"

    except Exception as exc:
        INSTALL_STATE["status"] = "failed"
        INSTALL_STATE["error"] = str(exc)
        logger.exception("LumaDeck: install_dependencies crashed: %s", exc)
    finally:
        if tmp_dir:
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    logger.info("LumaDeck: install_dependencies finished, state=%s", INSTALL_STATE)
    return {"success": INSTALL_STATE["status"] == "done"}


def get_install_status() -> dict:
    return INSTALL_STATE.copy()


# SLSsteam's own default config, verbatim from AceSLS/SLSsteam res/config.yaml.
# SLSsteam copies this to ~/.config/SLSsteam/config.yaml on its first injected
# run. We seed the SAME bytes when it's missing so CloudRedirect can flip
# DisableCloud without first waiting for a Steam restart (the gap that broke
# Quick Install: CR ran before SLSsteam had ever run, so no config.yaml existed).
# DisableCloud is left at the upstream default ("yes"); CR's _set_disablecloud_no
# flips it to "no" right after. Identical to the normal first-run result.
_SLSSTEAM_DEFAULT_CONFIG = """\
#Disables Family Share license locking for self and others
DisableFamilyShareLock: yes

#Switches to whitelist instead of the default blacklist
UseWhitelist: no

#Automatically filter Apps in CheckAppOwnership. Filters everything but Games and Applications. Should not affect DLC checks
#Overrides black-/whitelist. Gets overriden by AdditionalApps
AutoFilterList: yes

#List of AppIds to ex-/include
AppIds:

#Enables playing of not owned games. Respects black-/whitelist AppIds
PlayNotOwnedGames: no

#Additional AppIds to inject (Overrides your black-/whitelist & also overrides OwnerIds for apps you got shared!) Best to use this only on games NOT in your library.
AdditionalApps:

#Extra Data for Dlcs belonging to a specific AppId. Only needed
#when the App you're playing is hit by Steams 64 DLC limit
DlcData:

#Used to retrieve ProductInfo from Steam servers for some games
AppTokens:

#Fake Steam being offline for specified AppIds. Same format as AppIds
FakeOffline:

#Change AppIds of games to enable networking features
#Use 0 as a key to set for all unowned Apps
#Keeps track of the proper AppIds via game launches, so please do not start multiple FakeAppId enabled games simultaneously
FakeAppIds:

#Custom ingame statuses. Set AppId to 0 to disable
IdleStatus:
  AppId: 0
  Title: ""

#Override game titles. Only works with owned appIds! For injected appIds use either UnownedStatus or combine them with FakeAppIds
GameTitles:

#Override purchase time stamps
SubscriptionTimestamps:

#Blocks games from unlocking on wrong accounts
DenuvoGames:

#Automatically disable SLSsteam when steamclient.so does not match a predefined file hash that is known to work
#You should enable this if you're planing to use SLSsteam with Steam Deck's gamemode
SafeMode: no

#Toggles notifications via notify-send
Notifications: yes

#Warn user via notification when steamclient.so hash differs from known safe hash
#Mostly useful for development so I don't accidentally miss an update
WarnHashMissmatch: no

#Notify when SLSsteam is done initializing
NotifyInit: yes

#Enable sending commands to SLSsteam via /tmp/SLSsteam.API
API: no

#Disable cloud saves for unlocked games. Set to "no" if using CloudRedirect or similar.
DisableCloud: yes

#Changes your account's E-Mail clientsided. Leave blank to disable
FakeEmail: ""

#Changes your wallet's balance clientsidedly. 0 to turn off
FakeWalletBalance: 0

#Log levels:
#Once = 0
#Debug = 1
#Info = 2
#NotifyShort = 3
#NotifyLong = 4
#Warn = 5
#None = 6
LogLevel: 2

#Logs all calls to Steamworks (this makes the logfile huge! Only useful for debugging/analyzing
ExtendedLogging: no
"""


def _seed_slssteam_config_if_missing() -> bool:
    """Write SLSsteam's default config.yaml if it doesn't exist yet.

    No-op (returns False) when the config already exists, or when SLSsteam
    isn't installed (we must not create an orphan config for a missing
    SLSsteam — that would mask the real "install dependencies first" error).
    Returns True only when it actually seeded the file.
    """
    try:
        if not check_slssteam_installed():
            return False
        config_path = get_slssteam_config_path()
        if os.path.exists(config_path):
            return False
        os.makedirs(get_slssteam_config_dir(), exist_ok=True)
        tmp = config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(_SLSSTEAM_DEFAULT_CONFIG)
        os.replace(tmp, config_path)
        logger.info("LumaDeck: seeded default SLSsteam config.yaml at %s", config_path)
        return True
    except Exception as exc:
        logger.warning("LumaDeck: failed to seed SLSsteam config.yaml: %s", exc)
        return False


def _set_disablecloud_no(config_path: str) -> tuple[bool, str]:
    """Flip `DisableCloud: yes` -> `DisableCloud: no` in SLSsteam's config.yaml.

    headcrab gates CloudRedirect on this exact line (`crconfigcheck` greps
    for `DisableCloud: no`), so we have to flip it before invoking headcrab —
    the script doesn't do it itself.

    Returns (ok, message). ok=False only when the config is missing or the
    DisableCloud line is absent entirely (= SLSsteam wasn't initialised via
    enter-the-wired yet).
    """
    if not os.path.isfile(config_path):
        return False, f"SLSsteam config not found at {config_path} — install dependencies first"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return False, f"Cannot read SLSsteam config: {exc}"

    new_content, n = re.subn(
        r"^(\s*DisableCloud\s*:\s*)yes\s*$",
        r"\1no",
        content,
        flags=re.MULTILINE,
    )

    if n > 0:
        try:
            tmp = config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp, config_path)
            return True, "DisableCloud flipped to no"
        except Exception as exc:
            return False, f"Cannot write SLSsteam config: {exc}"

    if re.search(r"^\s*DisableCloud\s*:\s*no\s*$", content, flags=re.MULTILINE):
        return True, "DisableCloud already set to no"

    return False, "DisableCloud line missing from SLSsteam config — reinstall dependencies"


def _set_safemode_yes(config_path: str) -> tuple[bool, str]:
    """Flip `SafeMode: no` -> `SafeMode: yes` in SLSsteam's config.yaml.

    SLSsteam's own config recommends SafeMode for Steam Deck gamemode: it
    auto-disables SLSsteam when steamclient.so doesn't match a known-good hash,
    so a Steam client update can't make SLSsteam inject against changed offsets
    and break/crash gamemode (it just no-ops until AceSLS ships a new hash).
    Headcrab tries to set it but its editconfig() races SLSsteam creating
    config.yaml and silently fails, leaving the default (no) — so we seed the
    config if missing and flip the flag ourselves, exactly like DisableCloud.

    Returns (ok, message). ok=False only when the config is missing or has no
    SafeMode line.
    """
    if not os.path.isfile(config_path):
        return False, f"SLSsteam config not found at {config_path} — install dependencies first"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return False, f"Cannot read SLSsteam config: {exc}"

    new_content, n = re.subn(
        r"^(\s*SafeMode\s*:\s*)no\s*$",
        r"\1yes",
        content,
        flags=re.MULTILINE,
    )

    if n > 0:
        try:
            tmp = config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp, config_path)
            return True, "SafeMode flipped to yes"
        except Exception as exc:
            return False, f"Cannot write SLSsteam config: {exc}"

    if re.search(r"^\s*SafeMode\s*:\s*yes\s*$", content, flags=re.MULTILINE):
        return True, "SafeMode already set to yes"

    return False, "SafeMode line missing from SLSsteam config — reinstall dependencies"


async def install_cloudredirect() -> dict:
    """Run the Game-Mode-safe variant of headcrab with DisableCloud: no.

    Headcrab gates CR install on `grep "DisableCloud: no" config.yaml`. We
    flip the line, download headcrab.sh, apply _HEADCRAB_PATCHES so the
    install doesn't trip the gamescope-session crash detector, then run it.
    """
    global CR_INSTALL_STATE
    CR_INSTALL_STATE = {"status": "installing", "progress": "Starting installer...", "error": None}
    logger.info("LumaDeck: install_cloudredirect() entered")

    tmp_dir = None
    try:
        config_path = get_slssteam_config_path()
        # If SLSsteam is installed but hasn't run yet (no config.yaml — the
        # Quick Install case, where CR runs right after deps without a Steam
        # restart in between), seed SLSsteam's own default config so we can
        # flip DisableCloud without waiting for SLSsteam to create it. No-op
        # in the normal flow where a restart already made config.yaml exist.
        _seed_slssteam_config_if_missing()
        CR_INSTALL_STATE["progress"] = "Enabling DisableCloud: no in SLSsteam config..."
        ok, msg = _set_disablecloud_no(config_path)
        if not ok:
            CR_INSTALL_STATE["status"] = "failed"
            CR_INSTALL_STATE["error"] = msg
            return {"success": False}

        tmp_dir = tempfile.mkdtemp(prefix="lumadeck_cr_")
        script_path = os.path.join(tmp_dir, "headcrab_patched.sh")
        CR_INSTALL_STATE["progress"] = "Downloading + patching headcrab.sh..."
        logger.info("LumaDeck: fetching headcrab.sh for CR")
        if not await _download(_HEADCRAB_RAW_URL, script_path):
            CR_INSTALL_STATE["status"] = "failed"
            CR_INSTALL_STATE["error"] = "Failed to download headcrab.sh"
            return {"success": False}

        try:
            with open(script_path, "r", encoding="utf-8") as f:
                hc_content = f.read()
            hc_content = _patch_headcrab_script(hc_content)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(hc_content)
            os.chmod(script_path, 0o700)
            logger.info("LumaDeck: headcrab.sh patched OK (%d bytes)", len(hc_content))
        except RuntimeError as exc:
            CR_INSTALL_STATE["status"] = "failed"
            CR_INSTALL_STATE["error"] = str(exc)
            return {"success": False}

        CR_INSTALL_STATE["progress"] = "Running installer..."
        process = await asyncio.create_subprocess_shell(
            f"yes y | bash {script_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=tmp_dir,
            env=clean_env(),
        )

        async def _read_output():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                CR_INSTALL_STATE["progress"] = line.decode("utf-8", errors="replace").strip()

        asyncio.create_task(_read_output())
        await process.wait()

        if process.returncode == 0:
            # #19: headcrab can exit 0 with steam.sh left unpatched (transient
            # wget drop). Verify the post-condition — cloud_redirect.so on disk
            # AND the INJECT_CR line in steam.sh — instead of the exit code.
            if not check_cloudredirect_installed():
                CR_INSTALL_STATE["status"] = "failed"
                CR_INSTALL_STATE["error"] = (
                    "Installer finished but cloud_redirect.so was not deployed "
                    "(likely a transient network drop). Click Install CloudRedirect "
                    "again to retry."
                )
            elif not _cloudredirect_injected_in_steam_sh():
                CR_INSTALL_STATE["status"] = "failed"
                CR_INSTALL_STATE["error"] = (
                    "Installer finished but CloudRedirect was not injected into "
                    "steam.sh (likely a transient network drop during Headcrab's "
                    "downloads). Click Install CloudRedirect again to retry."
                )
            else:
                CR_INSTALL_STATE["status"] = "done"
                CR_INSTALL_STATE["progress"] = "CloudRedirect installed!"
        else:
            CR_INSTALL_STATE["status"] = "failed"
            CR_INSTALL_STATE["error"] = f"Installer exited with code {process.returncode}"

    except Exception as exc:
        CR_INSTALL_STATE["status"] = "failed"
        CR_INSTALL_STATE["error"] = str(exc)
        logger.exception("LumaDeck: install_cloudredirect crashed: %s", exc)
    finally:
        if tmp_dir:
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    logger.info("LumaDeck: install_cloudredirect finished, state=%s", CR_INSTALL_STATE)
    return {"success": CR_INSTALL_STATE["status"] == "done"}


def get_cr_install_status() -> dict:
    return CR_INSTALL_STATE.copy()


async def install_lumalinux() -> dict:
    """Run lumalinux/install.sh from the jayool/lumalinux repo.

    Unlike enter-the-wired and headcrab, this one does NOT touch Steam at
    runtime: it only patches ~/.local/share/Steam/steam.sh (idempotent
    managed-block insert before `source $STEAM_CLIENT`) and drops the .so +
    keys dir. No killall, no exec of Steam with env vars, no downgrade.

    Also serves as the recovery path after a Headcrab Updater run: Headcrab
    regenerates steam.sh from scratch, wiping the lumalinux block, so
    re-invoking this is how the user gets back to a loaded state.
    """
    global LL_INSTALL_STATE
    LL_INSTALL_STATE = {"status": "installing", "progress": "Starting installer...", "error": None}
    logger.info("LumaDeck: install_lumalinux() entered")

    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="lumadeck_ll_")
        script_path = os.path.join(tmp_dir, "install.sh")
        LL_INSTALL_STATE["progress"] = "Downloading lumalinux installer..."
        if not await _download(
            "https://raw.githubusercontent.com/jayool/lumalinux/main/install.sh",
            script_path,
        ):
            LL_INSTALL_STATE["status"] = "failed"
            LL_INSTALL_STATE["error"] = "Failed to download lumalinux installer"
            return {"success": False}
        os.chmod(script_path, 0o700)

        try:
            with open(script_path, "r", encoding="utf-8", errors="replace") as f:
                first_line = f.readline(256)
            if not first_line.startswith("#"):
                LL_INSTALL_STATE["status"] = "failed"
                LL_INSTALL_STATE["error"] = "Downloaded file does not look like a shell script"
                return {"success": False}
        except Exception as read_exc:
            LL_INSTALL_STATE["status"] = "failed"
            LL_INSTALL_STATE["error"] = f"Cannot read installer script: {read_exc}"
            return {"success": False}

        # No `yes y |` — lumalinux/install.sh contains zero `read` prompts
        # (only curl/sed/awk/install), so there's nothing to auto-confirm.
        LL_INSTALL_STATE["progress"] = "Running installer..."
        process = await asyncio.create_subprocess_exec(
            "bash", script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=tmp_dir,
            env=clean_env(),
        )

        async def _read_output():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                LL_INSTALL_STATE["progress"] = line.decode("utf-8", errors="replace").strip()

        asyncio.create_task(_read_output())
        await process.wait()

        if process.returncode == 0:
            # #19: verify the post-condition (the lumalinux LD_PRELOAD block
            # landed in steam.sh) rather than trusting the exit code, so a
            # transient download/patch failure can't report a green "done".
            if not _lumalinux_injected_in_steam_sh():
                LL_INSTALL_STATE["status"] = "failed"
                LL_INSTALL_STATE["error"] = (
                    "Installer finished but the lumalinux block was not added to "
                    "steam.sh (likely a transient network drop). Click Install "
                    "lumalinux again to retry."
                )
            else:
                LL_INSTALL_STATE["status"] = "done"
                LL_INSTALL_STATE["progress"] = "lumalinux installed!"
        else:
            LL_INSTALL_STATE["status"] = "failed"
            LL_INSTALL_STATE["error"] = (
                f"Installer exited with code {process.returncode} — "
                f"last line: {LL_INSTALL_STATE['progress']}"
            )

    except Exception as exc:
        LL_INSTALL_STATE["status"] = "failed"
        LL_INSTALL_STATE["error"] = str(exc)
        logger.exception("LumaDeck: install_lumalinux crashed: %s", exc)
    finally:
        if tmp_dir:
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    logger.info("LumaDeck: install_lumalinux finished, state=%s", LL_INSTALL_STATE)
    return {"success": LL_INSTALL_STATE["status"] == "done"}


def get_ll_install_status() -> dict:
    return LL_INSTALL_STATE.copy()


async def quick_install() -> dict:
    """Run the three installers in dependency order, stopping at the first
    failure:

        1. dependencies   — SLSsteam + ACCELA + .NET 9   (install_dependencies)
        2. cloudredirect  — CloudRedirect via headcrab    (install_cloudredirect)
        3. lumalinux      — liblumalinux.so + steam.sh patch (install_lumalinux)

    Order matters: steps 1 and 2 both run headcrab, which regenerates steam.sh
    from scratch — that would wipe lumalinux's managed block. lumalinux must
    therefore run LAST so its steam.sh patch survives. This mirrors doing the
    three existing buttons by hand, top to bottom.

    Each sub-installer keeps updating its own state global with live progress;
    get_quick_install_status() merges that in for the currently-running step.
    The caller (frontend) does a single Steam restart at the end — the
    sub-installers don't restart Steam themselves.
    """
    global QUICK_INSTALL_STATE

    steps = [
        ("dependencies", install_dependencies, get_install_status),
        ("cloudredirect", install_cloudredirect, get_cr_install_status),
        ("lumalinux", install_lumalinux, get_ll_install_status),
    ]
    QUICK_INSTALL_STATE = {
        "status": "installing",
        "step": steps[0][0],
        "stepIndex": 0,
        "totalSteps": len(steps),
        "progress": "Starting Quick Install...",
        "error": None,
    }
    logger.info("LumaDeck: quick_install() entered")

    for i, (name, runner, status_getter) in enumerate(steps):
        QUICK_INSTALL_STATE["step"] = name
        QUICK_INSTALL_STATE["stepIndex"] = i
        QUICK_INSTALL_STATE["progress"] = f"Installing {name} ({i + 1}/{len(steps)})..."
        logger.info("LumaDeck: quick_install step %d/%d: %s", i + 1, len(steps), name)
        try:
            result = await runner()
        except Exception as exc:
            logger.exception("LumaDeck: quick_install step %s crashed: %s", name, exc)
            QUICK_INSTALL_STATE["status"] = "failed"
            QUICK_INSTALL_STATE["error"] = f"{name} crashed: {exc}"
            return {"success": False, "failedStep": name}

        if not (isinstance(result, dict) and result.get("success")):
            # Surface the sub-installer's own error/progress for context.
            sub = status_getter()
            QUICK_INSTALL_STATE["status"] = "failed"
            QUICK_INSTALL_STATE["error"] = sub.get("error") or f"{name} failed"
            QUICK_INSTALL_STATE["progress"] = sub.get("progress", "")
            logger.error("LumaDeck: quick_install failed at %s: %s", name, QUICK_INSTALL_STATE["error"])
            return {"success": False, "failedStep": name}

    QUICK_INSTALL_STATE["status"] = "done"
    QUICK_INSTALL_STATE["stepIndex"] = len(steps)
    QUICK_INSTALL_STATE["progress"] = "Quick Install complete!"
    logger.info("LumaDeck: quick_install finished OK")
    return {"success": True}


def get_quick_install_status() -> dict:
    """Quick Install state, enriched with the live progress line of whichever
    sub-installer is running right now (so the UI shows real activity)."""
    state = QUICK_INSTALL_STATE.copy()
    if state.get("status") == "installing":
        live_getter = {
            "dependencies": get_install_status,
            "cloudredirect": get_cr_install_status,
            "lumalinux": get_ll_install_status,
        }.get(state.get("step"))
        if live_getter:
            sub = live_getter()
            if sub.get("progress"):
                state["progress"] = sub["progress"]
            if sub.get("status") == "failed" and sub.get("error"):
                state["error"] = sub["error"]
    return state

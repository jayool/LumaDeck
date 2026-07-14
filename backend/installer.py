"""Dependency installer — check and install SLSsteam, CloudRedirect, .NET runtime."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile

from paths import (
    find_slssteam_root,
    check_slssteam_installed,
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

LL_INSTALL_STATE = {
    "status": "idle",
    "progress": "",
    "error": None,
}

# Combined state for the "Quick Install" flow, which chains the two installers
# below in dependency order (dependencies [= SLSsteam + CloudRedirect] → lumalinux).
QUICK_INSTALL_STATE = {
    "status": "idle",
    "step": None,
    "stepIndex": 0,
    "totalSteps": 2,
    "progress": "",
    "error": None,
}


# Upstream Headcrab is hosted at Deadboy666/h3adcr-b. The `headcrab.pages.dev`
# alias serves the same file from main. We fetch the raw GitHub URL directly
# so we can guarantee what we patch.
_HEADCRAB_RAW_URL = "https://raw.githubusercontent.com/Deadboy666/h3adcr-b/main/headcrab.sh"

# String replacements applied to the downloaded headcrab.sh BEFORE we run it.
#
# Four classes of patch:
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
#      the destination file in place. On re-installs (any later Repair /
#      Reinstall Dependencies) Steam is already running with those
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
#   4) force CloudRedirect install (force-cr-install) — upstream gates every
#      CloudRedirect step behind `crconfigcheck`, which greps the SLSsteam
#      config.yaml for `DisableCloud: no`. On a fresh device that config doesn't
#      exist yet (SLSsteam only writes it on its first injected run), so the gate
#      fails and CR is skipped. We no-op the gate's grep to `true` so CR always
#      installs, and set `DisableCloud: no` (+ `DisableUpdates: no`) AFTER the
#      install on the real config SLSsteam generates itself. This removes the
#      need to seed a fake config.yaml before headcrab just to pass the grep.
#
# If upstream changes the wording of these lines, the patch fails and the
# user gets an explicit "headcrab format changed" error instead of a silent
# half-broken install.
# Each patch carries a `gamemode_only` flag. The kill / short-session-relaunch
# no-ops exist purely to survive SteamOS Game Mode's crash-loop detector; in a
# Desktop session those kills are normal and REQUIRED (the Steam downgrade needs
# them to restart Steam), so they're skipped there. The atomic .so copies are
# robustness fixes for a running Steam and apply in BOTH modes.
_HEADCRAB_PATCHES: tuple[tuple[str, str, str, bool], ...] = (
    (
        r"killall steam \| true",
        ": # LumaDeck: skip mid-install Steam kill (restart fires at end of install_*)",
        "nuketheclient",
        True,
    ),
    (
        r"wheresteam -exitsteam",
        ": # LumaDeck: skipped short-session relaunch",
        "exitsteam-A",
        True,
    ),
    (
        r"wheresteam -clearbeta steam://exit",
        ": # LumaDeck: skipped short-session relaunch",
        "exitsteam-B",
        True,
    ),
    (
        r"wheresteam -clearbeta -exitsteam",
        ": # LumaDeck: skipped short-session relaunch",
        "exitsteam-C",
        True,
    ),
    (
        r"cp -f \$InstallDir/(\S+\.so) (\S+SLSsteamInstallDir)/",
        r"cp -f $InstallDir/\1 \2/\1.lumadeck-new && mv -f \2/\1.lumadeck-new \2/\1",
        "atomic-so-copy",
        False,
    ),
    (
        r'wget -O cloud_redirect\.so "\$CloudRedirectLib" &> /dev/null',
        r'wget -O cloud_redirect.so.lumadeck-new "$CloudRedirectLib" &> /dev/null && mv -f cloud_redirect.so.lumadeck-new cloud_redirect.so',
        "atomic-cr-wget",
        False,
    ),
    (
        r'grep -F "DisableCloud: no" config\.yaml &> /dev/null',
        "true # LumaDeck: force CloudRedirect (gate; DisableCloud/DisableUpdates flipped post-install)",
        "force-cr-install",
        False,
    ),
)

_SESSION_TRACKER_RESET = (
    "# LumaDeck: reset gamescope-session short-session counter so even if a "
    "patched call slips through it can't accumulate towards recovery.\n"
    "rm -f /tmp/steamos-short-session-tracker 2>/dev/null\n"
)


def _patch_headcrab_script(content: str, gamemode: bool = True) -> str:
    """Apply the safety patches to a freshly downloaded headcrab.sh.

    gamemode=True (default, Game Mode): apply ALL patches + the gamescope
    short-session tracker reset — headcrab must not kill/relaunch Steam or it
    trips the crash-loop wipe.

    gamemode=False (Desktop hand-off): apply ONLY the always-on robustness
    patches (atomic .so copies) and SKIP the kill/relaunch no-ops + the tracker
    reset — in Desktop the kills are normal and REQUIRED so the Steam downgrade
    can restart Steam to step the version down.

    Raises RuntimeError if a patch that SHOULD apply doesn't — upstream changed
    the wording and the plugin needs updating.
    """
    failed: list[str] = []
    for pattern, replacement, label, gamemode_only in _HEADCRAB_PATCHES:
        if gamemode_only and not gamemode:
            continue  # Desktop: leave the kill/relaunch lines intact.
        content, n = re.subn(pattern, replacement, content)
        if n == 0:
            failed.append(label)
    if failed:
        raise RuntimeError(
            "headcrab.sh format changed upstream — these LumaDeck patches "
            f"failed to apply: {failed}. Update _HEADCRAB_PATCHES."
        )
    if not gamemode:
        return content  # no tracker reset in Desktop (gamescope isn't running).
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


def check_dependencies() -> dict:
    """Check if SLSsteam, CloudRedirect, lumalinux and the .NET runtime are available."""
    slssteam_installed = check_slssteam_installed()

    # .NET 9 detection — delegated to backend/dotnet.py so the path list and
    # the version check (--list-runtimes must mention "Microsoft.NETCore.App 9.")
    # live in one place. Same lookup used by ensure_dotnet_available() during
    # install, so the Dependencies panel and the installer agree on what
    # "installed" means.
    dotnet_path = find_dotnet_path()
    dotnet_available = dotnet_path is not None

    return {
        "success": True,
        "slssteam": slssteam_installed,
        "slssteamPath": find_slssteam_root(),
        "dotnet": dotnet_available,
        "dotnetPath": dotnet_path,
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


async def install_dependencies(gamemode: bool = True) -> dict:
    """Install SLSsteam via the patched headcrab.sh — no ACCELA, no enter-the-wired.

    headcrab.sh (Deadboy666/h3adcr-b) installs SLSsteam and performs the Steam
    version downgrade. We download it and apply _HEADCRAB_PATCHES: in Game Mode
    that replaces the Steam kills with `steam -shutdown` and skips the
    short-cycle relaunches, so the gamescope-session crash-loop detector doesn't
    wipe the Steam install. Then we run it.

    CloudRedirect ships with the base install: headcrab installs it whenever
    `DisableCloud: no` is present in config.yaml, so we seed the config and set
    that flag before running headcrab. CR is inert until the user configures a
    provider, so bundling it here (rather than a separate opt-in step) removes
    the second headcrab run without forcing anything on.

    ACCELA used to come from enter-the-wired for Steamless + Goldberg; both now
    ship bundled with the plugin, so enter-the-wired/ACCELA is gone entirely. We
    still install .NET 9 (Steamless uses it) via dotnet.py — Microsoft's own
    installer script, not ACCELA.

    gamemode=False is the Desktop variant (kills kept; see _patch_headcrab_script).

    If upstream wording of any patched line changes, the install fails fast with
    a clear "format changed" error instead of bricking Steam.
    """
    global INSTALL_STATE
    INSTALL_STATE = {"status": "installing", "progress": "Starting installer...", "error": None}
    logger.info("LumaDeck: install_dependencies() entered")

    tmp_dir = None
    try:
        # No config seeding here anymore. The force-cr-install patch makes
        # headcrab install CloudRedirect unconditionally (it no longer needs
        # DisableCloud: no present at crconfigcheck time), so there's nothing to
        # seed before the run. SLSsteam writes its own config.yaml on its first
        # injected run; we set the flags LumaDeck needs afterwards via
        # ensure_slssteam_flags() (below + a startup task in main.py).
        tmp_dir = tempfile.mkdtemp(prefix="lumadeck_deps_")
        script_path = os.path.join(tmp_dir, "headcrab_patched.sh")
        INSTALL_STATE["progress"] = "Downloading + patching headcrab.sh..."
        logger.info("LumaDeck: fetching headcrab.sh")
        if not await _download(_HEADCRAB_RAW_URL, script_path):
            INSTALL_STATE["status"] = "failed"
            INSTALL_STATE["error"] = "Failed to download headcrab.sh"
            return {"success": False}
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                hc_content = f.read()
            hc_content = _patch_headcrab_script(hc_content, gamemode)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(hc_content)
            os.chmod(script_path, 0o700)
            logger.info("LumaDeck: headcrab.sh patched OK (%d bytes, gamemode=%s)", len(hc_content), gamemode)
        except RuntimeError as exc:
            INSTALL_STATE["status"] = "failed"
            INSTALL_STATE["error"] = str(exc)
            logger.error("LumaDeck: headcrab patch failed: %s", exc)
            return {"success": False}

        INSTALL_STATE["progress"] = "Running installer..."
        # `yes y` covers any interactive prompt in the script (harmless — headcrab
        # itself doesn't `read`, and pacman calls are --noconfirm).
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
                INSTALL_STATE["progress"] = line.decode("utf-8", errors="replace").strip()

        asyncio.create_task(_read_output())
        await process.wait()

        if process.returncode == 0:
            # #19: Headcrab can exit 0 even when a transient
            # wget drop left steam.sh unpatched (its wgets are `&> /dev/null`).
            # Verify the post-condition (INJECT_SLS in steam.sh) instead of
            # trusting the exit code, so we don't report a green "done" that
            # isn't functional.
            #
            # In the Desktop / off-pin path the Steam DOWNGRADE settles
            # asynchronously — Steam restarts to step the client version down and
            # steam.sh's INJECT_SLS can land a few seconds after headcrab exits.
            # Poll before declaring failure so we don't abort a setup that's
            # actually finishing (that abort is what skipped CR + lumalinux).
            sls_check = verify_slssteam_injected()
            if not sls_check.get("already_ok"):
                for _ in range(20):  # ~60s (20 x 3s)
                    await asyncio.sleep(3)
                    INSTALL_STATE["progress"] = "Waiting for Steam to settle after the downgrade..."
                    sls_check = verify_slssteam_injected()
                    if sls_check.get("already_ok"):
                        break
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
                # Set the flags LumaDeck depends on (DisableCloud: no,
                # DisableUpdates: no, SafeMode: yes) on the config SLSsteam wrote
                # itself. On a fresh Game Mode install the config usually isn't
                # there yet (Steam hasn't restarted with SLSsteam), so this is a
                # best-effort no-op and the startup task in main.py sets them once
                # SLSsteam has created it. On a reinstall / Desktop run the config
                # already exists, so this applies immediately (SLSsteam hot-reloads).
                flags = ensure_slssteam_flags()
                logger.info("LumaDeck: ensure_slssteam_flags: %s", flags)

                # CloudRedirect rides the same headcrab run. A transient
                # wget/steam.sh drop can leave it missing,
                # so verify both post-conditions (cloud_redirect.so on disk AND
                # INJECT_CR in steam.sh) — the #19 defense. Non-fatal: SLSsteam is
                # the critical piece; a CR miss just gets surfaced so users retry.
                cr_ok = check_cloudredirect_installed() and _cloudredirect_injected_in_steam_sh()
                if not cr_ok:
                    logger.warning("LumaDeck: CloudRedirect not installed/injected after headcrab "
                                   "— likely a transient drop")

                # headcrab installs SLSsteam but not .NET 9. Steamless needs it,
                # so we install it here in the same "Install / Reinstall" click.
                # ensure_dotnet_available() is a no-op if .NET 9 is already there.
                INSTALL_STATE["progress"] = "Installing .NET 9 runtime if missing..."
                loop = asyncio.get_event_loop()
                dotnet_ok = await loop.run_in_executor(None, ensure_dotnet_available)

                INSTALL_STATE["status"] = "done"
                if dotnet_ok and cr_ok:
                    INSTALL_STATE["progress"] = "Installation complete!"
                elif not dotnet_ok:
                    INSTALL_STATE["progress"] = (
                        "SLSsteam installed. .NET 9 install failed — "
                        "click Install / Reinstall Dependencies again to retry."
                    )
                else:
                    INSTALL_STATE["progress"] = (
                        "SLSsteam installed, but CloudRedirect didn't (cloud saves) — "
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


# NOTE: LumaDeck no longer seeds a hardcoded config.yaml. The force-cr-install
# headcrab patch removed the need to pre-create one (it dropped the DisableCloud
# gate), and SLSsteam writes its own config on first run with its exact current
# schema. We only enforce the flags we depend on afterwards — see
# ensure_slssteam_flags().


def _set_disablecloud_no(config_path: str) -> tuple[bool, str]:
    """Flip `DisableCloud: yes` -> `DisableCloud: no` in SLSsteam's config.yaml.

    headcrab gates CloudRedirect on this exact line (`crconfigcheck` greps
    for `DisableCloud: no`), so we have to flip it before invoking headcrab —
    the script doesn't do it itself.

    Returns (ok, message). ok=False only when the config is missing or the
    DisableCloud line is absent entirely (= SLSsteam wasn't installed/
    initialised yet).
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


def _set_disableupdates_no(config_path: str) -> tuple[bool, str]:
    """Set `DisableUpdates: no` in SLSsteam's config.yaml.

    SLSsteam 20260714+ defaults DisableUpdates to `yes`, which stops any app
    matched by `isAddedAppId(appId) || !isSubscribed(appId)` from auto-updating.
    Every LumaDeck-added game is an AdditionalApps entry, so `yes` freezes exactly
    our games ("Update required" that never downloads). Owned games are unaffected
    either way. We want `no` so added games update like normal (the old lumalinux
    runtime unblock did the same, and is obsolete now that this is a config toggle).

    The key is new, so a config predating it has no line — append it rather than
    fail. Idempotent. Returns (ok, message).
    """
    if not os.path.isfile(config_path):
        return False, f"SLSsteam config not found at {config_path} — install dependencies first"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return False, f"Cannot read SLSsteam config: {exc}"

    new_content, n = re.subn(
        r"^(\s*DisableUpdates\s*:\s*)yes\s*$",
        r"\1no",
        content,
        flags=re.MULTILINE,
    )
    appended = False
    if n == 0:
        if re.search(r"^\s*DisableUpdates\s*:\s*no\s*$", content, flags=re.MULTILINE):
            return True, "DisableUpdates already set to no"
        # Key absent (config predates it) — append it.
        new_content = content + ("" if content.endswith("\n") else "\n") + "DisableUpdates: no\n"
        appended = True

    try:
        tmp = config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp, config_path)
        return True, ("DisableUpdates set to no (appended)" if appended else "DisableUpdates flipped to no")
    except Exception as exc:
        return False, f"Cannot write SLSsteam config: {exc}"


def ensure_slssteam_flags() -> dict:
    """Ensure the three SLSsteam config flags LumaDeck depends on, on the config
    SLSsteam writes itself (we no longer seed a hardcoded one). Idempotent, and
    SLSsteam hot-reloads config.yaml so no restart is needed.

        DisableCloud: no   — CloudRedirect owns cloud saves; SLSsteam must not disable them
        DisableUpdates: no — added (unowned) games must be allowed to auto-update
        SafeMode: yes      — auto-disable SLSsteam on an unknown steamclient.so hash (Deck gamemode)

    Returns {"applied": bool, ...}. applied=False means the config isn't there yet
    (SLSsteam writes it on its first injected run) — the caller should retry later.
    """
    path = get_slssteam_config_path()
    if not os.path.isfile(path):
        return {"applied": False, "reason": "SLSsteam config not created yet"}
    results = {
        "DisableCloud": _set_disablecloud_no(path),
        "DisableUpdates": _set_disableupdates_no(path),
        "SafeMode": _set_safemode_yes(path),
    }
    return {"applied": True, "results": {k: {"ok": v[0], "msg": v[1]} for k, v in results.items()}}


def _set_playnotowned_no(config_path: str) -> tuple[bool, str]:
    """Flip `PlayNotOwnedGames: yes` -> `PlayNotOwnedGames: no` in config.yaml.

    Headcrab forces PlayNotOwnedGames: yes (`sed -i .../PlayNotOwnedGames: yes/`
    in headcrab.sh), which makes SLSsteam treat ANY non-owned appid as owned.
    LumaDeck instead injects each added game into AdditionalApps (via
    steamidra_lite), so ownership is already targeted per-game — the global flag
    is redundant and broader than intended. We flip it back to no after headcrab,
    exactly like SafeMode/DisableCloud, so only the games the user actually added
    are treated as owned.

    NOTE: SLSsteam removed the PlayNotOwnedGames option in 20260707 (commit
    84c3672). On that build and later the key is simply absent and there is
    nothing to flip, so a missing line is now treated as success (no-op), not an
    error; otherwise a healthy new-SLSsteam install would report a false
    "reinstall dependencies". The flip is kept for users still on an older
    SLSsteam where the option (and Headcrab's forced `yes`) still exist.

    Returns (ok, message). ok=False only on an IO error reading/writing the
    config; a missing PlayNotOwnedGames line is ok=True (no-op).
    """
    if not os.path.isfile(config_path):
        return False, f"SLSsteam config not found at {config_path} — install dependencies first"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return False, f"Cannot read SLSsteam config: {exc}"

    new_content, n = re.subn(
        r"^(\s*PlayNotOwnedGames\s*:\s*)yes\s*$",
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
            return True, "PlayNotOwnedGames flipped to no"
        except Exception as exc:
            return False, f"Cannot write SLSsteam config: {exc}"

    if re.search(r"^\s*PlayNotOwnedGames\s*:\s*no\s*$", content, flags=re.MULTILINE):
        return True, "PlayNotOwnedGames already set to no"

    return True, "PlayNotOwnedGames absent (removed in SLSsteam 20260707+): nothing to flip"


async def install_lumalinux(gamemode: bool = True) -> dict:
    """Run lumalinux/install.sh from the jayool/lumalinux repo.

    (`gamemode` is accepted for a uniform quick_install() call signature but
    ignored here — lumalinux never touches Steam at runtime, no kills to patch.)

    Unlike headcrab, this one does NOT touch Steam at
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


async def quick_install(gamemode: bool = True) -> dict:
    """Run the installers in dependency order, stopping at the first failure:

        1. dependencies   — SLSsteam + CloudRedirect + .NET 9 (install_dependencies)
        2. lumalinux      — liblumalinux.so + steam.sh patch   (install_lumalinux)

    dependencies now installs CloudRedirect in the same headcrab run (it sets
    DisableCloud: no first), so there's no separate CR step — one headcrab, not
    two.

    gamemode=False is the DESKTOP variant (run by the Desktop hand-off launcher
    when Steam is off the headcrab pin): headcrab keeps its Steam kills so the
    downgrade actually applies. In Game Mode that would trip the crash-loop wipe,
    which is exactly why an off-pin install must go through Desktop.

    Order matters: dependencies runs headcrab, which regenerates steam.sh from
    scratch — that would wipe lumalinux's managed block. lumalinux must therefore
    run LAST (it's patch-only and idempotent) so its steam.sh patch survives.

    Each sub-installer keeps updating its own state global with live progress;
    get_quick_install_status() merges that in for the currently-running step.
    The caller (frontend) does a single Steam restart at the end — the
    sub-installers don't restart Steam themselves.
    """
    global QUICK_INSTALL_STATE

    steps = [
        ("dependencies", install_dependencies, get_install_status),
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
        logger.info("LumaDeck: quick_install step %d/%d: %s (gamemode=%s)", i + 1, len(steps), name, gamemode)
        try:
            result = await runner(gamemode)
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
            "lumalinux": get_ll_install_status,
        }.get(state.get("step"))
        if live_getter:
            sub = live_getter()
            if sub.get("progress"):
                state["progress"] = sub["progress"]
            if sub.get("status") == "failed" and sub.get("error"):
                state["error"] = sub["error"]
    return state


async def reinject_installed() -> dict:
    """Re-inject every INSTALLED component into steam.sh, in dependency order.

    steam.sh is shared: SLSsteam, CloudRedirect and lumalinux each inject a
    block. install_dependencies runs headcrab, which REGENERATES steam.sh from
    scratch (installing + re-injecting BOTH SLSsteam and CloudRedirect in one
    pass). install_lumalinux only patches (idempotent), so it never wipes the
    others and must run LAST to survive the headcrab regeneration.

    Repairing injection with a single installer would silently break the others.
    This re-runs the installers for the components that are actually installed,
    in order (SLSsteam+CloudRedirect) -> lumalinux. SLSsteam and CloudRedirect are
    one unit now (same headcrab), so a repair on a legacy SLSsteam-only setup also
    (re)installs CloudRedirect — harmless, it's inert until a provider is set. It
    never pulls in lumalinux if the user doesn't have it.

    Used to repair a `not_injected` component (any repair that runs headcrab).
    Shares QUICK_INSTALL_STATE so the frontend polls
    the same get_quick_install_status().
    """
    steps = []
    # One headcrab (install_dependencies) re-installs and re-injects BOTH
    # SLSsteam and CloudRedirect, so run it when either is present.
    if check_slssteam_installed() or check_cloudredirect_installed():
        steps.append(("dependencies", install_dependencies, get_install_status))
    if check_lumalinux_installed():
        steps.append(("lumalinux", install_lumalinux, get_ll_install_status))

    if not steps:
        return {"success": True, "skipped": "nothing installed"}
    return await _run_install_steps(steps, "Re-injecting")


async def _run_install_steps(steps, verb: str = "Running") -> dict:
    """Run a list of (name, async runner, status_getter) steps in order, driving
    QUICK_INSTALL_STATE so the frontend polls get_quick_install_status uniformly.
    Stops at the first failure. Shared by reinject_installed and apply_component."""
    global QUICK_INSTALL_STATE
    if not steps:
        return {"success": True, "skipped": "nothing to do"}

    QUICK_INSTALL_STATE = {
        "status": "installing",
        "step": steps[0][0],
        "stepIndex": 0,
        "totalSteps": len(steps),
        "progress": f"{verb}...",
        "error": None,
    }
    logger.info("LumaDeck: _run_install_steps (%d steps)", len(steps))

    for i, (name, runner, status_getter) in enumerate(steps):
        QUICK_INSTALL_STATE["step"] = name
        QUICK_INSTALL_STATE["stepIndex"] = i
        QUICK_INSTALL_STATE["progress"] = f"{verb} {name} ({i + 1}/{len(steps)})..."
        logger.info("LumaDeck: step %d/%d: %s", i + 1, len(steps), name)
        try:
            result = await runner()
        except Exception as exc:
            logger.exception("LumaDeck: step %s crashed: %s", name, exc)
            QUICK_INSTALL_STATE["status"] = "failed"
            QUICK_INSTALL_STATE["error"] = f"{name} crashed: {exc}"
            return {"success": False, "failedStep": name}

        if not (isinstance(result, dict) and result.get("success")):
            sub = status_getter()
            QUICK_INSTALL_STATE["status"] = "failed"
            QUICK_INSTALL_STATE["error"] = sub.get("error") or f"{name} failed"
            QUICK_INSTALL_STATE["progress"] = sub.get("progress", "")
            logger.error("LumaDeck: failed at %s: %s", name, QUICK_INSTALL_STATE["error"])
            return {"success": False, "failedStep": name}

    QUICK_INSTALL_STATE["status"] = "done"
    QUICK_INSTALL_STATE["stepIndex"] = len(steps)
    QUICK_INSTALL_STATE["progress"] = "Complete!"
    logger.info("LumaDeck: _run_install_steps finished OK")
    return {"success": True}


async def apply_component(component_id: str, op: str = "repair") -> dict:
    """Install / repair / update one component, keeping steam.sh correct.

    `op` (install|repair|update) is the same mechanically — every op re-runs the
    component's installer(s), which always fetch the latest, so a repair and an
    update run identical code; `op` is only the trigger/label. The per-component
    cascade follows DESIGN_UI.md §3b:

      - slssteam /
        cloudredirect: both are installed by the same headcrab run, so repairing
                       either re-runs it and re-injects the whole installed set in
                       order = reinject_installed.
      - lumalinux:     patch-only, touches nobody else → install_lumalinux alone.
      - core:          install_dependencies (SLSsteam + CloudRedirect in one
                       headcrab) → install_lumalinux.

    Drives QUICK_INSTALL_STATE; poll get_quick_install_status.
    """
    if component_id in ("slssteam", "cloudredirect"):
        return await reinject_installed()

    if component_id == "lumalinux":
        return await _run_install_steps(
            [("lumalinux", install_lumalinux, get_ll_install_status)], "Applying")

    if component_id == "core":
        # install_dependencies installs SLSsteam + CloudRedirect together, so no
        # separate CR step is needed.
        steps = [("dependencies", install_dependencies, get_install_status)]
        steps.append(("lumalinux", install_lumalinux, get_ll_install_status))
        return await _run_install_steps(steps, "Installing")

    return {"success": False, "error": f"unknown component '{component_id}'"}

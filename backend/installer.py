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
    get_slssteam_config_path,
    get_slssteam_config_dir,
    real_home,
    real_user,
    real_uid,
)
from dotnet import find_dotnet_path
from subprocess_env import clean_env

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# WS2: state for the wrapper-model installer (lumalinux/setup.sh), which replaces
# the headcrab install_dependencies + install_lumalinux pair with one script.
SETUP_INSTALL_STATE = {
    "status": "idle",
    "progress": "",
    "error": None,
}

# setup.sh source (main). Overridable for testing via LUMADECK_SETUP_URL.
SETUP_SH_URL = os.environ.get(
    "LUMADECK_SETUP_URL",
    "https://raw.githubusercontent.com/jayool/lumalinux/main/setup.sh",
)

# State for the "Quick Install" flow. WS2/WS3: it's now a single setup.sh step
# ("stack"); totalSteps is set dynamically from the step list at run time.
QUICK_INSTALL_STATE = {
    "status": "idle",
    "step": None,
    "stepIndex": 0,
    "totalSteps": 1,
    "progress": "",
    "error": None,
}


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
        r"^(DisableCloud\s*:\s*)yes\s*$",
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

    if re.search(r"^DisableCloud\s*:\s*no\s*$", content, flags=re.MULTILINE):
        return True, "DisableCloud already set to no"

    return False, "DisableCloud line missing from SLSsteam config — reinstall dependencies"


def _set_safemode_no(config_path: str) -> tuple[bool, str]:
    """Flip `SafeMode: yes` -> `SafeMode: no` in SLSsteam's config.yaml.

    SafeMode makes SLSsteam auto-disable (unload + return) whenever steamclient.so
    does not match a known-good hash. We used to force it ON for Deck gamemode, but
    the hash is unique per build, so a brand-new yet fully compatible Steam client
    degrades the whole stack until AceSLS ships the new hash, and it is what fires
    the `Unknown steamclient.so hash! Aborting...` self-abort on fresh builds.

    SLSsteam's own default is `no`: on a hash mismatch it does NOT block, it tries
    to hook, and still aborts gracefully if the pattern/VFTable scan fails
    (`Failed to find all patterns! Aborting...`). So the scan is the real gate, not
    the hash. We stop overriding SLSsteam's default and let it ride fresh builds.
    (WarnHashMissmatch is already `no` in SLSsteam's schema, so no user-facing
    warning fires under SafeMode=no; we do not touch it.) Existing installs that we
    previously flipped to `yes` get flipped back here.

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
        r"^(SafeMode\s*:\s*)yes\s*$",
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
            return True, "SafeMode flipped to no"
        except Exception as exc:
            return False, f"Cannot write SLSsteam config: {exc}"

    if re.search(r"^SafeMode\s*:\s*no\s*$", content, flags=re.MULTILINE):
        return True, "SafeMode already set to no"

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
        r"^(DisableUpdates\s*:\s*)yes\s*$",
        r"\1no",
        content,
        flags=re.MULTILINE,
    )
    appended = False
    if n == 0:
        if re.search(r"^DisableUpdates\s*:\s*no\s*$", content, flags=re.MULTILINE):
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
        SafeMode: no       — let SLSsteam hook fresh builds (scan is the gate, not the hash); don't override its default

    Returns {"applied": bool, ...}. applied=False means the config isn't there yet
    (SLSsteam writes it on its first injected run) — the caller should retry later.
    """
    path = get_slssteam_config_path()
    if not os.path.isfile(path):
        return {"applied": False, "reason": "SLSsteam config not created yet"}
    # Complete any missing keys FIRST (append-only) so the on-disk config matches
    # SLSsteam's current schema. This silences SLSsteam's "Missing key(s)" toast on
    # legacy/partial configs AND guarantees the three flag lines below exist for the
    # flip helpers to toggle (so SafeMode no longer fails to apply when its line is
    # absent). No-op when already complete; never touches existing bytes.
    try:
        from slssteam_schema import complete_slssteam_config
        completion = complete_slssteam_config(path)
    except Exception as exc:
        logger.warning(f"LumaDeck: SLSsteam config completion failed (non-fatal): {exc}")
        completion = {"completed": False, "added": [], "reason": str(exc)}
    results = {
        "DisableCloud": _set_disablecloud_no(path),
        "DisableUpdates": _set_disableupdates_no(path),
        "SafeMode": _set_safemode_no(path),
    }
    return {"applied": True, "completion": completion,
            "results": {k: {"ok": v[0], "msg": v[1]} for k, v in results.items()}}


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


async def install_via_setup(gamemode: bool = True) -> dict:
    """WS2: install the whole unlock stack via lumalinux/setup.sh (wrapper model).

    Replaces the headcrab install_dependencies + install_lumalinux pair with ONE
    script. setup.sh fetches SLSsteam + library-inject + CloudRedirect (+ its app)
    + netsock + lumalinux + .NET 9, applies the SLSsteam config flags, writes the
    injection wrapper + Game Mode drop-in (both via the crash-loop fail-safe), and
    covers Desktop + Game Mode. No headcrab, no downgrade, no freeze, no steam.sh.

    `gamemode` is accepted for a uniform step signature but ignored — setup.sh
    handles both modes itself. Idempotent, so this is also the repair/reinject path.
    """
    global SETUP_INSTALL_STATE
    SETUP_INSTALL_STATE = {"status": "installing", "progress": "Starting installer...", "error": None}
    logger.info("LumaDeck: install_via_setup() entered (url=%s)", SETUP_SH_URL)

    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="lumadeck_setup_")
        script_path = os.path.join(tmp_dir, "setup.sh")
        SETUP_INSTALL_STATE["progress"] = "Downloading setup.sh..."
        if not await _download(SETUP_SH_URL, script_path):
            SETUP_INSTALL_STATE["status"] = "failed"
            SETUP_INSTALL_STATE["error"] = "Failed to download setup.sh"
            return {"success": False}
        os.chmod(script_path, 0o700)

        try:
            with open(script_path, "r", encoding="utf-8", errors="replace") as f:
                if not f.readline(256).startswith("#"):
                    SETUP_INSTALL_STATE["status"] = "failed"
                    SETUP_INSTALL_STATE["error"] = "Downloaded file does not look like a shell script"
                    return {"success": False}
        except Exception as read_exc:
            SETUP_INSTALL_STATE["status"] = "failed"
            SETUP_INSTALL_STATE["error"] = f"Cannot read setup.sh: {read_exc}"
            return {"success": False}

        SETUP_INSTALL_STATE["progress"] = "Running installer..."
        # setup.sh is ENTIRELY $HOME-based (SLSsteam, config, wrapper, .dotnet,
        # systemd --user). Decky runs this backend as ROOT, so a plain `bash
        # setup.sh` would (a) install everything under /root — where Steam (uid
        # 1000) never looks — and (b) fail to reach the deck user's systemd --user
        # session, silently skipping the Game Mode drop-in + guardian (the whole
        # point). So when we're root, run it AS the real user in their session
        # (HOME + XDG_RUNTIME_DIR + DBUS), mirroring desktop_handoff. mkdtemp is
        # 0700/root, so open up the dir + script first or the deck user can't read
        # them. When already running as the real user (the Desktop hand-off path,
        # quick_install_cli), run directly — HOME/session are already correct.
        # The proven `curl|bash setup.sh` path (quick_install_cli, already deck)
        # runs directly and we DON'T touch the session — the real session already
        # has the correct XDG_RUNTIME_DIR/DBUS, and overwriting them with computed
        # values could break a path that works. Only pin HOME (already == $HOME
        # there, so effectively a no-op), matching dotnet.py / downloads.py. All
        # the sudo/session machinery is gated on euid==0, so the proven path is
        # unchanged except for that explicit HOME.
        if os.geteuid() == 0 and real_uid() != 0:
            _uid = real_uid()
            _runtime = f"/run/user/{_uid}"
            try:
                os.chmod(tmp_dir, 0o755)
                os.chmod(script_path, 0o755)
            except Exception:
                pass
            argv = [
                "sudo", "-u", real_user(), "env",
                f"HOME={real_home()}",
                f"XDG_RUNTIME_DIR={_runtime}",
                f"DBUS_SESSION_BUS_ADDRESS=unix:path={_runtime}/bus",
                "bash", script_path,
            ]
            proc_env = clean_env()
        else:
            argv = ["bash", script_path]
            proc_env = clean_env(HOME=real_home())
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=tmp_dir,
            env=proc_env,
        )

        async def _read_output():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                SETUP_INSTALL_STATE["progress"] = line.decode("utf-8", errors="replace").strip()

        asyncio.create_task(_read_output())
        await process.wait()

        if process.returncode == 0:
            # Verify the post-condition instead of trusting the exit code: the
            # wrapper + the two load-bearing .so's must be on disk.
            wrapper = os.path.join(real_home(), ".local", "share", "SLSsteam", "path", "steam")
            if not (os.path.exists(wrapper)
                    and check_slssteam_installed()
                    and check_lumalinux_installed()):
                SETUP_INSTALL_STATE["status"] = "failed"
                SETUP_INSTALL_STATE["error"] = (
                    "Installer finished but the wrapper or a core .so is missing "
                    "(likely a transient network drop). Retry."
                )
            else:
                # Catch-up lift: reconcile the Steam-update freeze now that fresh
                # components are in place. maybe_lift_freeze lifts a FOREIGN pin
                # (headcrab's — no `# lumalinux` signature; written on every headcrab
                # install, so a migrating device arrives frozen with no break to
                # recover from) ON SIGHT, and lifts OUR signed break-recovery pin only
                # once the ecosystem has caught up (pin advanced past our build +
                # latest lumalinux supports it). No-op when not pinned. This is the
                # step that un-freezes every device migrating from headcrab.
                try:
                    from steam_freeze import maybe_lift_freeze
                    from headcrab_compat import check_headcrab_compat
                    lift = maybe_lift_freeze(await check_headcrab_compat())
                    if lift.get("lifted"):
                        logger.info("LumaDeck: lifted Steam-update freeze (catch-up): %s", lift)
                    elif not lift.get("success", True):
                        logger.warning("LumaDeck: freeze lift failed: %s", lift)
                except Exception as exc:
                    logger.warning("LumaDeck: steam freeze lift check failed: %s", exc)

                SETUP_INSTALL_STATE["status"] = "done"
                SETUP_INSTALL_STATE["progress"] = "Stack installed!"
        else:
            SETUP_INSTALL_STATE["status"] = "failed"
            SETUP_INSTALL_STATE["error"] = (
                f"Installer exited with code {process.returncode} — "
                f"last line: {SETUP_INSTALL_STATE['progress']}"
            )

    except Exception as exc:
        SETUP_INSTALL_STATE["status"] = "failed"
        SETUP_INSTALL_STATE["error"] = str(exc)
        logger.exception("LumaDeck: install_via_setup crashed: %s", exc)
    finally:
        if tmp_dir:
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    logger.info("LumaDeck: install_via_setup finished, state=%s", SETUP_INSTALL_STATE)
    return {"success": SETUP_INSTALL_STATE["status"] == "done"}


def get_setup_status() -> dict:
    return SETUP_INSTALL_STATE.copy()


async def quick_install(gamemode: bool = True) -> dict:
    """Run the wrapper-model installer, stopping at the first failure:

        1. stack — SLSsteam + library-inject + CloudRedirect + netsock + lumalinux
                   + .NET 9 + the injection wrapper (lumalinux/setup.sh)

    WS2/WS3: one idempotent setup.sh run replaces the old headcrab
    install_dependencies + install_lumalinux pair — no Steam downgrade, no freeze,
    no steam.sh patch. The break-recovery downgrade is a separate escape-hatch
    (desktop_handoff REAL payload → downgrade.sh).

    `gamemode` is accepted for a uniform step signature but setup.sh handles both
    modes itself. install_via_setup keeps updating SETUP_INSTALL_STATE with live
    progress; get_quick_install_status() merges that in for the running step. The
    caller (frontend) does a single Steam restart at the end.
    """
    global QUICK_INSTALL_STATE

    # WS2: one setup.sh call does the whole stack (was headcrab + lumalinux).
    steps = [
        ("stack", install_via_setup, get_setup_status),
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
            "stack": get_setup_status,
        }.get(state.get("step"))
        if live_getter:
            sub = live_getter()
            if sub.get("progress"):
                state["progress"] = sub["progress"]
            if sub.get("status") == "failed" and sub.get("error"):
                state["error"] = sub["error"]
    return state


async def reinject_installed() -> dict:
    """Re-establish injection for every INSTALLED component.

    WS2/WS3: in the wrapper model there is no per-component steam.sh cascade —
    setup.sh is one idempotent script that (re)installs the whole stack and
    re-asserts the wrapper + Game Mode drop-in. So a repair of a `not_injected`
    component is just a single setup.sh run, gated on something being installed
    (never pulls in the stack on a bare device).

    Shares QUICK_INSTALL_STATE so the frontend polls get_quick_install_status().
    """
    steps = []
    # WS2: setup.sh re-installs and re-injects the WHOLE stack idempotently, so run
    # it if any component is present (reinject = re-run setup.sh).
    if (check_slssteam_installed() or check_cloudredirect_installed()
            or check_lumalinux_installed()):
        steps.append(("stack", install_via_setup, get_setup_status))

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
    installer, which always fetches the latest, so repair and update run identical
    code; `op` is only the trigger/label.

    WS2: in the wrapper model there is no per-component cascade — setup.sh is one
    idempotent script that (re)installs the whole stack and re-asserts the wrapper +
    Game Mode drop-in. So every component id maps to a single setup.sh run.

    Drives QUICK_INSTALL_STATE; poll get_quick_install_status.
    """
    # WS2: every component maps to one idempotent setup.sh run (it (re)installs
    # SLSsteam + CloudRedirect + netsock + lumalinux + .NET and re-asserts the
    # wrapper + Game Mode drop-in). Per-component granularity collapses into it.
    if component_id in ("slssteam", "cloudredirect", "lumalinux", "core"):
        return await _run_install_steps(
            [("stack", install_via_setup, get_setup_status)], "Installing")

    return {"success": False, "error": f"unknown component '{component_id}'"}

"""Dependency installer — check and install ACCELA, SLSsteam, .NET runtime."""

from __future__ import annotations

import asyncio
import os
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
    get_slssteam_config_path,
)
from dotnet import find_dotnet_path, ensure_dotnet_available

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
        "cloudredirect": check_cloudredirect_installed(),
        "cloudredirectPath": find_cloudredirect_root(),
        "cloudredirectActive": check_cloudredirect_active(),
        # True if ~/.config/CloudRedirect/tokens_<provider>.json exists. The
        # provider sign-in flow is GUI-only inside the CR Flatpak — gamemode
        # can't drive it, so the UI uses this to nudge the user to desktop
        # mode after we drop the .so + flatpak in place.
        "cloudredirectAuthed": check_cloudredirect_authed(),
    }


async def install_dependencies() -> dict:
    """Run the enter-the-wired installer script."""
    global INSTALL_STATE
    INSTALL_STATE = {"status": "installing", "progress": "Starting installer...", "error": None}

    tmp_dir = None
    try:
        BASE_URL = "https://raw.githubusercontent.com/ciscosweater/enter-the-wired/main"
        # enter-the-wired requires accela and fix-deps in the same directory.
        # Download all three into a temp dir so local-execution branch works.
        tmp_dir = tempfile.mkdtemp(prefix="lumadeck_etw_")
        scripts = {
            "enter-the-wired": f"{BASE_URL}/enter-the-wired",
            "accela": f"{BASE_URL}/accela",
            "fix-deps": f"{BASE_URL}/fix-deps",
        }

        for name, url in scripts.items():
            INSTALL_STATE["progress"] = f"Downloading {name}..."
            dest = os.path.join(tmp_dir, name)
            dl = await asyncio.create_subprocess_exec(
                "curl", "-fsSL", "-o", dest, url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await dl.wait()
            if dl.returncode != 0:
                INSTALL_STATE["status"] = "failed"
                INSTALL_STATE["error"] = f"Failed to download {name}"
                return {"success": False}
            os.chmod(dest, 0o700)

        # Verify main script looks like a shell script
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

        INSTALL_STATE["progress"] = "Running installer..."
        # Pipe `yes y` into bash so any interactive prompt that survives the
        # script chain (the ACCELAINSTALL binary inside the ACCELA tarball
        # is the one known case — it asks "Do you want to proceed with the
        # installation? [y/N]" and reads stdin) gets auto-confirmed. None
        # of the bash scripts in the chain (enter-the-wired, accela,
        # fix-deps, headcrab) use `read` themselves, and every pacman call
        # is already --noconfirm, so the y's are absorbed only by
        # ACCELAINSTALL. No destructive prompts exist in this chain that a
        # blanket "y" would answer incorrectly.
        process = await asyncio.create_subprocess_shell(
            f"yes y | bash {main_script}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=tmp_dir,
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
                # SLSsteam + ACCELA succeeded; only .NET failed. Don't fail
                # the whole operation — the user can hit Install/Reinstall
                # again to retry just the .NET step (the no-op short-circuit
                # in ensure_dotnet_available skips re-installing what's there).
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
    finally:
        if tmp_dir:
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    return {"success": INSTALL_STATE["status"] == "done"}


def get_install_status() -> dict:
    return INSTALL_STATE.copy()


def _set_disablecloud_no(config_path: str) -> tuple[bool, str]:
    """Flip `DisableCloud: yes` -> `DisableCloud: no` in SLSsteam's config.yaml.

    headcrab.pages.dev gates CloudRedirect on this exact line (crconfigcheck
    in the upstream script greps for `DisableCloud: no`), so we have to
    flip it before invoking headcrab — the script doesn't do it itself.

    Returns (ok, message). ok=False only when the config is missing or the
    DisableCloud line is absent entirely (= SLSsteam wasn't initialised
    via enter-the-wired yet, which is the user's prerequisite to install).
    """
    import re

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


async def install_cloudredirect() -> dict:
    """Run headcrab.pages.dev with DisableCloud flipped to `no`.

    headcrab installs CloudRedirect conditionally: the script greps the
    SLSsteam config and only invokes its crinstall() when it finds
    `DisableCloud: no`. We flip the line, then invoke the same shell
    chain enter-the-wired uses, with `yes y` piped in defensively (same
    rationale as install_dependencies — ACCELAINSTALL is the one known
    interactive binary in the chain).

    The script overwrites ~/.local/share/Steam/steam.sh with the cr-test
    variant that includes LD_PRELOAD=cloud_redirect.so — lumalinux's
    install.sh must be re-run separately to reapply its line.
    """
    global CR_INSTALL_STATE
    CR_INSTALL_STATE = {"status": "installing", "progress": "Starting installer...", "error": None}

    tmp_dir = None
    try:
        config_path = get_slssteam_config_path()
        CR_INSTALL_STATE["progress"] = "Enabling DisableCloud: no in SLSsteam config..."
        ok, msg = _set_disablecloud_no(config_path)
        if not ok:
            CR_INSTALL_STATE["status"] = "failed"
            CR_INSTALL_STATE["error"] = msg
            return {"success": False}

        tmp_dir = tempfile.mkdtemp(prefix="lumadeck_cr_")
        script_path = os.path.join(tmp_dir, "headcrab")
        CR_INSTALL_STATE["progress"] = "Downloading headcrab installer..."
        dl = await asyncio.create_subprocess_exec(
            "curl", "-fsSL", "-o", script_path, "https://headcrab.pages.dev",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await dl.wait()
        if dl.returncode != 0:
            CR_INSTALL_STATE["status"] = "failed"
            CR_INSTALL_STATE["error"] = "Failed to download headcrab installer"
            return {"success": False}
        os.chmod(script_path, 0o700)

        try:
            with open(script_path, "r", encoding="utf-8", errors="replace") as f:
                first_line = f.readline(256)
            if not first_line.startswith("#"):
                CR_INSTALL_STATE["status"] = "failed"
                CR_INSTALL_STATE["error"] = "Downloaded file does not look like a shell script"
                return {"success": False}
        except Exception as read_exc:
            CR_INSTALL_STATE["status"] = "failed"
            CR_INSTALL_STATE["error"] = f"Cannot read installer script: {read_exc}"
            return {"success": False}

        CR_INSTALL_STATE["progress"] = "Running installer (this will close Steam)..."
        process = await asyncio.create_subprocess_shell(
            f"yes y | bash {script_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=tmp_dir,
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
            CR_INSTALL_STATE["status"] = "done"
            CR_INSTALL_STATE["progress"] = "CloudRedirect installed!"
        else:
            CR_INSTALL_STATE["status"] = "failed"
            CR_INSTALL_STATE["error"] = f"Installer exited with code {process.returncode}"

    except Exception as exc:
        CR_INSTALL_STATE["status"] = "failed"
        CR_INSTALL_STATE["error"] = str(exc)
    finally:
        if tmp_dir:
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

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

    The user must restart Steam manually after this returns — we surface
    that as a toast, not as an automatic action, because gamemode = killing
    Steam = killing whatever the user is doing.
    """
    global LL_INSTALL_STATE
    LL_INSTALL_STATE = {"status": "installing", "progress": "Starting installer...", "error": None}

    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="lumadeck_ll_")
        script_path = os.path.join(tmp_dir, "install.sh")
        LL_INSTALL_STATE["progress"] = "Downloading lumalinux installer..."
        dl = await asyncio.create_subprocess_exec(
            "curl", "-fsSL", "-o", script_path,
            "https://raw.githubusercontent.com/jayool/lumalinux/main/install.sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await dl.wait()
        if dl.returncode != 0:
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
    finally:
        if tmp_dir:
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    return {"success": LL_INSTALL_STATE["status"] == "done"}


def get_ll_install_status() -> dict:
    return LL_INSTALL_STATE.copy()

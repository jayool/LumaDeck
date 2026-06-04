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
)

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


def check_dependencies() -> dict:
    """Check if ACCELA, SLSsteam, and .NET runtime are available."""
    accela_installed = check_accela_installed()
    slssteam_installed = check_slssteam_installed()
    accela_root = find_accela_root()

    # Check for .NET runtime - try multiple locations since Decky runs as root
    dotnet_available = False
    dotnet_path = None
    import subprocess

    # Candidate dotnet binary paths (SteamOS / Decky runs as root, so ~ is /root/)
    dotnet_candidates = [
        "dotnet",  # system PATH
        "/home/deck/.dotnet/dotnet",
        "/home/deck/.local/share/dotnet/dotnet",
        os.path.expanduser("~/.dotnet/dotnet"),
    ]
    # Also check inside ACCELA directory
    if accela_root:
        dotnet_candidates.append(os.path.join(accela_root, "dotnet", "dotnet"))
        dotnet_candidates.append(os.path.join(accela_root, "dotnet"))

    for candidate in dotnet_candidates:
        try:
            result = subprocess.run(
                [candidate, "--list-runtimes"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                dotnet_available = True
                dotnet_path = candidate
                break
        except Exception:
            continue

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
        process = await asyncio.create_subprocess_exec(
            "bash", main_script,
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
            INSTALL_STATE["status"] = "done"
            INSTALL_STATE["progress"] = "Installation complete!"
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

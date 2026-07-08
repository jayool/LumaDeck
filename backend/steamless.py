"""Steamless DRM removal — extracts Steamless CLI from ACCELA AppImage, runs independently."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile

from paths import data_dir, find_accela_root

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

# Utility executables to skip (by filename)
_SKIP_EXE_NAMES = {
    "UnityCrashHandler64.exe",
    "UnityCrashHandler32.exe",
    "unityCrashHandler64.exe",
    "unityCrashHandler32.exe",
    "CrashReportClient.exe",
    "CrashReportClient64.exe",
    "crashpad_handler.exe",
}

_download_state: dict = {"status": "idle"}
_steamless_state: dict = {}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _get_steamless_dir() -> str:
    return os.path.join(data_dir(), "Steamless")


def _find_steamless_cli() -> str | None:
    """Find Steamless.CLI.dll in the plugin's data directory."""
    root = _get_steamless_dir()
    if not os.path.isdir(root):
        return None
    # Walk to handle zip layouts that may create a subdirectory
    for dirpath, _, files in os.walk(root):
        if "Steamless.CLI.dll" in files:
            return os.path.join(dirpath, "Steamless.CLI.dll")
    return None


def _find_dotnet() -> str | None:
    """Find a working dotnet binary. Checks common Steam Deck locations."""
    import shutil
    import subprocess

    candidates = [
        "/home/deck/.dotnet/dotnet",
        "/home/deck/.local/share/dotnet/dotnet",
        os.path.expanduser("~/.dotnet/dotnet"),
        os.path.expanduser("~/.local/share/dotnet/dotnet"),
    ]
    system = shutil.which("dotnet")
    if system:
        candidates.insert(0, system)

    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            r = subprocess.run([path, "--list-runtimes"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return path
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------

def check_steamless_installed() -> str:
    cli = _find_steamless_cli()
    dotnet = _find_dotnet()
    return json.dumps({
        "success": True,
        "installed": cli is not None,
        "cliPath": cli,
        "dotnetAvailable": dotnet is not None,
        "dotnetPath": dotnet,
    })


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

async def download_steamless() -> str:
    global _download_state
    if _download_state.get("status") == "downloading":
        return json.dumps({"success": False, "error": "Download already in progress."})

    accela_dir = find_accela_root()
    appimage = os.path.join(accela_dir, "ACCELA.AppImage") if accela_dir else None
    if not appimage or not os.path.isfile(appimage):
        return json.dumps({"success": False, "error": "ACCELA.AppImage not found. Install ACCELA first."})

    _download_state = {"status": "downloading", "progress": "Extracting from ACCELA AppImage..."}
    asyncio.ensure_future(_extract_task(appimage))
    return json.dumps({"success": True})


async def _extract_task(appimage: str):
    global _download_state
    tmp_dir = None
    try:
        loop = asyncio.get_running_loop()

        # Run AppImage extraction in executor (blocking)
        tmp_dir = tempfile.mkdtemp(prefix="steamless_extract_")
        logger.info(f"[LumaDeck/Steamless] Extracting from AppImage to {tmp_dir}")

        proc = await asyncio.create_subprocess_exec(
            appimage, "--appimage-extract", "bin/src/deps/Steamless/*",
            cwd=tmp_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)

        src = os.path.join(tmp_dir, "squashfs-root", "bin", "src", "deps", "Steamless")
        if not os.path.isdir(src):
            _download_state = {"status": "error", "error": "Steamless not found in AppImage."}
            return

        dest = _get_steamless_dir()
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

        cli = _find_steamless_cli()
        if cli:
            logger.info(f"[LumaDeck/Steamless] Installed at: {cli}")
            _download_state = {"status": "done"}
        else:
            _download_state = {"status": "error", "error": "Steamless.CLI.dll not found after extraction."}

    except asyncio.TimeoutError:
        _download_state = {"status": "error", "error": "AppImage extraction timed out."}
        logger.error("[LumaDeck/Steamless] Extraction timeout")
    except Exception as e:
        logger.error(f"[LumaDeck/Steamless] Extraction error: {e}")
        _download_state = {"status": "error", "error": str(e)}
    finally:
        if tmp_dir and os.path.isdir(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass


def get_steamless_download_status() -> str:
    return json.dumps({"success": True, "state": _download_state})


# ---------------------------------------------------------------------------
# DRM removal
# ---------------------------------------------------------------------------

import re as _re

_SKIP_PATTERNS = [
    r"^unins.*\.exe$",
    r"^setup.*\.exe$",
    r"^config.*\.exe$",
    r"^launcher.*\.exe$",
    r"^updater.*\.exe$",
    r"^patch.*\.exe$",
    r"^redist.*\.exe$",
    r"^vcredist.*\.exe$",
    r"^dxsetup.*\.exe$",
    r"^physx.*\.exe$",
    r".*crash.*\.exe$",
    r".*handler.*\.exe$",
    r".*unity.*\.exe$",
    r".*\.original\.exe$",
    r".*\.unpacked\.exe$",
]

def _should_skip(fname: str, fpath: str) -> bool:
    fl = fname.lower()
    if fname in _SKIP_EXE_NAMES:
        return True
    for pat in _SKIP_PATTERNS:
        if _re.match(pat, fl):
            return True
    try:
        if os.path.getsize(fpath) < 100 * 1024:  # < 100 KB
            return True
    except OSError:
        pass
    return False


def _exe_priority(fname: str, game_name: str, fpath: str) -> int:
    """Higher = process first. Mirrors ACCELA's priority logic."""
    fl = fname.lower()
    game_clean = "".join(c for c in game_name.lower() if c.isalnum())
    priority = 0
    if fl.startswith(game_clean):
        priority += 100
    elif game_clean in fl:
        priority += 80
    if fl in ("game.exe", "main.exe", "play.exe", "start.exe"):
        priority += 50
    try:
        size = os.path.getsize(fpath)
        if size > 50 * 1024 * 1024:
            priority += 30
        elif size > 10 * 1024 * 1024:
            priority += 20
        elif size > 5 * 1024 * 1024:
            priority += 10
    except OSError:
        pass
    if any(w in fl for w in ("editor", "tool", "config", "settings")):
        priority -= 20
    if any(w in fl for w in ("crash", "handler", "debug")):
        priority -= 50
    return max(0, priority)


def _scan_executables(game_dir: str) -> list:
    """Recursively find game .exe files with size/pattern filtering and priority sort."""
    game_name = os.path.basename(game_dir.rstrip("/\\"))
    found = []
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d != ".DepotDownloader"]
        for fname in files:
            if not fname.lower().endswith(".exe"):
                continue
            fpath = os.path.join(root, fname)
            if _should_skip(fname, fpath):
                logger.debug(f"[LumaDeck/Steamless] Skipping: {fname}")
                continue
            found.append((fpath, _exe_priority(fname, game_name, fpath)))
    found.sort(key=lambda x: x[1], reverse=True)
    return [f for f, _ in found]


def _swap_in_unpacked(exe_path: str) -> bool:
    """Put the DRM-free exe in place of the original after a successful Steamless
    run — the step LumaDeck was missing, so the game kept launching the still
    protected original.

    Steamless.CLI is non-destructive by design: `-f X.exe` writes a NEW file
    `X.exe.unpacked.exe` and never touches `X.exe`. The caller must swap it in.
    This mirrors what the ACCELA app does around the same CLI: back the original
    up to `<name>.original.exe` (which the scan skip-list ignores, so it's never
    re-processed) and move the unpacked exe onto the real name.

    Idempotent: on a re-run the pristine `.original.exe` backup is preserved, not
    clobbered with an already-patched exe. Returns True only if the swap happened.
    """
    unpacked = exe_path + ".unpacked.exe"
    if not os.path.isfile(unpacked):
        # Some Steamless builds name it "<base>.unpacked.exe" instead.
        alt = os.path.splitext(exe_path)[0] + ".unpacked.exe"
        if os.path.isfile(alt):
            unpacked = alt
        else:
            return False

    backup = os.path.splitext(exe_path)[0] + ".original.exe"
    try:
        if not os.path.exists(backup):
            shutil.move(exe_path, backup)        # keep the pristine original once
        elif os.path.exists(exe_path):
            os.remove(exe_path)                  # already backed up; drop the packed one
        shutil.move(unpacked, exe_path)          # DRM-free exe takes the real name
        try:
            st = os.stat(exe_path)
            os.chmod(exe_path, st.st_mode | 0o111)  # keep it executable
        except OSError:
            pass
        return True
    except OSError as e:
        logger.error(f"[LumaDeck/Steamless] swap-in failed for "
                     f"{os.path.basename(exe_path)}: {e}")
        return False


async def run_steamless(install_path: str) -> str:
    global _steamless_state

    if not install_path or not os.path.isdir(install_path):
        return json.dumps({"success": False, "error": "Game directory not found."})

    dotnet = _find_dotnet()
    if not dotnet:
        return json.dumps({"success": False, "error": ".NET not found. Install it via the installer."})

    cli = _find_steamless_cli()
    if not cli:
        return json.dumps({"success": False, "error": "Steamless not installed. Download it first."})

    exes = _scan_executables(install_path)
    if not exes:
        # Check if it's a Linux native game (has ELF binaries but no .exe)
        has_linux_bin = any(
            not f.endswith((".dll", ".so", ".txt", ".cfg", ".json", ".xml", ".png", ".jpg"))
            for f in os.listdir(install_path)
            if os.path.isfile(os.path.join(install_path, f))
        )
        if has_linux_bin:
            return json.dumps({"success": False, "error": "Linux native game — no .exe found. Steamless only works on Windows executables."})
        return json.dumps({"success": False, "error": "No Windows executables (.exe) found in game directory."})

    _steamless_state = {
        "status": "running",
        "total": len(exes),
        "processed": 0,
        "current": os.path.basename(exes[0]),
        "results": [],
    }

    asyncio.ensure_future(_run_task(dotnet, cli, exes))
    return json.dumps({"success": True, "total": len(exes)})


async def _run_task(dotnet: str, cli: str, exes: list):
    global _steamless_state
    results = []

    steamless_dir = os.path.dirname(cli)
    env = None
    if dotnet.startswith("/home/"):
        import os as _os
        dotnet_root = _os.path.dirname(_os.path.dirname(dotnet))
        env = {**__import__("os").environ, "DOTNET_ROOT": dotnet_root}

    for i, exe_path in enumerate(exes):
        fname = os.path.basename(exe_path)
        _steamless_state["current"] = fname
        _steamless_state["processed"] = i

        try:
            proc = await asyncio.create_subprocess_exec(
                dotnet, cli,
                "-f", exe_path,
                "--quiet", "--realign",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=steamless_dir,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            rc = proc.returncode
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            # exit 0 = DRM removed; exit 1 = no DRM found; >1 = error
            success = rc == 0
            no_drm = rc == 1
            if success:
                # DRM stripped from the copy — now put it in place (ACCELA's step).
                # If the swap fails, this is NOT a real success: the game would
                # still launch the protected original, so report it honestly.
                replaced = _swap_in_unpacked(exe_path)
                results.append({"file": fname, "success": replaced, "unpacked": True})
                if replaced:
                    logger.info(f"[LumaDeck/Steamless] unpacked + swapped in: {fname}")
                else:
                    logger.warning(f"[LumaDeck/Steamless] unpacked but swap-in failed "
                                   f"(original still in place): {fname}")
            elif no_drm:
                results.append({"file": fname, "success": False, "noDrm": True})
                logger.info(f"[LumaDeck/Steamless] no DRM: {fname}")
            else:
                results.append({"file": fname, "success": False})
                logger.warning(f"[LumaDeck/Steamless] error (rc={rc}): {fname} — {output[:200]}")
        except asyncio.TimeoutError:
            results.append({"file": fname, "success": False, "error": "timeout"})
            logger.warning(f"[LumaDeck/Steamless] Timeout: {fname}")
        except Exception as e:
            results.append({"file": fname, "success": False, "error": str(e)})
            logger.error(f"[LumaDeck/Steamless] Error on {fname}: {e}")

    success_count = sum(1 for r in results if r["success"])
    _steamless_state = {
        "status": "done",
        "total": len(exes),
        "processed": len(exes),
        "successCount": success_count,
        "current": "",
        "results": results,
    }
    logger.info(f"[LumaDeck/Steamless] Done: {success_count}/{len(exes)} unpacked")


def get_steamless_status() -> str:
    return json.dumps({"success": True, "state": _steamless_state})

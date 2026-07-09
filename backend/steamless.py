"""Steamless DRM removal — runs the bundled Steamless.CLI (.NET 9) directly.

Steamless.CLI ships inside the plugin at backend/deps/Steamless (a ~450 KB
.NET 9 build: the atom0s unpacker Variant plugins + SharpDisasm). It used to be
extracted from the ACCELA AppImage; bundling it drops that dependency entirely.
The only runtime requirement is the .NET 9 runtime, which dotnet.py installs
on demand from Microsoft's official script — also independent of ACCELA.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil

from paths import data_dir, backend_path
from dotnet import find_dotnet_path, ensure_dotnet_available

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

def _steamless_search_roots() -> list[str]:
    """Where Steamless.CLI may live, most-preferred first.

    1. backend/deps/Steamless — bundled with the plugin build (the normal case).
    2. data_dir()/Steamless — legacy location where the old ACCELA-extraction
       path installed it; kept so an existing install still resolves.
    """
    return [backend_path(os.path.join("deps", "Steamless")),
            os.path.join(data_dir(), "Steamless")]


def _find_steamless_cli() -> str | None:
    """Find Steamless.CLI.dll in the bundled deps (or the legacy data dir)."""
    for root in _steamless_search_roots():
        if not os.path.isdir(root):
            continue
        # Walk to handle any nested layout.
        for dirpath, _, files in os.walk(root):
            if "Steamless.CLI.dll" in files:
                return os.path.join(dirpath, "Steamless.CLI.dll")
    return None


async def _ensure_dotnet_async() -> str | None:
    """Return a working .NET 9 path, installing it if missing. None on failure.

    ensure_dotnet_available() blocks (downloads Microsoft's installer script and
    runs it), so it runs in a thread to keep the event loop responsive.
    """
    dotnet = find_dotnet_path()
    if dotnet:
        return dotnet
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, ensure_dotnet_available)
    return find_dotnet_path() if ok else None


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------

def check_steamless_installed() -> str:
    cli = _find_steamless_cli()
    dotnet = find_dotnet_path()
    return json.dumps({
        "success": True,
        "installed": cli is not None,
        "cliPath": cli,
        "dotnetAvailable": dotnet is not None,
        "dotnetPath": dotnet,
    })


# ---------------------------------------------------------------------------
# Prepare (.NET runtime)
# ---------------------------------------------------------------------------

async def download_steamless() -> str:
    """Steamless.CLI is bundled — there is nothing to download. The only
    prerequisite is the .NET 9 runtime, so this now installs that on demand.
    Kept under the original name so the existing frontend call still works."""
    global _download_state
    if _download_state.get("status") == "downloading":
        return json.dumps({"success": False, "error": "Already in progress."})
    if not _find_steamless_cli():
        return json.dumps({"success": False, "error": "Steamless.CLI is missing from this build."})

    _download_state = {"status": "downloading", "progress": "Ensuring .NET 9 runtime..."}
    asyncio.ensure_future(_prepare_task())
    return json.dumps({"success": True})


async def _prepare_task():
    global _download_state
    try:
        dotnet = await _ensure_dotnet_async()
        if dotnet:
            logger.info(f"[LumaDeck/Steamless] Ready (.NET at {dotnet})")
            _download_state = {"status": "done"}
        else:
            _download_state = {"status": "error", "error": ".NET 9 install failed."}
    except Exception as e:
        logger.error(f"[LumaDeck/Steamless] Prepare error: {e}")
        _download_state = {"status": "error", "error": str(e)}


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

    cli = _find_steamless_cli()
    if not cli:
        return json.dumps({"success": False, "error": "Steamless.CLI is missing from this build."})

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

    asyncio.ensure_future(_run_task(cli, exes))
    return json.dumps({"success": True, "total": len(exes)})


async def _run_task(cli: str, exes: list):
    global _steamless_state
    results = []

    # Ensure the .NET 9 runtime, installing it on first use (from Microsoft's
    # official script via dotnet.py — no ACCELA). Surfaced as progress so the
    # first run doesn't look stalled while .NET downloads.
    _steamless_state["current"] = "Preparing .NET 9 runtime..."
    dotnet = await _ensure_dotnet_async()
    if not dotnet:
        _steamless_state = {
            "status": "error",
            "total": len(exes),
            "processed": 0,
            "successCount": 0,
            "current": "",
            "results": [],
            "error": ".NET 9 runtime unavailable (auto-install failed).",
        }
        logger.error("[LumaDeck/Steamless] .NET 9 unavailable — aborting run")
        return

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

"""Workshop download management using DepotDownloaderMod (async port)."""

from __future__ import annotations

import asyncio
import os
import re
import stat
from typing import Optional

from paths import get_plugin_dir, data_path
from steam_utils import detect_steam_install_path, open_game_folder

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

# Workshop download state
workshop_state = {
    "status": "idle",
    "progress": 0.0,
    "message": "",
    "download_path": "",
}
_workshop_process: Optional[asyncio.subprocess.Process] = None


def _get_workshop_config_file() -> str:
    return data_path("workshop_path.txt")


def save_workshop_tool_path(path: str) -> dict:
    try:
        with open(_get_workshop_config_file(), "w", encoding="utf-8") as f:
            f.write(path.strip())
        return {"success": True, "message": "Path saved"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def load_workshop_tool_path() -> str:
    try:
        config_file = _get_workshop_config_file()
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _find_depot_downloader() -> str:
    """Find DepotDownloaderMod executable."""
    custom_path = load_workshop_tool_path()
    if custom_path and os.path.exists(custom_path):
        if os.path.isdir(custom_path):
            potential = os.path.join(custom_path, "DepotDownloaderMod")
            if os.path.exists(potential):
                return potential
        elif os.path.isfile(custom_path):
            return custom_path

    # Fallback: bundled in backend/
    base_path = os.path.join(get_plugin_dir(), "backend")
    return os.path.join(base_path, "DepotDownloaderMod")


async def _run_depot_downloader_workshop(appid: str, pubfile_id: str, download_dir: str) -> None:
    global workshop_state, _workshop_process

    exe_path = _find_depot_downloader()

    # Ensure executable
    if os.path.exists(exe_path):
        try:
            st = os.stat(exe_path)
            os.chmod(exe_path, st.st_mode | stat.S_IEXEC)
        except Exception:
            pass

    if not os.path.exists(exe_path):
        workshop_state["status"] = "failed"
        workshop_state["message"] = f"Executable not found: {exe_path}"
        return

    cmd = [exe_path, "-app", str(appid), "-pubfile", str(pubfile_id), "-dir", download_dir, "-max-downloads", "8"]

    try:
        workshop_state["status"] = "downloading"
        workshop_state["message"] = "Starting download..."
        workshop_state["progress"] = 0.0

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        _workshop_process = process

        percent_regex = re.compile(r"(\d{1,3}\.\d{2})%")
        last_output_line = "Unknown Error"
        output_log = []

        while True:
            line = await process.stdout.readline()
            if not line:
                break  # EOF — stdout closed, process finishing
            clean_line = line.decode("utf-8", errors="replace").strip()
            if clean_line:
                output_log.append(clean_line.lower())
                if "%" not in clean_line:
                    workshop_state["message"] = clean_line
                    last_output_line = clean_line
                match = percent_regex.search(clean_line)
                if match:
                    try:
                        p = float(match.group(1))
                        workshop_state["progress"] = p
                        workshop_state["message"] = f"Downloading: {p}%"
                    except Exception:
                        pass

        await process.wait()
        _workshop_process = None
        rc = process.returncode

        # Check for valid files
        has_valid_files = False
        if os.path.exists(download_dir):
            ignored = {".depotdownloader", "depotdownloader.config", ".ds_store", "thumbs.db"}
            total_size = 0
            file_count = 0
            for root, dirs, files in os.walk(download_dir):
                dirs[:] = [d for d in dirs if d.lower() not in ignored]
                for f in files:
                    if f.lower() not in ignored:
                        try:
                            total_size += os.path.getsize(os.path.join(root, f))
                            file_count += 1
                        except Exception:
                            pass
            has_valid_files = file_count > 0 and total_size > 0

        full_log = "\n".join(output_log)
        auth_error = any(x in full_log for x in ("access denied", "manifest not available", "no subscription", "purchase"))

        if rc == 0 and has_valid_files and not auth_error:
            workshop_state["status"] = "done"
            workshop_state["message"] = "Download Complete!"
            workshop_state["progress"] = 100.0
            open_game_folder(download_dir)
        else:
            workshop_state["status"] = "failed"
            if auth_error or (rc == 0 and not has_valid_files):
                workshop_state["message"] = "LOGIN_REQUIRED"
            else:
                workshop_state["message"] = f"Error: {last_output_line}"

    except Exception as e:
        workshop_state["status"] = "failed"
        workshop_state["message"] = f"Internal Error: {str(e)}"
        _workshop_process = None


async def start_workshop_download(appid: int, pubfile_id: int, target_library_path: str = "") -> dict:
    global workshop_state
    if workshop_state["status"] == "downloading":
        return {"success": False, "error": "Download already in progress."}

    steam_root = detect_steam_install_path()
    if not steam_root:
        return {"success": False, "error": "Steam installation not found."}

    # Use target library if specified, otherwise default to primary Steam root
    library_base = target_library_path if target_library_path and os.path.isdir(target_library_path) else steam_root
    download_dir = os.path.join(library_base, "steamapps", "workshop", "content", str(appid), str(pubfile_id))
    os.makedirs(download_dir, exist_ok=True)

    workshop_state = {
        "status": "downloading",
        "progress": 0,
        "message": "Initializing...",
        "download_path": download_dir,
    }

    asyncio.create_task(_run_depot_downloader_workshop(str(appid), str(pubfile_id), download_dir))
    return {"success": True, "message": "Download started"}


def get_workshop_download_status() -> dict:
    return workshop_state.copy()


async def cancel_workshop_download() -> dict:
    global workshop_state, _workshop_process
    if _workshop_process:
        try:
            _workshop_process.kill()
            workshop_state["status"] = "cancelled"
            workshop_state["message"] = "Cancelled by user."
        except Exception:
            pass
    return {"success": True}

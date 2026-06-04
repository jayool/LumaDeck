"""Game fix lookup, application, and removal logic (async port)."""

from __future__ import annotations

import asyncio
import json
import os
import posixpath
import zipfile
from datetime import datetime
from typing import Any, Dict

from downloads import fetch_app_name
from http_client import ensure_http_client
from steam_utils import get_game_install_path_response, _parse_vdf_simple, detect_steam_install_path
from utils import ensure_temp_download_dir

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

FIX_DOWNLOAD_STATE: Dict[int, Dict[str, Any]] = {}
UNFIX_STATE: Dict[int, Dict[str, Any]] = {}


def _set_fix_download_state(appid: int, update: dict) -> None:
    state = FIX_DOWNLOAD_STATE.get(appid) or {}
    state.update(update)
    FIX_DOWNLOAD_STATE[appid] = state


def _get_fix_download_state(appid: int) -> dict:
    return FIX_DOWNLOAD_STATE.get(appid, {}).copy()


def _set_unfix_state(appid: int, update: dict) -> None:
    state = UNFIX_STATE.get(appid) or {}
    state.update(update)
    UNFIX_STATE[appid] = state


def _get_unfix_state(appid: int) -> dict:
    return UNFIX_STATE.get(appid, {}).copy()


async def check_for_fixes(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    client = await ensure_http_client("CheckForFixes")
    result: Dict[str, Any] = {
        "success": True,
        "appid": appid,
        "gameName": "",
        "genericFix": {"status": 0, "available": False},
        "onlineFix": {"status": 0, "available": False},
    }

    try:
        result["gameName"] = await fetch_app_name(appid) or f"Unknown Game ({appid})"
    except Exception:
        result["gameName"] = f"Unknown Game ({appid})"

    try:
        generic_url = f"https://files.luatools.work/GameBypasses/{appid}.zip"
        resp = await client.head(generic_url, follow_redirects=True, timeout=10)
        result["genericFix"]["status"] = resp.status_code
        result["genericFix"]["available"] = resp.status_code == 200
        if resp.status_code == 200:
            result["genericFix"]["url"] = generic_url
    except Exception:
        pass

    try:
        online_url = f"https://files.luatools.work/OnlineFix1/{appid}.zip"
        resp = await client.head(online_url, follow_redirects=True, timeout=10)
        result["onlineFix"]["status"] = resp.status_code
        result["onlineFix"]["available"] = resp.status_code == 200
        if resp.status_code == 200:
            result["onlineFix"]["url"] = online_url
    except Exception:
        pass

    return result


async def _download_and_extract_fix(appid: int, download_url: str, install_path: str, fix_type: str, game_name: str = "") -> None:
    client = await ensure_http_client("fix download")
    dest_zip = ""
    try:
        dest_root = ensure_temp_download_dir()
        dest_zip = os.path.join(dest_root, f"fix_{appid}.zip")
        _set_fix_download_state(appid, {"status": "downloading", "bytesRead": 0, "totalBytes": 0, "error": None})

        async with client.stream("GET", download_url, follow_redirects=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", "0") or "0")
            _set_fix_download_state(appid, {"totalBytes": total})

            with open(dest_zip, "wb") as output:
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    if _get_fix_download_state(appid).get("status") == "cancelled":
                        raise RuntimeError("cancelled")
                    output.write(chunk)
                    read = int(_get_fix_download_state(appid).get("bytesRead", 0)) + len(chunk)
                    _set_fix_download_state(appid, {"bytesRead": read})

        _set_fix_download_state(appid, {"status": "extracting"})

        # Run extraction in executor (blocking I/O)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _extract_fix_sync, appid, dest_zip, install_path, fix_type, game_name, download_url)

    except Exception as exc:
        if str(exc) == "cancelled":
            try:
                if dest_zip:
                    os.remove(dest_zip)
            except Exception:
                pass
            _set_fix_download_state(appid, {"status": "cancelled", "success": False, "error": "Cancelled by user"})
            return
        logger.warning(f"LumaDeck: Failed to apply fix: {exc}")
        _set_fix_download_state(appid, {"status": "failed", "error": str(exc)})


def _is_path_safe(base_dir: str, member_name: str) -> bool:
    """Check that a zip member path stays within base_dir (prevents Zip Slip)."""
    # Normalise the member name and reject absolute paths
    clean = posixpath.normpath(member_name)
    if clean.startswith("/") or clean.startswith("\\"):
        return False
    # Resolve the final destination and verify it's inside base_dir
    resolved = os.path.realpath(os.path.join(base_dir, clean))
    base_resolved = os.path.realpath(base_dir)
    return resolved.startswith(base_resolved + os.sep) or resolved == base_resolved


def _extract_fix_sync(appid: int, dest_zip: str, install_path: str, fix_type: str, game_name: str, download_url: str) -> None:
    """Synchronous extraction of fix zip (runs in executor)."""
    extracted_files = []
    with zipfile.ZipFile(dest_zip, "r") as archive:
        all_names = archive.namelist()
        appid_folder = f"{appid}/"

        top_level = set()
        for name in all_names:
            parts = name.split("/")
            if parts[0]:
                top_level.add(parts[0])

        if len(top_level) == 1 and appid_folder.rstrip("/") in top_level:
            for member in archive.namelist():
                if member.startswith(appid_folder) and member != appid_folder:
                    target_path = member[len(appid_folder):]
                    if not target_path:
                        continue
                    if not _is_path_safe(install_path, target_path):
                        logger.warning(f"Zip Slip blocked: {member}")
                        continue
                    source = archive.open(member)
                    target = os.path.join(install_path, target_path)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    if not member.endswith("/"):
                        with open(target, "wb") as output:
                            output.write(source.read())
                        extracted_files.append(target_path.replace("\\", "/"))
                    source.close()
        else:
            for member in archive.namelist():
                if member.endswith("/"):
                    continue
                if not _is_path_safe(install_path, member):
                    logger.warning(f"Zip Slip blocked: {member}")
                    continue
                archive.extract(member, install_path)
                extracted_files.append(member.replace("\\", "/"))

    # Handle unsteam.ini placeholder replacement
    if fix_type.lower() == "online fix (unsteam)":
        for rel_path in extracted_files:
            if rel_path.lower().endswith("unsteam.ini"):
                ini_path = os.path.join(install_path, rel_path.replace("/", os.sep))
                if os.path.exists(ini_path):
                    try:
                        with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
                            contents = f.read()
                        updated = contents.replace("<appid>", str(appid))
                        if updated != contents:
                            with open(ini_path, "w", encoding="utf-8") as f:
                                f.write(updated)
                    except Exception:
                        pass
                break

    # Write fix log
    log_file_path = os.path.join(install_path, f"luatools-fix-log-{appid}.log")
    try:
        existing = ""
        if os.path.exists(log_file_path):
            with open(log_file_path, "r", encoding="utf-8") as f:
                existing = f.read()
        with open(log_file_path, "w", encoding="utf-8") as f:
            if existing:
                f.write(existing)
                if not existing.endswith("\n"):
                    f.write("\n")
                f.write("\n---\n\n")
            f.write("[FIX]\n")
            f.write(f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write(f'Game: {game_name or f"Unknown Game ({appid})"}\n')
            f.write(f"Fix Type: {fix_type}\n")
            f.write(f"Download URL: {download_url}\n")
            f.write("Files:\n")
            for fp in extracted_files:
                f.write(f"{fp}\n")
            f.write("[/FIX]\n")
    except Exception:
        pass

    _set_fix_download_state(appid, {"status": "done", "success": True})

    try:
        os.remove(dest_zip)
    except Exception:
        pass


async def apply_game_fix(appid: int, download_url: str, install_path: str, fix_type: str = "", game_name: str = "") -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    if not download_url or not install_path:
        return {"success": False, "error": "Missing download URL or install path"}
    if not os.path.exists(install_path):
        return {"success": False, "error": "Install path does not exist"}

    _set_fix_download_state(appid, {"status": "queued", "bytesRead": 0, "totalBytes": 0, "error": None})
    asyncio.create_task(_download_and_extract_fix(appid, download_url, install_path, fix_type, game_name))
    return {"success": True}


def get_apply_fix_status(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    return {"success": True, "state": _get_fix_download_state(appid)}


def cancel_apply_fix(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    state = _get_fix_download_state(appid)
    if not state or state.get("status") in {"done", "failed"}:
        return {"success": True, "message": "Nothing to cancel"}

    _set_fix_download_state(appid, {"status": "cancelled", "success": False, "error": "Cancelled by user"})
    return {"success": True}


def _unfix_game_worker(appid: int, install_path: str, fix_date: str = "") -> None:
    """Synchronous un-fix worker (runs in executor)."""
    try:
        log_file_path = os.path.join(install_path, f"luatools-fix-log-{appid}.log")
        if not os.path.exists(log_file_path):
            _set_unfix_state(appid, {"status": "failed", "error": "No fix log found."})
            return

        _set_unfix_state(appid, {"status": "removing", "progress": "Reading log file..."})
        files_to_delete = set()
        remaining_fixes = []

        with open(log_file_path, "r", encoding="utf-8") as handle:
            log_content = handle.read()

        if "[FIX]" in log_content:
            fix_blocks = log_content.split("[FIX]")
            for block in fix_blocks:
                if not block.strip():
                    continue
                lines = block.split("\n")
                in_files_section = False
                block_date = None
                block_lines = []
                for line in lines:
                    line_stripped = line.strip()
                    if line_stripped == "[/FIX]" or line_stripped == "---":
                        break
                    if line_stripped.startswith("Date:"):
                        block_date = line_stripped.replace("Date:", "").strip()
                    block_lines.append(line)
                    if line_stripped == "Files:":
                        in_files_section = True
                    elif in_files_section and line_stripped:
                        if not fix_date or (block_date and block_date == fix_date):
                            files_to_delete.add(line_stripped)
                if fix_date and block_date and block_date != fix_date:
                    remaining_fixes.append("[FIX]\n" + "\n".join(block_lines) + "\n[/FIX]")
        else:
            lines = log_content.split("\n")
            in_files_section = False
            for line in lines:
                line = line.strip()
                if line == "Files:":
                    in_files_section = True
                elif in_files_section and line:
                    files_to_delete.add(line)

        _set_unfix_state(appid, {"status": "removing", "progress": f"Removing {len(files_to_delete)} files..."})
        deleted_count = 0
        for file_path in files_to_delete:
            try:
                full_path = os.path.join(install_path, file_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
                    deleted_count += 1
            except Exception:
                pass

        if remaining_fixes:
            try:
                with open(log_file_path, "w", encoding="utf-8") as handle:
                    handle.write("\n\n---\n\n".join(remaining_fixes))
            except Exception:
                pass
        else:
            try:
                os.remove(log_file_path)
            except Exception:
                pass

        _set_unfix_state(appid, {"status": "done", "success": True, "filesRemoved": deleted_count})
    except Exception as exc:
        _set_unfix_state(appid, {"status": "failed", "error": str(exc)})


async def unfix_game(appid: int, install_path: str = "", fix_date: str = "") -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    resolved_path = install_path
    if not resolved_path:
        result = get_game_install_path_response(appid)
        if not result.get("success") or not result.get("installPath"):
            return {"success": False, "error": "Could not find game install path"}
        resolved_path = result["installPath"]

    if not os.path.exists(resolved_path):
        return {"success": False, "error": "Install path does not exist"}

    _set_unfix_state(appid, {"status": "queued", "progress": "", "error": None})
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _unfix_game_worker, appid, resolved_path, fix_date or "")
    return {"success": True}


def get_unfix_status(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    return {"success": True, "state": _get_unfix_state(appid)}


def get_installed_fixes() -> dict:
    """Scan all Steam library folders for games with fix logs."""
    try:
        steam_path = detect_steam_install_path()
        if not steam_path:
            return {"success": False, "error": "Steam not found"}

        library_vdf_path = os.path.join(steam_path, "config", "libraryfolders.vdf")
        if not os.path.exists(library_vdf_path):
            return {"success": False, "error": "libraryfolders.vdf not found"}

        with open(library_vdf_path, "r", encoding="utf-8") as handle:
            library_data = _parse_vdf_simple(handle.read())

        library_folders = library_data.get("libraryfolders", {})
        all_library_paths = []
        for folder_data in library_folders.values():
            if isinstance(folder_data, dict):
                folder_path = folder_data.get("path", "")
                if folder_path:
                    all_library_paths.append(folder_path.replace("\\\\", "\\"))

        installed_fixes = []
        for lib_path in all_library_paths:
            steamapps = os.path.join(lib_path, "steamapps")
            if not os.path.isdir(steamapps):
                continue
            try:
                for filename in os.listdir(steamapps):
                    if not filename.startswith("appmanifest_") or not filename.endswith(".acf"):
                        continue
                    try:
                        appid = int(filename.replace("appmanifest_", "").replace(".acf", ""))
                        acf_path = os.path.join(steamapps, filename)
                        with open(acf_path, "r", encoding="utf-8") as f:
                            manifest_data = _parse_vdf_simple(f.read())
                        app_state = manifest_data.get("AppState", {})
                        install_dir = app_state.get("installdir", "")
                        game_name = app_state.get("name", f"Unknown ({appid})")
                        if not install_dir:
                            continue
                        full_path = os.path.join(lib_path, "steamapps", "common", install_dir)
                        if not os.path.exists(full_path):
                            continue
                        log_path = os.path.join(full_path, f"luatools-fix-log-{appid}.log")
                        if not os.path.exists(log_path):
                            continue

                        with open(log_path, "r", encoding="utf-8") as lf:
                            log_content = lf.read()

                        if "[FIX]" in log_content:
                            for block in log_content.split("[FIX]"):
                                if not block.strip():
                                    continue
                                fix_data = {"appid": appid, "gameName": game_name, "installPath": full_path, "date": "", "fixType": "", "downloadUrl": "", "filesCount": 0, "files": []}
                                in_files = False
                                files = []
                                for line in block.split("\n"):
                                    line = line.strip()
                                    if line == "[/FIX]":
                                        break
                                    if line.startswith("Date:"):
                                        fix_data["date"] = line.replace("Date:", "").strip()
                                    elif line.startswith("Fix Type:"):
                                        fix_data["fixType"] = line.replace("Fix Type:", "").strip()
                                    elif line.startswith("Download URL:"):
                                        fix_data["downloadUrl"] = line.replace("Download URL:", "").strip()
                                    elif line == "Files:":
                                        in_files = True
                                    elif in_files and line:
                                        files.append(line)
                                fix_data["filesCount"] = len(files)
                                fix_data["files"] = files
                                if fix_data["date"]:
                                    installed_fixes.append(fix_data)
                    except Exception:
                        continue
            except Exception:
                continue

        return {"success": True, "fixes": installed_fixes}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def apply_linux_native_fix(install_path: str) -> dict:
    """Fix permissions for Linux native games: chown to deck + chmod +rwx."""
    import stat
    import subprocess
    if os.name != "posix":
        return {"success": False, "error": "This fix is for Linux only."}
    if not install_path or not os.path.exists(install_path):
        return {"success": False, "error": "Game path not found."}
    try:
        # Fix ownership first (Decky runs as root, Steam runs as deck)
        try:
            subprocess.run(
                ["chown", "-R", "deck:deck", install_path],
                timeout=120, capture_output=True,
            )
        except Exception as chown_exc:
            logger.warning(f"LumaDeck: chown failed for {install_path}: {chown_exc}")

        count = 0
        for root, dirs, files in os.walk(install_path):
            # Directories: rwxr-xr-x (755) for traversal
            for d in dirs:
                dp = os.path.join(root, d)
                try:
                    os.chmod(dp, 0o755)
                except Exception:
                    pass
            # Files: rwxr-xr-x (755) — read+execute for all
            for name in files:
                fp = os.path.join(root, name)
                try:
                    os.chmod(fp, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                    count += 1
                except Exception:
                    pass
        return {"success": True, "count": count}
    except Exception as e:
        return {"success": False, "error": str(e)}

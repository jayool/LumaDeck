"""Goldberg Steam Emulator management for LumaDeck.

Applies/removes Goldberg emulator DLLs to game directories.
Uses Goldberg files bundled with ACCELA AppImage.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from paths import find_accela_root, data_path

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

_GOLDBERG_CACHE_DIR = None


def _get_goldberg_dir() -> str | None:
    """Find or extract Goldberg files. Returns path to directory containing DLLs."""
    global _GOLDBERG_CACHE_DIR

    # 1. Check cached location
    cache_dir = data_path("goldberg")
    if os.path.isdir(cache_dir):
        dll = os.path.join(cache_dir, "steam_api64.dll")
        if os.path.exists(dll):
            _GOLDBERG_CACHE_DIR = cache_dir
            return cache_dir

    # 2. Check if ACCELA AppImage was already extracted (from brainstorming session)
    squashfs_goldberg = "/tmp/squashfs-root/bin/src/deps/Goldberg"
    if os.path.isdir(squashfs_goldberg) and os.path.exists(os.path.join(squashfs_goldberg, "steam_api64.dll")):
        _copy_goldberg_to_cache(squashfs_goldberg, cache_dir)
        return cache_dir

    # 3. Extract from ACCELA AppImage
    accela_root = find_accela_root()
    if not accela_root:
        return None

    appimage = os.path.join(accela_root, "ACCELA.AppImage")
    if not os.path.exists(appimage):
        return None

    try:
        # Extract only the Goldberg directory
        extract_dir = "/tmp/lumadeck_appimage_extract"
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)

        subprocess.run(
            [appimage, "--appimage-extract", "bin/src/deps/Goldberg/*"],
            cwd="/tmp",
            capture_output=True,
            timeout=30,
        )

        extracted = os.path.join(extract_dir, "bin", "src", "deps", "Goldberg")
        if not os.path.isdir(extracted):
            # Fallback: full extract
            subprocess.run(
                [appimage, "--appimage-extract"],
                cwd="/tmp",
                capture_output=True,
                timeout=60,
            )
            extracted = "/tmp/squashfs-root/bin/src/deps/Goldberg"

        if os.path.isdir(extracted) and os.path.exists(os.path.join(extracted, "steam_api64.dll")):
            _copy_goldberg_to_cache(extracted, cache_dir)
            return cache_dir
    except Exception as e:
        logger.warning(f"LumaDeck: Failed to extract Goldberg from AppImage: {e}")

    return None


def _copy_goldberg_to_cache(src_dir: str, cache_dir: str) -> None:
    """Copy Goldberg files to persistent cache."""
    global _GOLDBERG_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    for item in os.listdir(src_dir):
        src_path = os.path.join(src_dir, item)
        dst_path = os.path.join(cache_dir, item)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
        else:
            shutil.copy2(src_path, dst_path)
    _GOLDBERG_CACHE_DIR = cache_dir
    logger.info(f"LumaDeck: Goldberg files cached at {cache_dir}")


def check_goldberg_status(install_path: str) -> dict:
    """Check if Goldberg is applied to a game directory."""
    try:
        if not install_path or not os.path.exists(install_path):
            return {"success": True, "applied": False, "reason": "Path not found"}

        for root, _, files in os.walk(install_path):
            for fname in files:
                if fname.lower() in ("steam_api.dll.valve", "steam_api64.dll.valve"):
                    return {"success": True, "applied": True}

        return {"success": True, "applied": False}
    except Exception as e:
        return {"success": False, "error": str(e)}


def apply_goldberg(install_path: str, appid: int) -> dict:
    """Apply Goldberg Steam Emulator to a game directory."""
    try:
        if not install_path or not os.path.exists(install_path):
            return {"success": False, "error": "Game directory not found"}

        goldberg_dir = _get_goldberg_dir()
        if not goldberg_dir:
            return {"success": False, "error": "Goldberg files not found. Is ACCELA installed?"}

        # Find all directories containing steam_api DLLs
        found_dirs = set()
        for root, _, files in os.walk(install_path):
            for fname in files:
                if fname.lower() in ("steam_api.dll", "steam_api64.dll"):
                    found_dirs.add(root)

        if not found_dirs:
            return {"success": False, "error": "No steam_api DLLs found in game directory"}

        modified_count = 0
        for dest_dir in found_dirs:
            # Track which DLLs originally existed
            original_dlls = set()
            for base in ("steam_api.dll", "steam_api64.dll"):
                if os.path.exists(os.path.join(dest_dir, base)):
                    original_dlls.add(base)

            # Rename originals to .valve backup
            for base in ("steam_api.dll", "steam_api64.dll"):
                src_path = os.path.join(dest_dir, base)
                if os.path.exists(src_path):
                    target_path = src_path + ".valve"
                    if not os.path.exists(target_path):
                        os.replace(src_path, target_path)

            # Copy matching Goldberg DLLs
            for base in original_dlls:
                src_dll = os.path.join(goldberg_dir, base)
                dst_dll = os.path.join(dest_dir, base)
                if os.path.exists(src_dll):
                    shutil.copy2(src_dll, dst_dll)

            # Copy other Goldberg content (steam_settings/, etc.)
            for item in os.listdir(goldberg_dir):
                if item.lower() in ("steam_api.dll", "steam_api64.dll", "steam_appid.txt"):
                    continue
                src_item = os.path.join(goldberg_dir, item)
                dst_item = os.path.join(dest_dir, item)
                if os.path.isdir(src_item):
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)

            # Write steam_appid.txt with actual game AppID
            appid_file = os.path.join(dest_dir, "steam_appid.txt")
            with open(appid_file, "w", encoding="utf-8") as f:
                f.write(str(appid))

            modified_count += 1

        logger.info(f"LumaDeck: Applied Goldberg to {modified_count} dir(s) in {install_path}")
        return {"success": True, "message": f"Goldberg applied to {modified_count} location(s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def remove_goldberg(install_path: str, appid: int) -> dict:
    """Remove Goldberg and restore original steam_api DLLs."""
    try:
        if not install_path or not os.path.exists(install_path):
            return {"success": False, "error": "Game directory not found"}

        # Find directories with .valve backups
        found_dirs = set()
        for root, _, files in os.walk(install_path):
            for fname in files:
                if fname.lower() in ("steam_api.dll.valve", "steam_api64.dll.valve"):
                    found_dirs.add(root)

        if not found_dirs:
            return {"success": False, "error": "No Goldberg installation found (no .valve backups)"}

        # Get list of Goldberg items to clean up
        goldberg_dir = _get_goldberg_dir()
        goldberg_items = []
        if goldberg_dir:
            goldberg_items = os.listdir(goldberg_dir)

        modified_count = 0
        for dest_dir in found_dirs:
            # Restore .valve backups
            had_backup = {}
            for base in ("steam_api.dll", "steam_api64.dll"):
                valve_path = os.path.join(dest_dir, base + ".valve")
                orig_path = os.path.join(dest_dir, base)
                had_backup[base] = os.path.exists(valve_path)
                if had_backup[base]:
                    os.replace(valve_path, orig_path)

            # Remove extra Goldberg DLLs that had no backup
            for base in ("steam_api.dll", "steam_api64.dll"):
                if had_backup.get(base):
                    continue
                extra_path = os.path.join(dest_dir, base)
                if os.path.exists(extra_path):
                    os.remove(extra_path)

            # Remove copied Goldberg files
            for name in goldberg_items:
                if name.lower() in ("steam_api.dll", "steam_api64.dll", "steam_appid.txt"):
                    continue
                dest_path = os.path.join(dest_dir, name)
                if os.path.isdir(dest_path):
                    shutil.rmtree(dest_path)
                elif os.path.exists(dest_path):
                    os.remove(dest_path)

            # Remove steam_appid.txt if it matches
            appid_file = os.path.join(dest_dir, "steam_appid.txt")
            if os.path.exists(appid_file):
                try:
                    with open(appid_file, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if not content or content == str(appid):
                        os.remove(appid_file)
                except Exception:
                    pass

            modified_count += 1

        logger.info(f"LumaDeck: Removed Goldberg from {modified_count} dir(s) in {install_path}")
        return {"success": True, "message": f"Goldberg removed from {modified_count} location(s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}

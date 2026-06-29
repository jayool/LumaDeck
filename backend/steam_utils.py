"""Steam-related utilities used across LumaDeck backend modules."""

from __future__ import annotations

import os
import re
import subprocess
from typing import Dict, Optional

from paths import find_steam_root

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

_STEAM_INSTALL_PATH: Optional[str] = None

# Well-known Linux Steam paths (same priority as paths.py)
_LINUX_STEAM_PATHS = [
    "/home/deck/.local/share/Steam",
    "/home/deck/.steam/steam",
    os.path.expanduser("~/.steam/steam"),
    os.path.expanduser("~/.local/share/Steam"),
    "/opt/steam/steam",
    "/usr/local/steam",
]


def detect_steam_install_path() -> str:
    global _STEAM_INSTALL_PATH
    if _STEAM_INSTALL_PATH:
        return _STEAM_INSTALL_PATH
    # Use find_steam_root which already handles Deck paths
    path = find_steam_root()
    if not path:
        for candidate in _LINUX_STEAM_PATHS:
            if os.path.isdir(candidate):
                path = candidate
                break
    _STEAM_INSTALL_PATH = path
    logger.info(f"LumaDeck: Steam install path set to {_STEAM_INSTALL_PATH}")
    return _STEAM_INSTALL_PATH or ""


def _parse_vdf_simple(content: str) -> Dict[str, any]:
    """Simple VDF parser for libraryfolders.vdf and appmanifest files."""
    result: Dict[str, any] = {}
    stack = [result]
    current_key = None

    lines = content.split("\n")
    tokens = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        parts = re.findall(r'"[^"]*"|\{|\}', line)
        tokens.extend(parts)

    i = 0
    while i < len(tokens):
        token = tokens[i].strip('"')

        if tokens[i] == "{":
            if current_key:
                new_dict = {}
                stack[-1][current_key] = new_dict
                stack.append(new_dict)
                current_key = None
        elif tokens[i] == "}":
            if len(stack) > 1:
                stack.pop()
        elif current_key is None:
            current_key = token
        else:
            stack[-1][current_key] = token
            current_key = None
        i += 1

    return result


def _appid_in_lumalinux_keys(appid: int, keys_path: str) -> bool:
    """Look for `appid` in lumalinux's keys.txt. It can appear in two shapes:
      - dummy line for the app itself: '<appid>;<hex>'
      - parent_app_id in a depot line:  '<depot>;<appid>;<gid>;<size>;<key>'
    Blank lines and lines starting with '#' are ignored. Best-effort: any
    read error → False, never raises."""
    if not os.path.isfile(keys_path):
        return False
    appid_str = str(appid)
    try:
        with open(keys_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                fields = line.split(";")
                if fields[0] == appid_str:
                    return True
                if len(fields) >= 2 and fields[1] == appid_str:
                    return True
    except Exception:
        pass
    return False


def has_lua_for_app(appid: int) -> bool:
    """Return True if the appid is registered with EITHER backend the plugin
    understands. Despite the historical name (kept for compat with the
    upstream API and the frontend `hasLua` field), the semantics is now
    "this game is managed by the plugin", not strictly "has a .lua".

    Sources, ORed:
      - Legacy SteaMidra-style: <steam>/config/stplug-in/<appid>.lua  (or .disabled)
      - lumalinux flow:         <appid> referenced in ~/.config/lumalinux/keys.txt

    Either presence is enough — the two flows are independent and the plugin
    supports them side by side. False only if neither has the app."""
    try:
        # Legacy stplug-in check (DDL / SteaMidra path)
        base_path = detect_steam_install_path()
        if base_path:
            stplug_path = os.path.join(base_path, "config", "stplug-in")
            lua_file = os.path.join(stplug_path, f"{appid}.lua")
            disabled_file = os.path.join(stplug_path, f"{appid}.lua.disabled")
            if os.path.exists(lua_file) or os.path.exists(disabled_file):
                return True
        # lumalinux keys.txt check (native Steam download path)
        from paths import get_lumalinux_keys_path
        if _appid_in_lumalinux_keys(int(appid), get_lumalinux_keys_path()):
            return True
    except Exception as exc:
        logger.error(f"LumaDeck: Error checking managed status for app {appid}: {exc}")
    return False


def get_game_install_path_response(appid: int) -> Dict[str, any]:
    """Find the game installation path. Returns dict with success/error."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    steam_path = detect_steam_install_path()
    if not steam_path:
        return {"success": False, "error": "Could not find Steam installation path"}

    library_vdf_path = os.path.join(steam_path, "config", "libraryfolders.vdf")
    if not os.path.exists(library_vdf_path):
        return {"success": False, "error": "Could not find libraryfolders.vdf"}

    try:
        with open(library_vdf_path, "r", encoding="utf-8") as handle:
            vdf_content = handle.read()
        library_data = _parse_vdf_simple(vdf_content)
    except Exception as exc:
        return {"success": False, "error": "Failed to parse libraryfolders.vdf"}

    library_folders = library_data.get("libraryfolders", {})
    library_path = None
    appid_str = str(appid)
    all_library_paths = []

    for folder_data in library_folders.values():
        if isinstance(folder_data, dict):
            folder_path = folder_data.get("path", "")
            if folder_path:
                folder_path = folder_path.replace("\\\\", "\\")
                all_library_paths.append(folder_path)
            apps = folder_data.get("apps", {})
            if isinstance(apps, dict) and appid_str in apps:
                library_path = folder_path
                break

    appmanifest_path = None
    if not library_path:
        for lib_path in all_library_paths:
            candidate_path = os.path.join(lib_path, "steamapps", f"appmanifest_{appid}.acf")
            if os.path.exists(candidate_path):
                library_path = lib_path
                appmanifest_path = candidate_path
                break
    else:
        appmanifest_path = os.path.join(library_path, "steamapps", f"appmanifest_{appid}.acf")

    if not library_path or not appmanifest_path or not os.path.exists(appmanifest_path):
        return {"success": False, "error": "Game not installed"}

    try:
        with open(appmanifest_path, "r", encoding="utf-8") as handle:
            manifest_content = handle.read()
        manifest_data = _parse_vdf_simple(manifest_content)
    except Exception:
        return {"success": False, "error": "Failed to parse appmanifest"}

    app_state = manifest_data.get("AppState", {})
    install_dir = app_state.get("installdir", "")
    if not install_dir:
        return {"success": False, "error": "Install directory not found"}

    full_install_path = os.path.join(library_path, "steamapps", "common", install_dir)
    if not os.path.exists(full_install_path):
        return {"success": False, "error": "Game directory not found"}

    return {
        "success": True,
        "installPath": full_install_path,
        "installDir": install_dir,
        "libraryPath": library_path,
        "path": full_install_path,
        "sizeOnDisk": int(app_state.get("SizeOnDisk", 0)),
    }


def get_installed_games() -> list:
    """Scan all Steam library folders for installed games (appmanifest_*.acf files)."""
    steam_path = detect_steam_install_path()
    if not steam_path:
        return []

    library_vdf_path = os.path.join(steam_path, "config", "libraryfolders.vdf")
    if not os.path.exists(library_vdf_path):
        return []

    try:
        with open(library_vdf_path, "r", encoding="utf-8") as handle:
            vdf_content = handle.read()
        library_data = _parse_vdf_simple(vdf_content)
    except Exception:
        return []

    library_folders = library_data.get("libraryfolders", {})
    all_library_paths = []
    for folder_data in library_folders.values():
        if isinstance(folder_data, dict):
            folder_path = folder_data.get("path", "")
            if folder_path:
                all_library_paths.append(folder_path.replace("\\\\", "\\"))

    games = []
    seen_appids = set()
    for lib_path in all_library_paths:
        steamapps = os.path.join(lib_path, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        try:
            for filename in os.listdir(steamapps):
                if not filename.startswith("appmanifest_") or not filename.endswith(".acf"):
                    continue
                try:
                    appid_str = filename.replace("appmanifest_", "").replace(".acf", "")
                    appid = int(appid_str)
                    if appid in seen_appids:
                        continue
                    seen_appids.add(appid)

                    acf_path = os.path.join(steamapps, filename)
                    with open(acf_path, "r", encoding="utf-8") as f:
                        acf_data = _parse_vdf_simple(f.read())
                    app_state = acf_data.get("AppState", {})
                    name = app_state.get("name", f"Unknown ({appid})")
                    install_dir = app_state.get("installdir", "")

                    games.append({
                        "appid": appid,
                        "name": name,
                        "installDir": install_dir,
                        "libraryPath": lib_path,
                        "updateResult": str(app_state.get("UpdateResult", "0")),
                    })
                except (ValueError, Exception):
                    continue
        except Exception:
            continue

    games.sort(key=lambda g: g["name"].lower())
    return games


def check_stuck_updates() -> dict:
    """Installed lua games whose last native Steam update failed with a missing
    decryption key (UpdateResult=8): a new or rotated depot whose key isn't in
    keys.txt, which needs a fresh Hubcap manifest re-deploy (#21).

    Non-destructive — Steam stages updates and only commits on success, so the
    game stays on its working installed version. Restricted to games that have a
    .lua (LumaDeck/unpinned installs); an owned game would never hit this.

    NOTE: UpdateResult persists until a successful depot op, so a fully-installed
    game can carry a STALE "8" (e.g. from the initial add) with no real pending
    update — that's a known false-positive source (CrossCode on-device). Trying
    to gate on StateFlags/BytesToDownload was reverted because we don't yet know
    what a genuine stuck looks like in the Hubcap/lumalinux flow; revisit with a
    real captured case.

    Returns {"success": True, "stuck": [{"appid", "name"}, ...]}.
    """
    stuck = []
    for game in get_installed_games():
        if str(game.get("updateResult", "0")) == "8" and has_lua_for_app(game["appid"]):
            stuck.append({"appid": game["appid"], "name": game["name"]})
    return {"success": True, "stuck": stuck}


def get_steam_libraries() -> list:
    """Return all Steam library folders with free space info.

    Each entry: {"path": str, "freeBytes": int, "totalBytes": int, "gameCount": int}
    """
    steam_path = detect_steam_install_path()
    if not steam_path:
        return []

    library_vdf_path = os.path.join(steam_path, "config", "libraryfolders.vdf")
    if not os.path.exists(library_vdf_path):
        return []

    try:
        with open(library_vdf_path, "r", encoding="utf-8") as handle:
            vdf_content = handle.read()
        library_data = _parse_vdf_simple(vdf_content)
    except Exception:
        return []

    library_folders = library_data.get("libraryfolders", {})
    libraries = []

    for folder_data in library_folders.values():
        if not isinstance(folder_data, dict):
            continue
        folder_path = folder_data.get("path", "")
        if not folder_path:
            continue
        folder_path = folder_path.replace("\\\\", "\\")

        apps = folder_data.get("apps", {})
        game_count = len(apps) if isinstance(apps, dict) else 0

        free_bytes = 0
        total_bytes = 0
        try:
            st = os.statvfs(folder_path)
            free_bytes = st.f_bavail * st.f_frsize
            total_bytes = st.f_blocks * st.f_frsize
        except Exception:
            pass

        libraries.append({
            "path": folder_path,
            "freeBytes": free_bytes,
            "totalBytes": total_bytes,
            "gameCount": game_count,
        })

    return libraries


def open_game_folder(path: str) -> bool:
    try:
        if not path or not os.path.exists(path):
            return False
        subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def get_app_launch_options(appid: int) -> str | None:
    """Read the current LaunchOptions string for `appid` from localconfig.vdf.

    Returns the string (possibly empty) if the app's block is found, or None if
    no localconfig.vdf / app block exists. Best-effort: while Steam is running
    this reflects the last value Steam persisted to disk, which is enough to
    preserve any user-set options when we merge in our WINEDLLOVERRIDES.
    Brace-balanced scan so we never read a neighbouring app's LaunchOptions.
    """
    steam_path = detect_steam_install_path()
    if not steam_path:
        return None
    userdata_dir = os.path.join(steam_path, "userdata")
    if not os.path.isdir(userdata_dir):
        return None
    appid_str = str(appid)
    for user_id in os.listdir(userdata_dir):
        config_path = os.path.join(userdata_dir, user_id, "config", "localconfig.vdf")
        if not os.path.exists(config_path):
            continue
        try:
            with open(config_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except Exception:
            continue
        m = re.search(r'"' + re.escape(appid_str) + r'"\s*\{', content)
        if not m:
            continue
        # Walk to the matching close brace so we stay inside this app's block.
        i = m.end()
        depth = 1
        j = i
        while j < len(content) and depth > 0:
            c = content[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        block = content[i:j]
        lm = re.search(r'"LaunchOptions"\s*"([^"]*)"', block)
        return lm.group(1) if lm else ""
    return None


def set_compat_tool_for_app(appid: int, tool_name: str = "proton_experimental") -> bool:
    """Write a CompatToolMapping entry in localconfig.vdf so Steam launches
    the game via the specified Proton/compat tool (default: proton_experimental).

    Iterates over all user IDs found under Steam's userdata directory.
    Safe to call while Steam is not running; Steam reloads the file on start.
    """
    steam_path = detect_steam_install_path()
    if not steam_path:
        logger.warning("LumaDeck: set_compat_tool — Steam path not found")
        return False

    userdata_dir = os.path.join(steam_path, "userdata")
    if not os.path.isdir(userdata_dir):
        logger.warning(f"LumaDeck: set_compat_tool — userdata dir not found: {userdata_dir}")
        return False

    appid_str = str(appid)
    success = False

    for user_id in os.listdir(userdata_dir):
        config_path = os.path.join(userdata_dir, user_id, "config", "localconfig.vdf")
        if not os.path.exists(config_path):
            continue

        try:
            with open(config_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()

            compat_re = re.compile(r'^([ \t]*)"CompatToolMapping"[ \t]*\{', re.MULTILINE | re.IGNORECASE)
            compat_match = compat_re.search(content)

            if not compat_match:
                # CompatToolMapping section missing — create it inside the "Steam" block
                steam_re = re.compile(r'^([ \t]*)"Steam"[ \t]*\n[ \t]*\{', re.MULTILINE)
                steam_match = steam_re.search(content)
                if not steam_match:
                    logger.warning(f"LumaDeck: Steam section not found in {config_path} — skipping")
                    continue

                steam_indent = steam_match.group(1)
                c_indent = steam_indent + "\t"
                e_indent = c_indent + "\t"
                f_indent = e_indent + "\t"

                new_section = (
                    f'{c_indent}"CompatToolMapping"\n'
                    f'{c_indent}{{\n'
                    f'{e_indent}"{appid_str}"\n'
                    f'{e_indent}{{\n'
                    f'{f_indent}"name"\t\t"{tool_name}"\n'
                    f'{f_indent}"config"\t\t""\n'
                    f'{f_indent}"Priority"\t\t"250"\n'
                    f'{e_indent}}}\n'
                    f'{c_indent}}}\n'
                )

                insert_pos = steam_match.end()
                content = content[:insert_pos] + "\n" + new_section + content[insert_pos:]

            else:
                base_indent = compat_match.group(1)
                entry_indent = base_indent + "\t"
                field_indent = entry_indent + "\t"

                new_block = (
                    f'{entry_indent}"{appid_str}"\n'
                    f'{entry_indent}{{\n'
                    f'{field_indent}"name"\t\t"{tool_name}"\n'
                    f'{field_indent}"config"\t\t""\n'
                    f'{field_indent}"Priority"\t\t"250"\n'
                    f'{entry_indent}}}\n'
                )

                existing_re = re.compile(
                    rf'([ \t]*)"{re.escape(appid_str)}"\s*\{{[^{{}}]*\}}',
                    re.DOTALL,
                )
                if existing_re.search(content):
                    content = existing_re.sub(new_block.rstrip("\n"), content)
                else:
                    insert_pos = compat_match.end()
                    content = content[:insert_pos] + "\n" + new_block + content[insert_pos:]

            with open(config_path, "w", encoding="utf-8") as fh:
                fh.write(content)

            logger.info(f"LumaDeck: Set compat tool '{tool_name}' for app {appid} (user {user_id})")
            success = True

        except Exception as exc:
            logger.warning(f"LumaDeck: set_compat_tool failed for user {user_id}: {exc}")

    return success

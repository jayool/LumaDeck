"""Handling of game manifest download flows and related utilities (async port).

All public functions return native Python types (dict/list/str/bool).
Decky Loader auto-serializes return values to JSON.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Dict

from api_manifest import load_api_manifest, load_ryu_cookie
from config import (
    APPID_LOG_FILE,
    LOADED_APPS_FILE,
    USER_AGENT,
    APPLIST_URL,
    APPLIST_URL_FALLBACK,
    APPLIST_FILE_NAME,
    APPLIST_DOWNLOAD_TIMEOUT,
    GAMES_DB_FILE_NAME,
    GAMES_DB_URL,
)
from http_client import ensure_http_client
from paths import backend_path, data_path, get_plugin_dir
from steam_utils import detect_steam_install_path, has_lua_for_app
from utils import ensure_temp_download_dir

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("decktools")

DOWNLOAD_STATE: Dict[int, Dict[str, Any]] = {}
DOWNLOAD_TASKS: Dict[int, asyncio.Task] = {}

# Cache for app names
APP_NAME_CACHE: Dict[int, str] = {}

# Rate limiting for Steam API calls
_LAST_API_CALL_TIME = 0.0
_API_CALL_MIN_INTERVAL = 0.3  # 300ms between calls

# In-memory applist for fallback app name lookup
APPLIST_DATA: Dict[int, str] = {}
APPLIST_LOADED = False

# In-memory games database
GAMES_DB_DATA: Dict[str, Any] = {}
GAMES_DB_LOADED = False


def _set_download_state(appid: int, update: dict) -> None:
    state = DOWNLOAD_STATE.get(appid) or {}
    state.update(update)
    DOWNLOAD_STATE[appid] = state


def _get_download_state(appid: int) -> dict:
    return DOWNLOAD_STATE.get(appid, {}).copy()


def _is_download_cancelled(appid: int) -> bool:
    try:
        return _get_download_state(appid).get("status") == "cancelled"
    except Exception:
        return False


def _loaded_apps_path() -> str:
    return backend_path(LOADED_APPS_FILE)


def _appid_log_path() -> str:
    return backend_path(APPID_LOG_FILE)


# ---------------------------------------------------------------------------
# App name resolution
# ---------------------------------------------------------------------------

def _extract_applist_entries(data):
    """Return the list of {appid, name} entries from either of the two shapes
    the applist endpoints serve:
      - Steam Web API: {"applist": {"apps": [{"appid": N, "name": "..."}, ...]}}
      - Legacy Morrenus/Hubcap: [{"appid": N, "name": "..."}, ...]
    Any malformed input → empty list, so callers don't need to defend further."""
    if isinstance(data, dict):
        applist = data.get("applist")
        if isinstance(applist, dict):
            apps = applist.get("apps")
            if isinstance(apps, list):
                return apps
        return []
    if isinstance(data, list):
        return data
    return []


def _load_applist_into_memory() -> None:
    global APPLIST_DATA, APPLIST_LOADED
    if APPLIST_LOADED:
        return
    file_path = os.path.join(ensure_temp_download_dir(), APPLIST_FILE_NAME)
    if not os.path.exists(file_path):
        APPLIST_LOADED = True
        return
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        for entry in _extract_applist_entries(data):
            if isinstance(entry, dict):
                appid = entry.get("appid")
                name = entry.get("name")
                if appid and name and isinstance(name, str) and name.strip():
                    APPLIST_DATA[int(appid)] = name.strip()
        APPLIST_LOADED = True
    except Exception:
        APPLIST_LOADED = True


def _get_app_name_from_applist(appid: int) -> str:
    if not APPLIST_LOADED:
        _load_applist_into_memory()
    return APPLIST_DATA.get(int(appid), "")


def _get_loaded_app_name(appid: int) -> str:
    try:
        path = _loaded_apps_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle.read().splitlines():
                    if line.startswith(f"{appid}:"):
                        name = line.split(":", 1)[1].strip()
                        if name:
                            return name
    except Exception:
        pass
    return _get_app_name_from_applist(appid)


def _preload_app_names_cache() -> None:
    # From appid log
    try:
        log_path = _appid_log_path()
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as handle:
                for line in handle.read().splitlines():
                    if "]" in line and " - " in line:
                        try:
                            parts = line.split("]", 1)
                            if len(parts) < 2:
                                continue
                            content_parts = parts[1].strip().split(" - ", 2)
                            if len(content_parts) >= 2:
                                appid = int(content_parts[0].strip())
                                name = content_parts[1].strip()
                                if name and not name.startswith("Unknown"):
                                    APP_NAME_CACHE[appid] = name
                        except (ValueError, IndexError):
                            continue
    except Exception:
        pass
    # From loaded apps
    try:
        path = _loaded_apps_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle.read().splitlines():
                    if ":" in line:
                        parts = line.split(":", 1)
                        try:
                            appid = int(parts[0].strip())
                            name = parts[1].strip()
                            if name:
                                APP_NAME_CACHE[appid] = name
                        except (ValueError, IndexError):
                            continue
    except Exception:
        pass
    try:
        _load_applist_into_memory()
    except Exception:
        pass


async def fetch_app_name(appid: int) -> str:
    """Fetch app name with caching and rate limiting."""
    global _LAST_API_CALL_TIME

    if appid in APP_NAME_CACHE and APP_NAME_CACHE[appid]:
        return APP_NAME_CACHE[appid]

    # Check applist
    applist_name = _get_app_name_from_applist(appid)
    if applist_name:
        APP_NAME_CACHE[appid] = applist_name
        return applist_name

    # Rate limit Steam API calls
    now = time.time()
    elapsed = now - _LAST_API_CALL_TIME
    if elapsed < _API_CALL_MIN_INTERVAL:
        await asyncio.sleep(_API_CALL_MIN_INTERVAL - elapsed)
    _LAST_API_CALL_TIME = time.time()

    # Steam API as fallback
    try:
        client = await ensure_http_client("fetch_app_name")
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
        resp = await client.get(url, follow_redirects=True, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        entry = data.get(str(appid)) or {}
        if isinstance(entry, dict):
            inner = entry.get("data") or {}
            name = inner.get("name")
            if isinstance(name, str) and name.strip():
                APP_NAME_CACHE[appid] = name.strip()
                return name.strip()
    except Exception:
        pass

    APP_NAME_CACHE[appid] = ""
    return ""


def _get_installed_size_bytes(appid: int) -> int:
    """Return installed game size in bytes, or 0 if not found/installed."""
    try:
        from steam_utils import detect_steam_install_path, get_steam_libraries
        libraries = get_steam_libraries()
        steam_path = detect_steam_install_path() or "/home/deck/.local/share/Steam"
        if not libraries:
            libraries = [{"path": steam_path}]

        for lib in libraries:
            lib_path = lib.get("path", "") if isinstance(lib, dict) else str(lib)
            acf = os.path.join(lib_path, "steamapps", f"appmanifest_{appid}.acf")
            if not os.path.exists(acf):
                continue
            # Try to find install dir from ACF
            import re as _re
            with open(acf, "r", encoding="utf-8") as f:
                content = f.read()
            m = _re.search(r'"installdir"\s+"([^"]+)"', content)
            if not m:
                continue
            game_dir = os.path.join(lib_path, "steamapps", "common", m.group(1))
            if not os.path.isdir(game_dir):
                continue
            # Fast size via du
            import subprocess
            result = subprocess.run(
                ["du", "-sb", game_dir],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return int(result.stdout.split()[0])
    except Exception:
        pass
    return 0


def _parse_storage_from_requirements(app_data: dict) -> int:
    """Parse required storage bytes from Steam's pc_requirements HTML.

    Steam returns strings like:
      '<strong>Storage:</strong> 10 GB available space'
    Returns bytes, or 0 if not found.
    """
    import re as _re
    for key in ("minimum", "recommended"):
        html = (app_data.get("pc_requirements") or {}).get(key) or ""
        if not html:
            continue
        # Strip tags then look for "Storage: N GB/MB"
        plain = _re.sub(r"<[^>]+>", "", html)
        m = _re.search(r"Storage[^:]*:\s*([\d.,]+)\s*(GB|MB|TB)", plain, _re.IGNORECASE)
        if m:
            value = float(m.group(1).replace(",", "."))
            unit = m.group(2).upper()
            if unit == "TB":
                return int(value * 1_000_000_000_000)
            if unit == "GB":
                return int(value * 1_073_741_824)
            if unit == "MB":
                return int(value * 1_048_576)
    return 0


async def get_game_notices(appid: int) -> dict:
    """Return game info, DRM and external launcher notices from the Steam store API."""
    try:
        client = await ensure_http_client("get_game_notices")
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english"
        resp = await client.get(url, follow_redirects=True, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        app_data = (data.get(str(appid)) or {}).get("data") or {}
        if not app_data:
            return {"success": True, "notices": [], "info": None}

        # --- Game info ---
        name = app_data.get("name") or ""
        developers = app_data.get("developers") or []
        developer = developers[0] if developers else ""
        platforms = app_data.get("platforms") or {}
        metacritic = (app_data.get("metacritic") or {}).get("score")
        achievements_total = (app_data.get("achievements") or {}).get("total") or 0

        # Detect PT-BR support by stripping HTML tags from supported_languages
        import re as _re
        lang_raw = app_data.get("supported_languages") or ""
        lang_plain = _re.sub(r"<[^>]+>", "", lang_raw)
        has_ptbr = bool(_re.search(r"portuguese.*brazil|brazil.*portuguese", lang_plain, _re.IGNORECASE))

        # --- Game size ---
        size_bytes = _get_installed_size_bytes(appid)
        if not size_bytes:
            size_bytes = _parse_storage_from_requirements(app_data)

        info = {
            "name": name,
            "developer": developer,
            "metacritic": metacritic,
            "platforms": {
                "windows": bool(platforms.get("windows")),
                "linux": bool(platforms.get("linux")),
                "mac": bool(platforms.get("mac")),
            },
            "achievements": achievements_total,
            "hasPtBR": has_ptbr,
            "sizeBytes": size_bytes,
        }

        # --- DRM / launcher notices ---
        notices = []
        drm_text = app_data.get("drm_notice") or ""
        short_desc = app_data.get("short_description") or ""
        search_text = f"{drm_text} {short_desc}"

        if _re.search(r"denuvo", drm_text, _re.IGNORECASE):
            notices.append("denuvo")
        elif drm_text.strip():
            notices.append(f"drm:{drm_text.strip()[:120]}")

        launchers = [
            (r"ea app|ea desktop|electronic arts app", "EA App"),
            (r"ubisoft connect|uplay", "Ubisoft Connect"),
            (r"rockstar games launcher|social club", "Rockstar Games Launcher"),
            (r"battle\.?net", "Battle.net"),
            (r"epic games (store|launcher)", "Epic Games Launcher"),
            (r"xbox app|microsoft store", "Xbox App"),
            (r"2k launcher", "2K Launcher"),
            (r"bethesda\.?net", "Bethesda.net Launcher"),
        ]
        for pattern, label in launchers:
            if _re.search(pattern, search_text, _re.IGNORECASE):
                notices.append(f"launcher:{label}")

        return {"success": True, "notices": notices, "info": info}
    except Exception as e:
        return {"success": False, "notices": [], "info": None, "error": str(e)}


def _append_loaded_app(appid: int, name: str) -> None:
    try:
        path = _loaded_apps_path()
        lines = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        prefix = f"{appid}:"
        lines = [line for line in lines if not line.startswith(prefix)]
        lines.append(f"{appid}:{name}")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except Exception as exc:
        logger.warning(f"DeckTools: _append_loaded_app failed for {appid}: {exc}")


def _remove_loaded_app(appid: int) -> None:
    try:
        path = _loaded_apps_path()
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        prefix = f"{appid}:"
        new_lines = [line for line in lines if not line.startswith(prefix)]
        if len(new_lines) != len(lines):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(new_lines) + ("\n" if new_lines else ""))
    except Exception:
        pass


def _log_appid_event(action: str, appid: int, name: str) -> None:
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        line = f"[{action}] {appid} - {name} - {stamp}\n"
        with open(_appid_log_path(), "a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Applist & Games DB initialization
# ---------------------------------------------------------------------------

async def init_applist() -> None:
    file_path = os.path.join(ensure_temp_download_dir(), APPLIST_FILE_NAME)
    if not os.path.exists(file_path):
        client = await ensure_http_client("DownloadApplist")
        urls = [u for u in (APPLIST_URL, APPLIST_URL_FALLBACK) if u]
        for url in urls:
            try:
                resp = await client.get(url, follow_redirects=True, timeout=APPLIST_DOWNLOAD_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
                # Validate before persisting so a malformed response doesn't
                # poison the cache. We accept either of the two known shapes
                # (Steam Web API or legacy Morrenus/Hubcap — see
                # _extract_applist_entries) and require at least one entry.
                if _extract_applist_entries(data):
                    with open(file_path, "w", encoding="utf-8") as handle:
                        json.dump(data, handle)
                    break
                logger.warning(f"LumaDeck: applist from {url} parsed but had no entries")
            except Exception as exc:
                logger.warning(f"LumaDeck: applist fetch from {url} failed: {exc}")
        else:
            logger.warning("LumaDeck: applist unavailable from all sources — search/name resolution will be limited")
    _load_applist_into_memory()


async def init_games_db() -> None:
    global GAMES_DB_DATA, GAMES_DB_LOADED
    file_path = os.path.join(ensure_temp_download_dir(), GAMES_DB_FILE_NAME)
    try:
        client = await ensure_http_client("DownloadGamesDB")
        resp = await client.get(GAMES_DB_URL, follow_redirects=True, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        GAMES_DB_DATA = data
        GAMES_DB_LOADED = True
    except Exception as exc:
        logger.warning(f"DeckTools: Failed to download Games DB: {exc}")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as handle:
                    GAMES_DB_DATA = json.load(handle)
                GAMES_DB_LOADED = True
            except Exception:
                pass


def get_games_database() -> dict:
    return {"success": True, "data": GAMES_DB_DATA, "loaded": GAMES_DB_LOADED}


# ---------------------------------------------------------------------------
# Process & install
# ---------------------------------------------------------------------------

def _zip_basename(name: str) -> str:
    """Get the basename of a zip entry, handling both / and \\ separators."""
    return name.replace("\\", "/").split("/")[-1]


async def _enrich_lua_with_linux_depot(appid: int, lua_text: str) -> tuple[str, bool]:
    """Add Linux depot to lua if the manifest is already in the local depotcache.

    Returns (lua_text, has_linux_depot). Only adds the depot if the manifest
    binary was already extracted from the zip — avoids 401 errors trying to
    fetch manifests anonymously from Steam CDN.
    """
    try:
        for m in re.finditer(r'addappid\(\s*(\d+)\s*,\s*\d+\s*,', lua_text):
            _ = m.group(1)  # windows depot present

        if not re.search(r'addappid\(\s*\d+\s*,\s*\d+\s*,', lua_text):
            return lua_text, False  # No depots to work with

        steam_path = detect_steam_install_path()
        depotcache_dir = os.path.join(steam_path or "", "depotcache")

        try:
            client = await ensure_http_client("EnrichLua")
            resp = await client.get(f"https://api.steamcmd.net/v1/info/{appid}", timeout=10)
            if resp.status_code != 200:
                return lua_text, False

            data = resp.json()
            if data.get("status") != "success":
                return lua_text, False

            app_depots = data.get("data", {}).get(str(appid), {}).get("depots", {})

            linux_depot_id = None
            linux_manifest = None
            linux_size = None

            for depot_id, depot_info in app_depots.items():
                if not depot_id.isdigit():
                    continue
                config = depot_info.get("config", {})
                if config.get("oslist") == "linux" and config.get("osarch") == "64":
                    linux_depot_id = depot_id
                    public = depot_info.get("manifests", {}).get("public", {})
                    if isinstance(public, dict):
                        linux_manifest = public.get("gid")
                        linux_size = public.get("size", 0)
                    break

            if not linux_depot_id or not linux_manifest:
                return lua_text, False

            # Only add the Linux depot if the manifest binary is already in depotcache
            # (placed there when the API zip contained it). Without it, DDM gets 401.
            manifest_file = os.path.join(depotcache_dir, f"{linux_depot_id}_{linux_manifest}.manifest")
            if not os.path.exists(manifest_file):
                logger.info(
                    f"DeckTools: Linux depot {linux_depot_id} found for {appid} "
                    f"but manifest {linux_manifest} not in depotcache — skipping enrichment"
                )
                return lua_text, False

            windows_token = None
            for m in re.finditer(r'addappid\(\s*(\d+)\s*,\s*\d+\s*,\s*"([^"]+)"', lua_text):
                windows_token = m.group(2)
                if windows_token:
                    break

            if not windows_token:
                return lua_text, False

            linux_line = f'addappid({linux_depot_id},1,"{windows_token}")\n'
            linux_manifest_line = f'--setManifestid({linux_depot_id},"{linux_manifest}",{linux_size})\n'
            lua_text = lua_text.rstrip() + "\n" + linux_line + linux_manifest_line
            logger.info(f"DeckTools: Added Linux depot {linux_depot_id} (manifest in depotcache) for {appid}")
            return lua_text, True

        except Exception as exc:
            logger.warning(f"DeckTools: Failed to enrich lua with Linux depot: {exc}")
            return lua_text, False

    except Exception as exc:
        logger.warning(f"DeckTools: Error in _enrich_lua_with_linux_depot: {exc}")
        return lua_text, False


async def _process_and_install_lua(appid: int, zip_path: str) -> None:
    """Process downloaded zip: extract manifests and lua files."""
    import zipfile

    if _is_download_cancelled(appid):
        raise RuntimeError("cancelled")

    base_path = detect_steam_install_path()
    target_dir = os.path.join(base_path or "", "config", "stplug-in")
    os.makedirs(target_dir, exist_ok=True)

    # ACCELA/Bifrost launcher integration (skip AppImage - it's a GUI app)
    launcher_bin = _load_launcher_path()
    if os.path.exists(launcher_bin) and not launcher_bin.endswith(".AppImage"):
        logger.info(f"DeckTools: Sending {zip_path} to launcher at {launcher_bin}")
        try:
            if not os.access(launcher_bin, os.X_OK):
                os.chmod(launcher_bin, 0o755)
            clean_env = os.environ.copy()
            clean_env.pop("LD_LIBRARY_PATH", None)
            clean_env.pop("LD_PRELOAD", None)
            clean_env.pop("STEAM_RUNTIME", None)

            import subprocess
            proc = subprocess.Popen(
                [launcher_bin, zip_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=clean_env,
            )
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"Launcher exited with code {proc.returncode}")
            if stderr:
                logger.warning(f"Launcher stderr: {stderr[:200]}")
        except Exception as e:
            logger.error(f"DeckTools: Failed to run launcher: {e}")

    # Extract manifests and lua from zip
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        logger.info(f"DeckTools: Zip contains {len(names)} entries: {names}")

        # Extract .manifest files to depotcache
        depotcache_dir = os.path.join(base_path or "", "depotcache")
        os.makedirs(depotcache_dir, exist_ok=True)
        for name in names:
            if _is_download_cancelled(appid):
                raise RuntimeError("cancelled")
            if name.lower().endswith(".manifest"):
                pure = _zip_basename(name)
                data = archive.read(name)
                out_path = os.path.join(depotcache_dir, pure)
                with open(out_path, "wb") as mf:
                    mf.write(data)
                logger.info(f"DeckTools: Extracted manifest -> {out_path}")

        # Find and process .lua file
        candidates = [n for n in names if re.fullmatch(r"\d+\.lua", _zip_basename(n))]

        if _is_download_cancelled(appid):
            raise RuntimeError("cancelled")

        chosen = None
        preferred = f"{appid}.lua"
        for name in candidates:
            if _zip_basename(name) == preferred:
                chosen = name
                break
        if chosen is None and candidates:
            chosen = candidates[0]
        if not chosen:
            raise RuntimeError("No numeric .lua file found in zip")

        data = archive.read(chosen)
        try:
            text = data.decode("utf-8")
        except Exception:
            text = data.decode("utf-8", errors="replace")

        # Comment out setManifestid() calls to prevent Steam from locking
        # manifest versions and showing an "Update" button (LuaToolsLinux approach)
        processed_lines = []
        for line in text.splitlines(True):
            if re.match(r"^\s*setManifestid\(", line) and not re.match(r"^\s*--", line):
                line = re.sub(r"^(\s*)", r"\1--", line)
            processed_lines.append(line)
        processed_text = "".join(processed_lines)

        # Enrich lua with missing Linux depot if manifest is already in depotcache
        processed_text, has_linux_depot = await _enrich_lua_with_linux_depot(appid, processed_text)
        _set_download_state(appid, {"hasLinuxDepot": has_linux_depot})

        _set_download_state(appid, {"status": "installing"})
        dest_file = os.path.join(target_dir, f"{appid}.lua")
        if _is_download_cancelled(appid):
            raise RuntimeError("cancelled")
        with open(dest_file, "w", encoding="utf-8") as output:
            output.write(processed_text)
        logger.info(f"DeckTools: Installed lua -> {dest_file}")
        _set_download_state(appid, {"installedPath": dest_file})

    try:
        os.remove(zip_path)
    except Exception:
        pass


def _load_launcher_path() -> str:
    default_path = os.path.expanduser("~/.local/share/Bifrost/bin/Bifrost")
    # Also check /home/deck path for Steam Deck root context
    deck_default = "/home/deck/.local/share/Bifrost/bin/Bifrost"
    accela_appimage = "/home/deck/.local/share/ACCELA/ACCELA.AppImage"
    try:
        path_file = data_path("launcher_path.txt")
        if os.path.exists(path_file):
            with open(path_file, "r", encoding="utf-8") as f:
                saved = f.read().strip()
                if saved:
                    return saved
    except Exception:
        pass
    if os.path.exists(deck_default):
        return deck_default
    if os.path.exists(accela_appimage):
        return accela_appimage
    return default_path


# ---------------------------------------------------------------------------
# Game install directory resolution
# ---------------------------------------------------------------------------

async def _fetch_installdir_from_api(appid: int) -> str:
    """Fetch the official installdir from Steam's store API (like ACCELA does)."""
    try:
        client = await ensure_http_client("steam_api")
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
        resp = await client.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            app_data = data.get(str(appid), {})
            if app_data.get("success"):
                install_dir = app_data.get("data", {}).get("install_dir")
                if install_dir:
                    logger.info(f"DeckTools: installdir from Steam API: {install_dir}")
                    return install_dir
    except Exception as e:
        logger.debug(f"DeckTools: Failed to fetch installdir from API: {e}")
    return ""


async def _determine_install_dir(appid: int, game_name: str, target_library_path: str = "") -> str:
    """Determine the directory to download game files into (like ACCELA).

    Priority: Steam API installdir > existing directory on disk > ACF > game name.
    If target_library_path is given, use that library instead of the primary one.
    """
    steam_path = detect_steam_install_path()
    if not steam_path:
        steam_path = "/home/deck/.local/share/Steam"

    # Use target library if specified, otherwise default to primary Steam path
    library_base = target_library_path if target_library_path and os.path.isdir(target_library_path) else steam_path
    common_path = os.path.join(library_base, "steamapps", "common")

    # 1. Try Steam API for official installdir (like ACCELA's steam_api.py)
    api_installdir = await _fetch_installdir_from_api(appid)
    if api_installdir:
        full_path = os.path.join(common_path, api_installdir)
        logger.info(f"DeckTools: Install dir from Steam API: {full_path}")
        return full_path

    # 2. Check if a directory already exists on disk matching the game
    if os.path.isdir(common_path):
        # Check ACF installdir first
        acf_path = os.path.join(steam_path, "steamapps", f"appmanifest_{appid}.acf")
        if os.path.exists(acf_path):
            try:
                with open(acf_path, "r", encoding="utf-8") as f:
                    content = f.read()
                m = re.search(r'"installdir"\s+"([^"]+)"', content)
                if m:
                    acf_dir = m.group(1)
                    full_path = os.path.join(common_path, acf_dir)
                    if os.path.isdir(full_path):
                        logger.info(f"DeckTools: Install dir from ACF (verified on disk): {full_path}")
                        return full_path
                    # ACF dir doesn't exist — scan for similar directories
                    logger.info(f"DeckTools: ACF installdir '{acf_dir}' not found on disk, scanning...")
            except Exception:
                pass

        # Scan common/ for directories matching game name
        game_lower = game_name.lower()
        for d in os.listdir(common_path):
            if d.lower().startswith(game_lower[:20]) or game_lower.startswith(d.lower()[:20]):
                candidate = os.path.join(common_path, d)
                if os.path.isdir(candidate):
                    logger.info(f"DeckTools: Install dir matched on disk: {candidate}")
                    return candidate

    # 3. Fallback: use game name as directory name
    safe_name = re.sub(r'[<>:"/\\|?*]', '', game_name).strip()
    if not safe_name:
        safe_name = f"app_{appid}"
    full_path = os.path.join(common_path, safe_name)
    logger.info(f"DeckTools: Install dir from game name: {full_path}")
    return full_path


# ---------------------------------------------------------------------------
# DepotDownloader integration — download actual game files
# ---------------------------------------------------------------------------

# Persistent directory where DDM is cached after extraction
_DDM_CACHE_DIR = "/home/deck/.local/share/DeckTools/deps"

# DepotDownloaderMod executable search paths (self-contained build)
_DDM_EXE_SEARCH_PATHS = [
    os.path.join(_DDM_CACHE_DIR, "DepotDownloaderMod"),
    "/home/deck/.local/share/ACCELA/deps/DepotDownloaderMod",
]

# DepotDownloaderMod DLL search paths (framework-dependent build)
_DDM_DLL_SEARCH_PATHS = [
    os.path.join(_DDM_CACHE_DIR, "DepotDownloaderMod.dll"),
    "/home/deck/.local/share/ACCELA/deps/DepotDownloaderMod.dll",
]

# Known locations where ACCELA AppImage may exist
_ACCELA_APPIMAGE_CANDIDATES = [
    "/home/deck/.local/share/ACCELA/ACCELA.AppImage",
    os.path.expanduser("~/.local/share/ACCELA/ACCELA.AppImage"),
]

# dotnet binary search paths
_DOTNET_SEARCH_PATHS = [
    "/home/deck/.dotnet/dotnet",
    "/home/deck/.local/share/dotnet/dotnet",
    os.path.expanduser("~/.dotnet/dotnet"),
    os.path.join(_DDM_CACHE_DIR, "dotnet", "dotnet"),
]


# ---------------------------------------------------------------------------
# DDM cache validation
# ---------------------------------------------------------------------------

_DDM_CACHE_MARKER = os.path.join(_DDM_CACHE_DIR, ".ddm_cache_info.json")


def _write_ddm_cache_marker(appimage_path: str) -> None:
    """Record AppImage identity alongside cached DDM for staleness detection."""
    try:
        st = os.stat(appimage_path)
        marker = {
            "appimage_path": appimage_path,
            "mtime": st.st_mtime,
            "size": st.st_size,
        }
        os.makedirs(_DDM_CACHE_DIR, exist_ok=True)
        with open(_DDM_CACHE_MARKER, "w", encoding="utf-8") as f:
            json.dump(marker, f)
    except Exception as exc:
        logger.warning(f"DeckTools: Failed to write DDM cache marker: {exc}")


def _is_ddm_cache_valid() -> bool:
    """Check if cached DDM matches the current ACCELA AppImage."""
    appimage = _find_accela_appimage()
    if not appimage:
        return True  # No AppImage to compare against

    ddm_exe = os.path.join(_DDM_CACHE_DIR, "DepotDownloaderMod")
    ddm_dll = os.path.join(_DDM_CACHE_DIR, "DepotDownloaderMod.dll")
    has_cache = os.path.exists(ddm_exe) or os.path.exists(ddm_dll)

    if not has_cache:
        return True  # Nothing cached to invalidate

    if not os.path.exists(_DDM_CACHE_MARKER):
        return False  # Cache exists but no marker — invalidate to be safe

    try:
        with open(_DDM_CACHE_MARKER, "r", encoding="utf-8") as f:
            marker = json.load(f)
        st = os.stat(appimage)
        return (marker.get("mtime") == st.st_mtime
                and marker.get("size") == st.st_size)
    except Exception:
        return False


def _invalidate_ddm_cache() -> None:
    """Remove all cached DDM files so they get re-extracted."""
    import shutil
    try:
        if os.path.isdir(_DDM_CACHE_DIR):
            shutil.rmtree(_DDM_CACHE_DIR, ignore_errors=True)
            logger.info("DeckTools: DDM cache invalidated (AppImage changed)")
    except Exception as exc:
        logger.warning(f"DeckTools: Failed to invalidate DDM cache: {exc}")


async def validate_ddm_cache() -> None:
    """Check DDM cache validity on startup; invalidate if stale."""
    loop = asyncio.get_event_loop()
    valid = await loop.run_in_executor(None, _is_ddm_cache_valid)
    if not valid:
        logger.info("DeckTools: ACCELA AppImage changed, invalidating DDM cache")
        await loop.run_in_executor(None, _invalidate_ddm_cache)


def _find_dotnet() -> str:
    """Find the dotnet runtime binary."""
    for path in _DOTNET_SEARCH_PATHS:
        if os.path.exists(path):
            return path
    # Try PATH
    import shutil
    found = shutil.which("dotnet")
    if found:
        return found
    return ""


def _find_accela_appimage() -> str:
    """Find the ACCELA AppImage file."""
    for path in _ACCELA_APPIMAGE_CANDIDATES:
        if os.path.isfile(path):
            return path
    # Scan ACCELA directories for any .AppImage file
    from paths import find_accela_root
    accela_root = find_accela_root()
    if accela_root:
        try:
            for f in os.listdir(accela_root):
                if f.lower().endswith(".appimage"):
                    return os.path.join(accela_root, f)
        except Exception:
            pass
    return ""


def _copy_ddm_from_tree(root_dir: str) -> str:
    """Search a directory tree for DDM files and copy them to the persistent cache.

    Returns the path to the cached DDM (exe or dll), or "" if not found.
    """
    import shutil

    ddm_found = ""
    ddm_dll_found = ""
    dotnet_found = ""
    for dirpath, _dirs, files in os.walk(root_dir):
        for fname in files:
            fl = fname.lower()
            if fname in ("DepotDownloaderMod", "DepotDownloader") and not fl.endswith(".dll"):
                ddm_found = os.path.join(dirpath, fname)
            elif fname in ("DepotDownloaderMod.dll", "DepotDownloader.dll"):
                ddm_dll_found = os.path.join(dirpath, fname)
            elif fname == "dotnet" and not fl.endswith((".dll", ".so")):
                dotnet_found = os.path.join(dirpath, fname)

    if not ddm_found and not ddm_dll_found:
        logger.warning("DeckTools: DepotDownloaderMod not found in tree")
        return ""

    os.makedirs(_DDM_CACHE_DIR, exist_ok=True)

    if ddm_found:
        dest = os.path.join(_DDM_CACHE_DIR, "DepotDownloaderMod")
        shutil.copy2(ddm_found, dest)
        os.chmod(dest, 0o755)
        logger.info(f"DeckTools: Cached DDM executable -> {dest}")
        return dest

    # Copy ALL files from DDM directory (runtimeconfig.json, deps, etc.)
    ddm_src_dir = os.path.dirname(ddm_dll_found)
    for item in os.listdir(ddm_src_dir):
        src = os.path.join(ddm_src_dir, item)
        dst = os.path.join(_DDM_CACHE_DIR, item)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        elif os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
    dest = os.path.join(_DDM_CACHE_DIR, "DepotDownloaderMod.dll")
    # If the original DLL was named DepotDownloader (without Mod), create aliases
    # so the rest of the codebase can always reference DepotDownloaderMod.*
    src_dll_name = os.path.basename(ddm_dll_found)
    if src_dll_name != "DepotDownloaderMod.dll":
        base_name = src_dll_name.replace(".dll", "")
        for ext in (".dll", ".runtimeconfig.json", ".deps.json"):
            src_f = os.path.join(_DDM_CACHE_DIR, base_name + ext)
            dst_f = os.path.join(_DDM_CACHE_DIR, "DepotDownloaderMod" + ext)
            if os.path.isfile(src_f) and not os.path.exists(dst_f):
                shutil.copy2(src_f, dst_f)

    # Copy dotnet if found and not available system-wide
    if dotnet_found and not _find_dotnet():
        dotnet_dest_dir = os.path.join(_DDM_CACHE_DIR, "dotnet")
        dotnet_src_dir = os.path.dirname(dotnet_found)
        if os.path.isdir(dotnet_src_dir):
            shutil.copytree(dotnet_src_dir, dotnet_dest_dir, dirs_exist_ok=True)
            os.chmod(os.path.join(dotnet_dest_dir, "dotnet"), 0o755)
            logger.info(f"DeckTools: Cached dotnet runtime -> {dotnet_dest_dir}")

    logger.info(f"DeckTools: Cached DDM directory ({len(os.listdir(ddm_src_dir))} files) -> {_DDM_CACHE_DIR}")
    return dest


def _extract_ddm_via_mount(appimage: str) -> str:
    """Fast path: FUSE-mount the AppImage and copy DDM without full extraction."""
    import signal
    import subprocess

    proc = None
    try:
        proc = subprocess.Popen(
            [appimage, "--appimage-mount"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        mount_point = proc.stdout.readline().decode("utf-8").strip()
        if not mount_point or not os.path.isdir(mount_point):
            logger.warning(f"DeckTools: AppImage mount returned invalid path: {mount_point!r}")
            return ""

        logger.info(f"DeckTools: AppImage FUSE-mounted at {mount_point}")
        return _copy_ddm_from_tree(mount_point)

    except Exception as exc:
        logger.warning(f"DeckTools: AppImage FUSE mount failed: {exc}")
        return ""
    finally:
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def _extract_ddm_via_full_extract(appimage: str) -> str:
    """Fallback: full --appimage-extract, copy DDM, then clean up."""
    import shutil
    import subprocess
    import tempfile

    extract_dir = os.path.join(tempfile.gettempdir(), "decktools_appimage_extract")
    try:
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)

        proc = subprocess.run(
            [appimage, "--appimage-extract"],
            cwd=extract_dir,
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            logger.warning(f"DeckTools: AppImage extraction failed: {proc.stderr[:200]}")
            return ""

        squashfs_root = os.path.join(extract_dir, "squashfs-root")
        if not os.path.isdir(squashfs_root):
            logger.warning("DeckTools: squashfs-root not found after extraction")
            return ""

        return _copy_ddm_from_tree(squashfs_root)

    except Exception as exc:
        logger.warning(f"DeckTools: AppImage full extraction failed: {exc}")
        return ""
    finally:
        try:
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass


def _extract_ddm_from_appimage() -> str:
    """Extract DepotDownloaderMod from ACCELA AppImage with caching.

    Tries fast FUSE mount first, falls back to full extraction.
    Writes a cache marker so staleness can be detected on next startup.
    """
    import stat as stat_mod

    appimage = _find_accela_appimage()
    if not appimage:
        return ""

    logger.info(f"DeckTools: Found ACCELA AppImage at {appimage}, extracting DDM...")

    try:
        st = os.stat(appimage)
        os.chmod(appimage, st.st_mode | stat_mod.S_IEXEC)
    except Exception:
        pass

    # Fast path: FUSE mount (no disk extraction)
    result = _extract_ddm_via_mount(appimage)
    if result:
        _write_ddm_cache_marker(appimage)
        return result

    # Fallback: full extraction
    logger.info("DeckTools: FUSE mount failed, falling back to --appimage-extract")
    result = _extract_ddm_via_full_extract(appimage)
    if result:
        _write_ddm_cache_marker(appimage)
    return result


def _find_ddm_executable() -> tuple[list[str], str]:
    """Find DepotDownloaderMod and return (cmd_prefix, description).

    Search order:
    1. Custom workshop tool path (user-configured)
    2. Known executable paths (DeckTools/deps, ACCELA/deps)
    3. Plugin backend directory
    4. DLL paths with dotnet runtime
    5. Auto-extract from ACCELA AppImage (last resort)

    Returns ([], "") if not found.
    """
    import stat as stat_mod
    from workshop import load_workshop_tool_path

    # 1. Check custom workshop tool path for executable
    custom = load_workshop_tool_path()
    if custom and os.path.exists(custom):
        if os.path.isdir(custom):
            exe = os.path.join(custom, "DepotDownloaderMod")
            if os.path.exists(exe):
                try:
                    st = os.stat(exe)
                    os.chmod(exe, st.st_mode | stat_mod.S_IEXEC)
                except Exception:
                    pass
                return [exe], f"executable: {exe}"
            dll = os.path.join(custom, "DepotDownloaderMod.dll")
            if os.path.exists(dll):
                dotnet = _find_dotnet()
                if dotnet:
                    return [dotnet, dll], f"dotnet+dll: {dll}"
        elif os.path.isfile(custom):
            if custom.endswith(".dll"):
                dotnet = _find_dotnet()
                if dotnet:
                    return [dotnet, custom], f"dotnet+dll: {custom}"
            else:
                try:
                    st = os.stat(custom)
                    os.chmod(custom, st.st_mode | stat_mod.S_IEXEC)
                except Exception:
                    pass
                return [custom], f"executable: {custom}"

    # 2. Check known executable paths (self-contained)
    for path in _DDM_EXE_SEARCH_PATHS:
        if os.path.exists(path):
            try:
                st = os.stat(path)
                os.chmod(path, st.st_mode | stat_mod.S_IEXEC)
            except Exception:
                pass
            return [path], f"executable: {path}"

    # 3. Plugin backend dir executable
    base = os.path.join(get_plugin_dir(), "backend")
    bundled_exe = os.path.join(base, "DepotDownloaderMod")
    if os.path.exists(bundled_exe):
        try:
            st = os.stat(bundled_exe)
            os.chmod(bundled_exe, st.st_mode | stat_mod.S_IEXEC)
        except Exception:
            pass
        return [bundled_exe], f"executable: {bundled_exe}"

    # 4. Check known DLL paths (framework-dependent, needs dotnet)
    dotnet = _find_dotnet()
    if dotnet:
        for path in _DDM_DLL_SEARCH_PATHS:
            if os.path.exists(path):
                # Verify runtimeconfig.json exists alongside the DLL
                rc_path = path.replace(".dll", ".runtimeconfig.json")
                if os.path.exists(rc_path):
                    return [dotnet, path], f"dotnet+dll: {path}"
                else:
                    logger.warning(f"DeckTools: DDM DLL found at {path} but missing runtimeconfig.json, skipping")

        bundled_dll = os.path.join(base, "deps", "DepotDownloaderMod.dll")
        if os.path.exists(bundled_dll):
            return [dotnet, bundled_dll], f"dotnet+dll: {bundled_dll}"

    # 5. Try extracting from ACCELA AppImage
    extracted = _extract_ddm_from_appimage()
    if extracted:
        if extracted.endswith(".dll"):
            # Check for dotnet again (may have been extracted from AppImage)
            dotnet = _find_dotnet()
            # Also check extracted dotnet
            extracted_dotnet = os.path.join(_DDM_CACHE_DIR, "dotnet", "dotnet")
            if not dotnet and os.path.exists(extracted_dotnet):
                dotnet = extracted_dotnet
            if dotnet:
                return [dotnet, extracted], f"dotnet+dll (extracted from AppImage): {extracted}"
        else:
            try:
                os.chmod(extracted, 0o755)
            except Exception:
                pass
            return [extracted], f"executable (extracted from AppImage): {extracted}"

    return [], ""


async def _auto_download_ddm() -> str:
    """Download the latest self-contained DepotDownloader binary from GitHub if not found.

    Returns the path to the downloaded executable, or "" on failure.
    """
    import zipfile
    import tempfile

    dest_exe = os.path.join(_DDM_CACHE_DIR, "DepotDownloaderMod")
    if os.path.exists(dest_exe):
        return dest_exe

    try:
        client = await ensure_http_client("DDM-downloader")
        resp = await client.get(
            "https://api.github.com/repos/SteamRE/DepotDownloader/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"DeckTools: GitHub API returned {resp.status_code} for DepotDownloader release")
            return ""

        data = resp.json()
        asset_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if "linux" in name.lower() and "x64" in name.lower() and name.endswith(".zip"):
                asset_url = asset["browser_download_url"]
                break

        if not asset_url:
            logger.warning("DeckTools: No linux-x64 asset found in DepotDownloader release")
            return ""

        logger.info(f"DeckTools: Downloading DepotDownloader from {asset_url}")
        dl_resp = await client.get(asset_url, timeout=120, follow_redirects=True)
        if dl_resp.status_code != 200:
            logger.warning(f"DeckTools: Failed to download DepotDownloader: {dl_resp.status_code}")
            return ""

        os.makedirs(_DDM_CACHE_DIR, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(dl_resp.content)
            tmp_path = tmp.name

        try:
            with zipfile.ZipFile(tmp_path) as zf:
                for member in zf.namelist():
                    basename = os.path.basename(member)
                    if basename in ("DepotDownloader", "DepotDownloaderMod") and not member.endswith("/"):
                        with zf.open(member) as src, open(dest_exe, "wb") as dst:
                            dst.write(src.read())
                        os.chmod(dest_exe, 0o755)
                        logger.info(f"DeckTools: DepotDownloader extracted to {dest_exe}")
                        return dest_exe
            logger.warning("DeckTools: DepotDownloader executable not found inside zip")
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    except Exception as exc:
        logger.warning(f"DeckTools: Auto-download of DepotDownloader failed: {exc}")

    return ""


def _parse_lua_depots(lua_path: str) -> list[dict]:
    """Parse a stplug-in lua file to extract depot/manifest info.

    Returns list of dicts: [{"depot": int, "manifest": str, "token": str}, ...]
    """
    depots = []
    manifest_map: Dict[int, dict] = {}

    try:
        with open(lua_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return depots

    # Parse addappid(depotid, type, "token") calls
    for m in re.finditer(r'addappid\(\s*(\d+)\s*,\s*\d+\s*,\s*"([^"]+)"\s*\)', content):
        depot_id = int(m.group(1))
        token = m.group(2)
        manifest_map.setdefault(depot_id, {})["depot"] = depot_id
        manifest_map[depot_id]["token"] = token

    # Parse setManifestid(depotid, "manifestid", ...) calls
    # Also match commented-out lines (--setManifestid) since _process_and_install_lua
    # comments them out to prevent Steam from showing an update button
    for m in re.finditer(r'(?:--\s*)?setManifestid\(\s*(\d+)\s*,\s*"(\d+)"', content):
        depot_id = int(m.group(1))
        manifest_id = m.group(2)
        manifest_map.setdefault(depot_id, {})["depot"] = depot_id
        manifest_map[depot_id]["manifest"] = manifest_id

    depots = [v for v in manifest_map.values() if "depot" in v and "manifest" in v]
    return depots



async def _fetch_depot_os_map(appid: int) -> dict:
    """Return {depot_id_int: "windows"|"linux"|"macos"|""} from steamcmd API."""
    try:
        client = await ensure_http_client("DepotOsMap")
        resp = await client.get(f"https://api.steamcmd.net/v1/info/{appid}", timeout=10)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        if data.get("status") != "success":
            return {}
        app_depots = data.get("data", {}).get(str(appid), {}).get("depots", {})
        os_map: dict = {}
        for depot_id_str, depot_info in app_depots.items():
            if not depot_id_str.isdigit():
                continue
            oslist = depot_info.get("config", {}).get("oslist", "")
            # Use the declared OS; empty or multi-value means cross-platform
            os_map[int(depot_id_str)] = oslist if (oslist and "," not in oslist) else ""
        return os_map
    except Exception as e:
        logger.warning(f"DeckTools: Could not fetch depot OS map for {appid}: {e}")
        return {}


async def _run_depot_download(appid: int, depots: list[dict], install_dir: str) -> None:
    """Run DepotDownloaderMod to download actual game files."""
    import tempfile

    cmd_prefix, ddm_desc = _find_ddm_executable()
    if not cmd_prefix:
        logger.info("DeckTools: DDM not found locally, attempting auto-download from GitHub...")
        _set_download_state(appid, {"depotProgress": "Downloading DepotDownloader..."})
        downloaded = await _auto_download_ddm()
        if downloaded:
            cmd_prefix, ddm_desc = _find_ddm_executable()

    if not cmd_prefix:
        appimage = _find_accela_appimage()
        if appimage:
            logger.error(
                f"DeckTools: ACCELA AppImage found at {appimage} but DepotDownloaderMod "
                "could not be extracted. Try reinstalling dependencies in Settings."
            )
            error_msg = (
                "DepotDownloaderMod not found inside ACCELA AppImage. "
                "Go to Settings > Install Dependencies to fix."
            )
        else:
            logger.error("DeckTools: DepotDownloaderMod not found (no executable or dotnet+dll)")
            error_msg = (
                "DepotDownloaderMod not found. "
                "Go to Settings > Install Dependencies or set the workshop tool path."
            )
        _set_download_state(appid, {"status": "failed", "error": error_msg})
        return

    logger.info(f"DeckTools: Using DDM: {ddm_desc}")

    os.makedirs(install_dir, exist_ok=True)
    total_depots = len(depots)
    logger.info(f"DeckTools: Starting depot download for {appid}: {total_depots} depot(s) -> {install_dir}")

    depot_os_map = await _fetch_depot_os_map(appid)
    logger.info(f"DeckTools: Depot OS map for {appid}: {depot_os_map}")

    # Generate depot keys file (mistwalker_keys.vdf format: "depot_id;key\n")
    temp_dir = tempfile.gettempdir()
    keys_path = os.path.join(temp_dir, "mistwalker_keys.vdf")
    try:
        with open(keys_path, "w", encoding="utf-8") as kf:
            for depot_info in depots:
                token = depot_info.get("token", "")
                if token:
                    kf.write(f"{depot_info['depot']};{token}\n")
        logger.info(f"DeckTools: Wrote depot keys to {keys_path}")
    except Exception as e:
        logger.error(f"DeckTools: Failed to write depot keys: {e}")
        _set_download_state(appid, {"status": "failed", "error": f"Failed to write depot keys: {e}"})
        return

    # Find manifest files in depotcache
    steam_path = detect_steam_install_path() or "/home/deck/.local/share/Steam"
    depotcache_dir = os.path.join(steam_path, "depotcache")

    # Set up clean environment (remove Steam runtime vars that break dotnet)
    clean_env = os.environ.copy()
    clean_env.pop("LD_LIBRARY_PATH", None)
    clean_env.pop("LD_PRELOAD", None)
    clean_env.pop("STEAM_RUNTIME", None)
    dotnet_path = _find_dotnet()
    if dotnet_path:
        clean_env["DOTNET_ROOT"] = os.path.dirname(dotnet_path)

    _DEPOT_MAX_RETRIES = 3
    _DEPOT_RETRY_DELAYS = [5, 15, 30]
    _AUTH_ERROR_MARKERS = ("access denied", "manifest not available", "no subscription", "purchase")
    _MANIFEST_UNAVAILABLE_MARKERS = (
        "no manifest request code",
        "unable to download manifest",
        "encountered 401",
        "manifest 401",
    )
    _DECRYPTION_ERROR_MARKERS = ("padding is invalid",)
    _FILE_LOCK_MARKERS = ("being used by another process", "ioexception: the process cannot access")

    for idx, depot_info in enumerate(depots):
        depot_id = depot_info["depot"]
        manifest_id = depot_info["manifest"]

        if _is_download_cancelled(appid):
            return

        # Find the manifest file in depotcache
        manifest_file = os.path.join(depotcache_dir, f"{depot_id}_{manifest_id}.manifest")
        has_local_manifest = os.path.exists(manifest_file)

        # Use per-depot OS: windows depot gets -os windows, linux gets -os linux,
        # cross-platform (empty oslist) gets no -os flag so all files are downloaded
        depot_os = depot_os_map.get(depot_id, "")
        cmd = cmd_prefix + [
            "-app", str(appid),
            "-depot", str(depot_id),
            "-manifest", str(manifest_id),
            "-dir", install_dir,
            "-max-downloads", "8",
        ]
        if depot_os:
            cmd.extend(["-os", depot_os])

        if has_local_manifest:
            cmd.extend(["-manifestfile", manifest_file])
            logger.info(f"DeckTools: Using manifest file: {manifest_file}")

        try:
            if os.path.getsize(keys_path) > 0:
                cmd.extend(["-depotkeys", keys_path])
        except Exception:
            pass

        # Note: -validate intentionally omitted — it opens all existing game files to check
        # hashes, which causes IOException when Steam has any file open between retries.

        depot_succeeded = False

        for attempt in range(_DEPOT_MAX_RETRIES):
            if attempt > 0:
                delay = _DEPOT_RETRY_DELAYS[min(attempt - 1, len(_DEPOT_RETRY_DELAYS) - 1)]
                logger.info(f"DeckTools: Retrying depot {depot_id} (attempt {attempt + 1}/{_DEPOT_MAX_RETRIES}) after {delay}s")
                _set_download_state(appid, {
                    "depotProgress": f"Depot {idx+1}/{total_depots}: retry {attempt+1} in {delay}s...",
                })
                await asyncio.sleep(delay)
                if _is_download_cancelled(appid):
                    return

            attempt_label = f" (attempt {attempt+1})" if attempt > 0 else ""
            _set_download_state(appid, {
                "status": "depot_download",
                "depotProgress": f"Depot {idx+1}/{total_depots}{attempt_label}",
                "currentDepot": depot_id,
                "depotPercent": 0,
            })

            logger.info(f"DeckTools: DepotDownloader cmd{attempt_label}: {' '.join(cmd)}")

            depot_output = []

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=clean_env,
                )

                percent_re = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)%")
                last_line = ""
                padding_error_count = 0
                _PADDING_ERROR_THRESHOLD = 5
                killed_for_padding = False

                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break

                    if _is_download_cancelled(appid):
                        process.kill()
                        return

                    clean_line = line.decode("utf-8", errors="replace").strip()
                    if clean_line:
                        last_line = clean_line
                        clean_lower = clean_line.lower()
                        depot_output.append(clean_lower)
                        logger.info(f"DeckTools: DDM[{depot_id}]: {clean_line}")

                        if "padding is invalid" in clean_lower:
                            padding_error_count += 1
                            if padding_error_count >= _PADDING_ERROR_THRESHOLD:
                                logger.warning(
                                    f"DeckTools: Depot {depot_id} — too many decryption errors "
                                    f"({padding_error_count}), killing DDM early"
                                )
                                killed_for_padding = True
                                process.kill()
                                break
                        m = percent_re.search(clean_line)
                        if m:
                            pct = float(m.group(1))
                            _set_download_state(appid, {
                                "depotPercent": pct,
                                "depotProgress": f"Depot {idx+1}/{total_depots}: {pct:.0f}%{attempt_label}",
                            })
                        elif "%" not in clean_line:
                            _set_download_state(appid, {
                                "depotProgress": f"Depot {idx+1}/{total_depots}: {clean_line[:60]}{attempt_label}",
                            })

                await process.wait()
                rc = process.returncode
                logger.info(f"DeckTools: DepotDownloader depot {depot_id} exit code: {rc}, last output: {last_line}")

                # Give the OS a moment to release file handles after a killed process
                if killed_for_padding:
                    await asyncio.sleep(3)

                full_log = "\n".join(depot_output)
                auth_error = any(x in full_log for x in _AUTH_ERROR_MARKERS)
                manifest_unavailable = any(x in full_log for x in _MANIFEST_UNAVAILABLE_MARKERS)
                decryption_error = any(x in full_log.lower() for x in _DECRYPTION_ERROR_MARKERS)
                file_lock_error = any(x in full_log.lower() for x in _FILE_LOCK_MARKERS)

                if decryption_error:
                    # Wrong depot key — retrying won't help, skip and continue with others
                    logger.warning(
                        f"DeckTools: Depot {depot_id} skipped — decryption failed (wrong key from API). "
                        f"Game will run via Proton if Windows depot succeeded."
                    )
                    break

                if file_lock_error:
                    # Steam (or a previous DDM process) has a game file open. Retrying with
                    # -validate would hit the same lock. Skip this depot as non-fatal — the
                    # partially downloaded files are still usable via Proton.
                    logger.warning(
                        f"DeckTools: Depot {depot_id} skipped — file locked by another process "
                        f"(Steam may be indexing the game directory). Proton fallback active."
                    )
                    break

                if auth_error or manifest_unavailable:
                    if not has_local_manifest:
                        # Enriched depot (added from SteamCMD, no local manifest) — non-fatal
                        logger.warning(
                            f"DeckTools: Depot {depot_id} skipped — manifest not available anonymously "
                            f"(enriched depot, game will run via Proton)"
                        )
                        break  # skip this depot, continue with others
                    error_msg = f"Access denied for depot {depot_id} (auth required)"
                    logger.warning(f"DeckTools: {error_msg} — not retrying")
                    _set_download_state(appid, {"status": "failed", "error": f"Depot {depot_id} failed: {error_msg}"})
                    return

                if rc != 0:
                    error_msg = last_line if last_line else f"exit code {rc}"
                    logger.warning(f"DeckTools: Depot {depot_id} failed (attempt {attempt+1}): {error_msg}")
                    if attempt < _DEPOT_MAX_RETRIES - 1:
                        continue  # retry
                    if not has_local_manifest:
                        # Enriched depot without local manifest — non-fatal
                        logger.warning(f"DeckTools: Depot {depot_id} skipped after {_DEPOT_MAX_RETRIES} attempts (enriched, non-fatal)")
                        break
                    _set_download_state(appid, {
                        "status": "failed",
                        "error": f"Depot {depot_id} failed after {_DEPOT_MAX_RETRIES} attempts: {error_msg}",
                    })
                    return

                # Success
                depot_succeeded = True
                break

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"DeckTools: Depot {depot_id} error (attempt {attempt+1}): {e}")
                if attempt < _DEPOT_MAX_RETRIES - 1:
                    continue
                _set_download_state(appid, {
                    "status": "failed",
                    "error": f"Depot {depot_id} error after {_DEPOT_MAX_RETRIES} attempts: {e}",
                })
                return

        if not depot_succeeded:
            return

    # Clean up temp keys file
    try:
        if os.path.exists(keys_path):
            os.remove(keys_path)
    except Exception:
        pass

    logger.info(f"DeckTools: All depots downloaded for {appid} -> {install_dir}")

    # NOTE: DDM creates subdirectories like "GameName_windows/" — do NOT flatten them.
    # Steam's launch config expects executables inside those subdirectories.

    # Fix file ownership: Decky runs as root but Steam runs as deck user
    try:
        import subprocess
        subprocess.run(
            ["chown", "-R", "deck:deck", install_dir],
            timeout=120, capture_output=True,
        )
        logger.info(f"DeckTools: Fixed ownership of {install_dir} to deck:deck")
    except Exception as chown_exc:
        logger.warning(f"DeckTools: chown failed for {install_dir}: {chown_exc}")


async def _restart_steam_delayed(delay: int = 5) -> None:
    """Restart Steam after a delay. On Steam Deck Game Mode, Steam auto-restarts.
    Also restarts plugin_loader afterwards so Decky comes back cleanly."""
    await asyncio.sleep(delay)
    try:
        import subprocess
        logger.info("DeckTools: Restarting Steam...")
        subprocess.Popen(
            ["steam", "-shutdown"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning(f"DeckTools: Failed to restart Steam: {e}")
        return



def _get_dir_size(path: str) -> int:
    """Calculate total size of all files in a directory tree."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def _chmod_linux_binaries(install_dir: str) -> None:
    """Set executable permissions on Linux binaries (like ACCELA's _run_chmod_recursive)."""
    import stat
    if not os.path.isdir(install_dir):
        return
    chmod_count = 0
    # Known Linux binary extensions and ELF magic
    binary_exts = {".sh", ".x86", ".x86_64", ".so", ""}
    for dirpath, _dirnames, filenames in os.walk(install_dir):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                _, ext = os.path.splitext(fname)
                should_chmod = False
                if ext.lower() in (".sh", ".x86", ".x86_64"):
                    should_chmod = True
                elif ext == "":
                    # Check if ELF binary
                    try:
                        with open(fpath, "rb") as bf:
                            magic = bf.read(4)
                        if magic == b"\x7fELF":
                            should_chmod = True
                    except Exception:
                        pass
                if should_chmod:
                    st = os.stat(fpath)
                    new_mode = st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    if new_mode != st.st_mode:
                        os.chmod(fpath, new_mode)
                        chmod_count += 1
            except Exception:
                pass
    if chmod_count > 0:
        logger.info(f"DeckTools: Set executable permissions on {chmod_count} files in {install_dir}")


def _create_or_update_appmanifest(appid: int, install_dir: str, depots: list[dict], game_name: str = "", target_library_path: str = "") -> None:
    """Create or overwrite the appmanifest ACF (matching ACCELA's _create_acf_file exactly).

    Key differences from previous version:
    - InstalledDepots is EMPTY on Linux (ACCELA line 770)
    - Adds platform_override for Windows depots on Linux
    - Calls chmod on Linux binaries
    - Triggers Steam restart

    If target_library_path is given, the ACF is written to that library's steamapps/.
    """
    steam_path = detect_steam_install_path() or "/home/deck/.local/share/Steam"
    library_base = target_library_path if target_library_path and os.path.isdir(target_library_path) else steam_path
    acf_path = os.path.join(library_base, "steamapps", f"appmanifest_{appid}.acf")

    # Derive installdir from actual download directory basename
    install_folder_name = os.path.basename(install_dir.rstrip("/\\"))
    if not install_folder_name:
        install_folder_name = f"app_{appid}"

    # Resolve game name: param > existing ACF > fallback
    if not game_name and os.path.exists(acf_path):
        try:
            with open(acf_path, "r", encoding="utf-8") as f:
                old = f.read()
            m = re.search(r'"name"\s+"([^"]+)"', old)
            if m:
                game_name = m.group(1)
        except Exception:
            pass
    if not game_name:
        game_name = install_folder_name

    size_on_disk = _get_dir_size(install_dir)

    # Fetch real buildid from SteamCMD API so Steam doesn't show "Update" button.
    # buildid=0 causes Steam to detect a version mismatch and set StateFlags 6.
    buildid = "0"
    try:
        import httpx
        resp = httpx.get(f"https://api.steamcmd.net/v1/info/{appid}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                bid = data.get("data", {}).get(str(appid), {}).get("depots", {}).get("branches", {}).get("public", {}).get("buildid")
                if bid:
                    buildid = str(bid)
                    logger.info(f"DeckTools: Fetched buildid {buildid} for {appid}")
    except Exception as exc:
        logger.warning(f"DeckTools: Failed to fetch buildid for {appid}: {exc}")

    # InstalledDepots — populate with real depot/manifest data.
    # Empty causes UpdateResult 8 ("content still encrypted").
    # Steam rewriting StateFlags to 6 is blocked by making the ACF read-only.
    depot_entries = ""
    for d in depots:
        depot_id = d.get("depot", "")
        manifest_id = d.get("manifest", "")
        size = d.get("size", 0)
        if depot_id and manifest_id:
            depot_entries += (
                f'\t\t"{depot_id}"\n'
                f'\t\t{{\n'
                f'\t\t\t"manifest"\t\t"{manifest_id}"\n'
                f'\t\t\t"size"\t\t"{size}"\n'
                f'\t\t}}\n'
            )
    installed_depots_str = f'\t"InstalledDepots"\n\t{{\n{depot_entries}\t}}'

    # Platform config — detect if game has Windows .exe files (needs Proton override).
    # DDM places files in subdirs like "GameName_windows/", so we walk recursively.
    has_exe = False
    has_linux_binary = False
    if os.path.isdir(install_dir):
        for _root, _dirs, files in os.walk(install_dir):
            for fname in files:
                fl = fname.lower()
                if fl.endswith(".exe"):
                    has_exe = True
                if fl.endswith(".sh") or fl.endswith(".x86_64") or fl.endswith(".x86"):
                    has_linux_binary = True
            if has_exe or has_linux_binary:
                break  # found enough, stop early

    if has_exe and not has_linux_binary:
        # Windows game on Linux — needs Proton (like ACCELA line 719-730)
        platform_config = (
            '\t"UserConfig"\n'
            '\t{\n'
            '\t\t"platform_override_dest"\t\t"linux"\n'
            '\t\t"platform_override_source"\t\t"windows"\n'
            '\t}\n'
            '\t"MountedConfig"\n'
            '\t{\n'
            '\t\t"platform_override_dest"\t\t"linux"\n'
            '\t\t"platform_override_source"\t\t"windows"\n'
            '\t}'
        )
    else:
        # Native Linux or unknown — empty config (ACCELA line 733/738)
        platform_config = '\t"UserConfig"\n\t{\n\t}\n\t"MountedConfig"\n\t{\n\t}'

    acf_content = (
        '"AppState"\n'
        "{\n"
        f'\t"appid"\t\t"{appid}"\n'
        f'\t"Universe"\t\t"1"\n'
        f'\t"name"\t\t"{game_name}"\n'
        f'\t"StateFlags"\t\t"4"\n'
        f'\t"installdir"\t\t"{install_folder_name}"\n'
        f'\t"SizeOnDisk"\t\t"{size_on_disk}"\n'
        f'\t"buildid"\t\t"{buildid}"\n'
        f"{installed_depots_str}\n"
        f"{platform_config}\n"
        "}"
    )

    try:
        os.makedirs(os.path.dirname(acf_path), exist_ok=True)
        tmp_path = acf_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(acf_content)
        os.replace(tmp_path, acf_path)
        try:
            import subprocess
            subprocess.run(["chown", "deck:deck", acf_path], timeout=10, capture_output=True)
            # Make read-only so Steam cannot rewrite StateFlags/UpdateResult
            os.chmod(acf_path, 0o444)
        except Exception:
            pass
        logger.info(
            f"DeckTools: Created appmanifest {acf_path}: "
            f"installdir={install_folder_name}, StateFlags=4, "
            f"SizeOnDisk={size_on_disk}, platform={'windows_override' if has_exe and not has_linux_binary else 'native'}"
        )
    except Exception as e:
        logger.error(f"DeckTools: Failed to write appmanifest: {e}")

    # Set executable permissions for Linux binaries (like ACCELA's _set_linux_binary_permissions)
    _chmod_linux_binaries(install_dir)


async def repair_appmanifest(appid: int) -> dict:
    """Repair a broken appmanifest ACF for an existing game (without re-downloading).

    This mirrors what ACCELA does: create a correct ACF from scratch,
    set Linux binary permissions, and restart Steam.
    """
    from steam_utils import get_steam_libraries
    libraries = get_steam_libraries()
    
    install_dir = ""
    game_name = ""
    found_lib_path = ""

    api_installdir = await _fetch_installdir_from_api(appid)
    try:
        fetched_name = await fetch_app_name(appid)
    except Exception:
        fetched_name = ""

    main_steam_path = detect_steam_install_path() or "/home/deck/.local/share/Steam"
    if not libraries:
        libraries = [{"path": main_steam_path}]

    for lib in libraries:
        lib_path = lib.get("path", "") if isinstance(lib, dict) else str(lib)
        if not lib_path or not os.path.exists(lib_path):
            continue

        common_path = os.path.join(lib_path, "steamapps", "common")
        acf_path = os.path.join(lib_path, "steamapps", f"appmanifest_{appid}.acf")

        if api_installdir and not install_dir:
            candidate = os.path.join(common_path, api_installdir)
            if os.path.exists(candidate):
                install_dir = candidate
                found_lib_path = lib_path
                logger.info(f"DeckTools: repair - found dir via API: {install_dir}")

        if os.path.exists(acf_path) and not install_dir:
            try:
                import re
                with open(acf_path, "r", encoding="utf-8") as f:
                    content = f.read()
                m_name = re.search(r'"name"\s+"([^"]+)"', content)
                if m_name:
                    game_name = m_name.group(1)
                m_dir = re.search(r'"installdir"\s+"([^"]+)"', content)
                if m_dir:
                    candidate = os.path.join(common_path, m_dir.group(1))
                    if os.path.exists(candidate):
                        install_dir = candidate
                        found_lib_path = lib_path
                        logger.info(f"DeckTools: repair - found dir via ACF: {install_dir}")
            except Exception:
                pass

        if not install_dir and fetched_name and os.path.exists(common_path):
            name_lower = fetched_name.lower().strip()
            for d in os.listdir(common_path):
                if d.lower().startswith(name_lower[:15]) or name_lower.startswith(d.lower()[:15]):
                    candidate = os.path.join(common_path, d)
                    if os.path.exists(candidate):
                        install_dir = candidate
                        found_lib_path = lib_path
                        logger.info(f"DeckTools: repair - found dir via scanning: {install_dir}")
                        break

        if install_dir:
            break

    if not install_dir:
        return {"success": False, "error": f"Game directory not found for AppID {appid} in any library"}

    if not game_name:
        game_name = fetched_name or os.path.basename(install_dir)

    lua_path = os.path.join(main_steam_path, "config", "stplug-in", f"{appid}.lua")
    depots = []
    if os.path.exists(lua_path):
        depots = _parse_lua_depots(lua_path)

    # ACCELA original logic creates appmanifest
    _create_or_update_appmanifest(
        appid,
        install_dir,
        depots,
        game_name,
        target_library_path=found_lib_path
    )

    return {
        "success": True,
        "installdir": os.path.basename(install_dir),
        "game_name": game_name,
        "message": "Appmanifest repaired.",
    }


# ---------------------------------------------------------------------------
# Main download flow (async)
# ---------------------------------------------------------------------------

async def _download_zip_for_app(appid: int, target_library_path: str = "") -> None:
    """Download manifest zip from enabled APIs and install."""
    client = await ensure_http_client("download")
    apis = load_api_manifest()
    if not apis:
        _set_download_state(appid, {"status": "failed", "error": "No APIs available"})
        return

    dest_root = ensure_temp_download_dir()
    dest_path = os.path.join(dest_root, f"{appid}.zip")
    _set_download_state(appid, {
        "status": "checking", "currentApi": None,
        "bytesRead": 0, "totalBytes": 0, "dest": dest_path,
    })

    for api in apis:
        name = api.get("name", "Unknown")
        template = api.get("url", "")
        success_code = int(api.get("success_code", 200))
        unavailable_code = int(api.get("unavailable_code", 404))
        url = template.replace("<appid>", str(appid))
        _set_download_state(appid, {
            "status": "checking", "currentApi": name,
            "bytesRead": 0, "totalBytes": 0,
        })
        logger.info(f"DeckTools: Trying API '{name}' -> {url}")

        try:
            headers = {"User-Agent": USER_AGENT}

            # Ryuu cookie injection
            if "ryuu.lol" in url:
                cookie_content = load_ryu_cookie()
                if cookie_content:
                    headers["Cookie"] = cookie_content
                    headers["Referer"] = "https://generator.ryuu.lol/"
                    headers["Authority"] = "generator.ryuu.lol"
                    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                    headers["Upgrade-Insecure-Requests"] = "1"
                    headers["Sec-Fetch-Dest"] = "document"
                    headers["Sec-Fetch-Mode"] = "navigate"
                    headers["Sec-Fetch-Site"] = "same-origin"
                else:
                    logger.warning("DeckTools: Ryuu API detected but ryuu_cookie.txt not found or empty!")

            if _is_download_cancelled(appid):
                return

            async with client.stream("GET", url, headers=headers, follow_redirects=True, timeout=30) as resp:
                code = resp.status_code
                logger.info(f"DeckTools: API '{name}' status={code}")
                if code == unavailable_code:
                    continue
                if code != success_code:
                    if "ryuu.lol" in url and code in (401, 403):
                        logger.warning(f"DeckTools: Ryuu access denied ({code}). Check if cookie expired.")
                    continue

                total = int(resp.headers.get("Content-Length", "0") or "0")
                _set_download_state(appid, {"status": "downloading", "bytesRead": 0, "totalBytes": total, "downloadStartTime": time.time()})

                with open(dest_path, "wb") as output:
                    async for chunk in resp.aiter_bytes():
                        if not chunk:
                            continue
                        if _is_download_cancelled(appid):
                            raise RuntimeError("cancelled")
                        output.write(chunk)
                        read = int(_get_download_state(appid).get("bytesRead", 0)) + len(chunk)
                        elapsed = time.time() - _get_download_state(appid).get("downloadStartTime", time.time())
                        speed = int(read / elapsed) if elapsed > 0.5 else 0
                        _set_download_state(appid, {"bytesRead": read, "speed": speed})

                if _is_download_cancelled(appid):
                    raise RuntimeError("cancelled")

                # Validate ZIP magic + Ryuu login detection
                try:
                    with open(dest_path, "rb") as fh:
                        magic = fh.read(4)
                        if magic not in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
                            file_size = os.path.getsize(dest_path)
                            with open(dest_path, "rb") as check_f:
                                preview = check_f.read(512)
                                content_preview = preview[:100].decode("utf-8", errors="ignore")
                            logger.warning(
                                f"DeckTools: API '{name}' returned non-zip (magic={magic.hex()}, size={file_size}, preview={content_preview[:50]})"
                            )
                            if "Login required" in content_preview or "Sign in" in content_preview:
                                logger.error("DeckTools: Ryuu site asked for login. Cookie is invalid or expired.")
                            try:
                                os.remove(dest_path)
                            except Exception:
                                pass
                            continue
                except FileNotFoundError:
                    continue

                # Process and install
                try:
                    if _is_download_cancelled(appid):
                        raise RuntimeError("cancelled")
                    _set_download_state(appid, {"status": "processing"})
                    await _process_and_install_lua(appid, dest_path)

                    if _is_download_cancelled(appid):
                        raise RuntimeError("cancelled")

                    try:
                        fetched_name = await fetch_app_name(appid) or f"Unknown ({appid})"
                        _append_loaded_app(appid, fetched_name)
                        _log_appid_event(f"ADDED - {name}", appid, fetched_name)
                    except Exception:
                        pass

                    # Auto-configure SLSsteam so the game appears in Steam library
                    _set_download_state(appid, {"status": "configuring"})
                    try:
                        from slssteam_ops import add_game_token, add_game_dlcs, add_to_additional_apps, write_depot_decryption_keys
                        r0 = add_to_additional_apps(appid)
                        logger.info(f"DeckTools: SLSsteam add_to_additional_apps({appid}): {r0}")
                        r2 = add_game_token(appid)
                        logger.info(f"DeckTools: SLSsteam add_game_token({appid}): {r2}")

                        # Write DecryptionKey entries from the installed lua into config.vdf
                        # so Steam can decrypt the depot without needing SLSsteam injected
                        try:
                            lua_path_now = _get_download_state(appid).get("installedPath", "")
                            if not lua_path_now:
                                _steam_base = detect_steam_install_path()
                                lua_path_now = os.path.join(_steam_base or "", "config", "stplug-in", f"{appid}.lua")
                            if os.path.exists(lua_path_now):
                                import re as _re
                                with open(lua_path_now, "r", encoding="utf-8") as _lf:
                                    _lua = _lf.read()
                                _depot_keys = {}
                                for _m in _re.finditer(r'addappid\(\s*(\d+)\s*,\s*\d+\s*,\s*"([0-9a-fA-F]{64})"', _lua):
                                    _depot_keys[_m.group(1)] = _m.group(2)
                                if _depot_keys:
                                    _dk_result = write_depot_decryption_keys(_depot_keys)
                                    logger.info(f"DeckTools: write_depot_decryption_keys: {_dk_result}")
                        except Exception as _dk_exc:
                            logger.warning(f"DeckTools: DecryptionKey write failed: {_dk_exc}")

                        r3 = await add_game_dlcs(appid)
                        logger.info(f"DeckTools: SLSsteam add_game_dlcs({appid}): {r3}")
                    except Exception as sls_exc:
                        logger.warning(f"DeckTools: SLSsteam config partial: {sls_exc}")

                    # Download actual game files via DepotDownloader
                    if _is_download_cancelled(appid):
                        raise RuntimeError("cancelled")

                    _set_download_state(appid, {"status": "depot_download", "depotProgress": "Preparing..."})
                    try:
                        lua_path = _get_download_state(appid).get("installedPath", "")
                        if not lua_path:
                            steam_base = detect_steam_install_path()
                            lua_path = os.path.join(steam_base or "", "config", "stplug-in", f"{appid}.lua")

                        depots = _parse_lua_depots(lua_path) if os.path.exists(lua_path) else []
                        if depots:
                            install_dir = await _determine_install_dir(appid, fetched_name, target_library_path)
                            logger.info(f"DeckTools: Starting depot download - {len(depots)} depot(s) -> {install_dir}")
                            await _run_depot_download(appid, depots, install_dir)

                            if _is_download_cancelled(appid):
                                raise RuntimeError("cancelled")

                            # Check if depot download failed
                            cur_state = _get_download_state(appid)
                            if cur_state.get("status") == "failed":
                                return

                            # Create/overwrite appmanifest so Steam recognizes the game as installed
                            try:
                                _create_or_update_appmanifest(appid, install_dir, depots, fetched_name, target_library_path)
                            except Exception as acf_exc:
                                logger.warning(f"DeckTools: appmanifest update error: {acf_exc}")

                            # If no Linux depot was available, force Proton so Steam
                            # doesn't refuse to launch the Windows executable
                            if not _get_download_state(appid).get("hasLinuxDepot", False):
                                try:
                                    from steam_utils import set_compat_tool_for_app
                                    if set_compat_tool_for_app(appid):
                                        logger.info(f"DeckTools: Forced proton_experimental for {appid} (Windows-only depot)")
                                    else:
                                        logger.warning(f"DeckTools: Could not set compat tool for {appid}")
                                except Exception as proton_exc:
                                    logger.warning(f"DeckTools: set_compat_tool error: {proton_exc}")

                            # Re-verify SLSsteam config after all game files are in place.
                            # Avoids the race condition where Steam restarts before SLSsteam
                            # has processed the lua, causing the game to fail to launch.
                            try:
                                from slssteam_ops import reconfigure_slssteam
                                await reconfigure_slssteam(appid)
                                logger.info(f"DeckTools: SLSsteam config re-verified for {appid}")
                            except Exception as reconf_exc:
                                logger.warning(f"DeckTools: SLSsteam re-verify failed: {reconf_exc}")
                        else:
                            logger.info(f"DeckTools: No depots found in lua for {appid}, skipping game file download")
                    except RuntimeError:
                        raise
                    except Exception as depot_exc:
                        logger.warning(f"DeckTools: Depot download error: {depot_exc}")
                        _set_download_state(appid, {"status": "failed", "error": f"Game download failed: {depot_exc}"})
                        return

                    # Save depot snapshot for update checking.
                    # Use exact manifest IDs from the API response (what DDM was told to download).
                    # Scanning depotcache with a numeric tiebreak is unreliable because Steam
                    # manifest GIDs are content hashes, not sequential version numbers.
                    try:
                        from api_manifest import _depot_snapshot_path
                        snap_manifests = {str(d["depot"]): str(d["manifest"]) for d in depots if d.get("manifest")}
                        if snap_manifests:
                            import json as _json
                            snap_path = _depot_snapshot_path(appid)
                            with open(snap_path, "w", encoding="utf-8") as _sf:
                                _json.dump({"appid": appid, "manifests": snap_manifests}, _sf)
                            logger.info(f"DeckTools: Saved depot snapshot for {appid} ({len(snap_manifests)} depots)")
                    except Exception as snap_exc:
                        logger.warning(f"DeckTools: depot snapshot save error: {snap_exc}")

                    _set_download_state(appid, {"status": "done", "success": True, "api": name})
                    return
                except Exception as install_exc:
                    if isinstance(install_exc, RuntimeError) and str(install_exc) == "cancelled":
                        try:
                            if os.path.exists(dest_path):
                                os.remove(dest_path)
                        except Exception:
                            pass
                        return
                    logger.warning(f"DeckTools: Processing failed -> {install_exc}")
                    _set_download_state(appid, {"status": "failed", "error": f"Processing failed: {install_exc}"})
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                    return

        except RuntimeError as cancel_exc:
            if str(cancel_exc) == "cancelled":
                try:
                    if os.path.exists(dest_path):
                        os.remove(dest_path)
                except Exception:
                    pass
                return
            _set_download_state(appid, {"status": "failed", "error": str(cancel_exc)})
            return
        except Exception as err:
            logger.warning(f"DeckTools: API '{name}' failed: {err}")
            continue

    _set_download_state(appid, {"status": "failed", "error": "Not available on any API"})


async def start_download(appid: int, target_library_path: str = "") -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    logger.info(f"DeckTools: start_download appid={appid} library={target_library_path or '(default)'}")
    _set_download_state(appid, {"status": "queued", "bytesRead": 0, "totalBytes": 0})
    task = asyncio.create_task(_download_zip_for_app(appid, target_library_path))
    DOWNLOAD_TASKS[appid] = task
    return {"success": True}


def get_download_status(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    return {"success": True, "state": _get_download_state(appid)}


def get_active_downloads() -> dict:
    """Return all downloads that are still in progress (not terminal)."""
    active = {}
    terminal = {"done", "failed", "cancelled"}
    for appid, state in DOWNLOAD_STATE.items():
        status = state.get("status")
        if status and status not in terminal:
            active[str(appid)] = state.copy()
    return {"success": True, "downloads": active}


def cancel_download(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    state = _get_download_state(appid)
    if not state or state.get("status") in {"done", "failed"}:
        return {"success": True, "message": "Nothing to cancel"}

    _set_download_state(appid, {"status": "cancelled", "error": "Cancelled by user"})
    task = DOWNLOAD_TASKS.get(appid)
    if task and not task.done():
        task.cancel()
    return {"success": True}


def has_luatools_for_app(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    return {"success": True, "exists": has_lua_for_app(appid)}


def delete_luatools_for_app(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    base = detect_steam_install_path()
    target_dir = os.path.join(base or "", "config", "stplug-in")
    paths_to_check = [
        os.path.join(target_dir, f"{appid}.lua"),
        os.path.join(target_dir, f"{appid}.lua.disabled"),
    ]
    deleted = []
    for path in paths_to_check:
        try:
            if os.path.exists(path):
                os.remove(path)
                deleted.append(path)
        except Exception as exc:
            logger.warning(f"DeckTools: Failed to delete {path}: {exc}")
    try:
        name = _get_loaded_app_name(appid) or f"Unknown ({appid})"
        _remove_loaded_app(appid)
        if deleted:
            _log_appid_event("REMOVED", appid, name)
    except Exception:
        pass
    return {"success": True, "deleted": deleted, "count": len(deleted)}


def get_installed_lua_scripts() -> dict:
    """Get list of all installed Lua scripts from stplug-in directory."""
    try:
        _preload_app_names_cache()
        base_path = detect_steam_install_path()
        if not base_path:
            return {"success": False, "error": "Could not find Steam installation path"}

        target_dir = os.path.join(base_path, "config", "stplug-in")
        if not os.path.exists(target_dir):
            return {"success": True, "scripts": []}

        installed_scripts = []
        for filename in os.listdir(target_dir):
            if filename.endswith(".lua") or filename.endswith(".lua.disabled"):
                try:
                    appid_str = filename.replace(".lua.disabled", "").replace(".lua", "")
                    appid = int(appid_str)
                    is_disabled = filename.endswith(".lua.disabled")

                    game_name = APP_NAME_CACHE.get(appid, "")
                    if not game_name:
                        game_name = _get_loaded_app_name(appid)
                    if not game_name:
                        game_name = f"Unknown Game ({appid})"

                    file_path = os.path.join(target_dir, filename)
                    file_stat = os.stat(file_path)

                    import datetime
                    modified_time = datetime.datetime.fromtimestamp(file_stat.st_mtime)

                    installed_scripts.append({
                        "appid": appid,
                        "gameName": game_name,
                        "filename": filename,
                        "isDisabled": is_disabled,
                        "fileSize": file_stat.st_size,
                        "modifiedDate": modified_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "path": file_path,
                        "hasGameFiles": os.path.exists(
                            os.path.join(base_path, "steamapps", f"appmanifest_{appid}.acf")
                        ),
                    })
                except ValueError:
                    continue
                except Exception:
                    continue

        installed_scripts.sort(key=lambda x: x["appid"])
        return {"success": True, "scripts": installed_scripts}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def read_loaded_apps() -> dict:
    try:
        path = _loaded_apps_path()
        entries = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle.read().splitlines():
                    if ":" in line:
                        appid_str, name = line.split(":", 1)
                        appid_str = appid_str.strip()
                        name = name.strip()
                        if appid_str.isdigit() and name:
                            entries.append({"appid": int(appid_str), "name": name})
        return {"success": True, "apps": entries}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def dismiss_loaded_apps() -> dict:
    """Delete the loadedappids.txt file."""
    try:
        path = _loaded_apps_path()
        if os.path.exists(path):
            os.remove(path)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def save_launcher_path_config(path: str) -> dict:
    try:
        path_file = data_path("launcher_path.txt")
        clean_path = path.strip()
        with open(path_file, "w", encoding="utf-8") as f:
            f.write(clean_path)
        return {"success": True, "path": clean_path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def load_launcher_path() -> str:
    """Public accessor for the launcher path."""
    return _load_launcher_path()

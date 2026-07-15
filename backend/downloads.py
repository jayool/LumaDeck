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
from paths import backend_path
from steam_utils import detect_steam_install_path, has_lua_for_app
from utils import ensure_temp_download_dir

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

DOWNLOAD_STATE: Dict[int, Dict[str, Any]] = {}
DOWNLOAD_TASKS: Dict[int, asyncio.Task] = {}

# Fire-and-forget background tasks (e.g. the delayed Steam restart). Keep a
# strong reference so the event loop doesn't garbage-collect them mid-flight —
# asyncio only holds a weak reference to tasks created via create_task().
_BACKGROUND_TASKS: set = set()

# Cache for app names
APP_NAME_CACHE: Dict[int, str] = {}


# ---------------------------------------------------------------------------
# lumalinux backend integration
# ---------------------------------------------------------------------------
#
# LumaDeck replaces the DDL-based install flow with a delegation to
# tools/steamidra_lite.py from the jayool/lumalinux project. The script does
# everything DDL used to do plus the SLSsteam config edits the plugin used to
# do separately (config.yaml AdditionalApps, depot keys into config.vdf, .acf
# stub, ACCELA markers, etc.). After invoking it we just shut Steam down so
# SteamOS Game Mode auto-relaunches it with the hooks reading the fresh
# config — Steam itself handles the actual game download natively.
#
# The helper below resolves the script path. steamidra_lite runs on SteamOS'
# system python3: lumalinux commit b2d3d11 dropped the 'vdf' module dependency
# (the script does inline VDF text editing now), so the user-created venv that
# used to be required (to get 'vdf' past SteamOS' PEP 668) is no longer needed.
# Pin the absolute /usr/bin/python3 (always present on SteamOS) so we don't
# depend on PATH, falling back to the bare name elsewhere.
_LUMALINUX_PYTHON = "/usr/bin/python3" if os.path.isfile("/usr/bin/python3") else "python3"


def _find_steamidra_lite_script() -> str:
    """Locate tools/steamidra_lite.py from the deployed lumalinux directory.
    Returns the path, or "" if lumalinux isn't installed."""
    from paths import get_steamidra_lite_script
    return get_steamidra_lite_script() or ""


_STEAMIDRA_SUPPORTS_NAME: bool | None = None


async def _steamidra_supports_name(python: str, script: str) -> bool:
    """Whether the DEPLOYED steamidra_lite.py accepts --name. Older lumalinux
    builds don't, and argparse errors out (exit 2) on an unknown flag — which
    would break the install. Probed once via --help and cached for the session."""
    global _STEAMIDRA_SUPPORTS_NAME
    if _STEAMIDRA_SUPPORTS_NAME is None:
        try:
            proc = await asyncio.create_subprocess_exec(
                python, script, "--help",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            _STEAMIDRA_SUPPORTS_NAME = b"--name" in (out or b"")
        except Exception:
            _STEAMIDRA_SUPPORTS_NAME = False
    return _STEAMIDRA_SUPPORTS_NAME


async def _invoke_steamidra_lite(
    input_path: str, manifests_dir: str = "", appid_for_log: int = 0,
    game_name: str = "",
) -> tuple[bool, str]:
    """Run steamidra_lite.py on `input_path` (a Hubcap zip, or — when
    `manifests_dir` is supplied — a bare .lua file alongside an extracted
    manifest directory). Returns (success, combined_stdout_stderr).

    Combined stream so the user gets the script's progress narrative in one
    block if it fails. We stream the script's output through the plugin's
    DOWNLOAD_STATE if `appid_for_log` is set so the frontend can show the
    current step while the script is running."""
    script = _find_steamidra_lite_script()
    if not script:
        return False, (
            "lumalinux not installed (steamidra_lite.py not found). "
            "Install lumalinux first."
        )
    python = _LUMALINUX_PYTHON

    cmd = [python, script, input_path]
    if manifests_dir:
        cmd.extend(["--manifests-dir", manifests_dir])
    # Pass the canonical name so steamidra writes it as the .acf installdir
    # instead of falling back to the appid (which makes Steam re-download the
    # whole game if the .acf is later regenerated — e.g. by Repair appmanifest).
    # Gated on the deployed steamidra supporting --name (older lumalinux would
    # argparse-error on it and fail the install).
    if game_name and await _steamidra_supports_name(python, script):
        cmd.extend(["--name", game_name])

    logger.info(f"LumaDeck: invoking steamidra_lite: {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        return False, f"Could not start steamidra_lite: {exc}"

    output_chunks: list[str] = []
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").rstrip()
        output_chunks.append(text)
        logger.info(f"steamidra_lite[{appid_for_log}]: {text}")
        if appid_for_log:
            _set_download_state(appid_for_log, {"steamidraStep": text})

    await proc.wait()
    output = "\n".join(output_chunks)
    return proc.returncode == 0, output


# ---------------------------------------------------------------------------
# Per-game pin / unpin (auto-update toggle)
# ---------------------------------------------------------------------------
#
# steamidra_lite's zip-less modes (--pin-installed / --unpin / --pin-status) do
# the keys.txt surgery; LumaDeck just shells out to them. The change takes effect
# on the next Steam restart — we do NOT force one (a toggle inside Game Mode
# shouldn't kill Steam); the UI tells the user it applies on restart.


async def _run_steamidra_mode(mode_args: list[str]) -> tuple[bool, str]:
    """Run steamidra_lite in a zip-less mode (just flags, no input zip)."""
    script = _find_steamidra_lite_script()
    if not script:
        return False, "lumalinux not installed (steamidra_lite.py not found)."
    python = _LUMALINUX_PYTHON
    cmd = [python, script, *mode_args]
    logger.info(f"LumaDeck: invoking steamidra_lite: {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        return False, f"Could not start steamidra_lite: {exc}"
    raw, _ = await proc.communicate()
    return proc.returncode == 0, raw.decode("utf-8", errors="replace").strip()


async def pin_game(appid: int) -> dict:
    """Freeze a game at its installed version (steamidra_lite --pin-installed)."""
    ok, out = await _run_steamidra_mode(["--pin-installed", str(int(appid))])
    if not ok:
        return {"success": False, "error": out or "pin failed"}
    return {"success": True, "pinned": True}


async def unpin_game(appid: int) -> dict:
    """Return a game to auto-update (steamidra_lite --unpin)."""
    ok, out = await _run_steamidra_mode(["--unpin", str(int(appid))])
    if not ok:
        return {"success": False, "error": out or "unpin failed"}
    return {"success": True, "pinned": False}


async def get_pin_status(appid: int) -> dict:
    """Return {"success", "pinned", "depots"} (steamidra_lite --pin-status)."""
    ok, out = await _run_steamidra_mode(["--pin-status", str(int(appid))])
    if not ok:
        return {"success": False, "error": out or "status failed", "pinned": False}
    try:
        line = out.splitlines()[-1] if out else "{}"
        data = json.loads(line)
        return {
            "success": True,
            "pinned": bool(data.get("pinned")),
            "depots": data.get("depots", {}),
        }
    except Exception:
        return {"success": False, "error": f"could not parse: {out}", "pinned": False}


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

        # --- ProtonDB compatibility tier (best-effort; never blocks notices) ---
        info["protondb"] = None
        try:
            pdb_url = f"https://www.protondb.com/api/v1/reports/summaries/{appid}.json"
            pdb_resp = await client.get(pdb_url, follow_redirects=True, timeout=4)
            if pdb_resp.status_code == 200:
                tier = (pdb_resp.json() or {}).get("tier")
                if tier and tier not in ("pending",):
                    info["protondb"] = tier
        except Exception:
            pass

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
        logger.warning(f"LumaDeck: _append_loaded_app failed for {appid}: {exc}")


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
        logger.warning(f"LumaDeck: Failed to download Games DB: {exc}")
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
                    f"LumaDeck: Linux depot {linux_depot_id} found for {appid} "
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
            logger.info(f"LumaDeck: Added Linux depot {linux_depot_id} (manifest in depotcache) for {appid}")
            return lua_text, True

        except Exception as exc:
            logger.warning(f"LumaDeck: Failed to enrich lua with Linux depot: {exc}")
            return lua_text, False

    except Exception as exc:
        logger.warning(f"LumaDeck: Error in _enrich_lua_with_linux_depot: {exc}")
        return lua_text, False


def _count_app_depot_keys(appid: int) -> int:
    """Count usable Extended depot-key entries in lumalinux's keys.txt whose
    parent_app_id == appid — i.e. content depots for which steamidra_lite wrote
    a real 32-byte (64-hex) decryption key for this app.

    Used as a post-install sanity check: steamidra_lite can exit 0 yet parse
    nothing usable out of a .lua that isn't in the Hubcap dialect (a non-Hubcap
    endpoint may ship a zip whose .lua uses a different format / quote style, or
    differently named manifests). Without a usable key the install is a
    "phantom" — Steam shows the game as owned but it never downloads / can't
    decrypt.

    Returns the count (>= 0), or -1 if keys.txt could not be read (so the
    caller can skip the guard instead of false-failing on our own read error).
    """
    keys_path = os.path.expanduser("~/.config/lumalinux/keys.txt")
    if not os.path.exists(keys_path):
        return 0
    target = str(appid)
    count = 0
    try:
        with open(keys_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Extended: depot_id;parent_app_id;manifest_gid;manifest_size;hex_key
                parts = line.split(";")
                if len(parts) == 5 and parts[1].strip() == target:
                    key = parts[4].strip()
                    if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
                        count += 1
    except Exception as exc:
        logger.warning(f"LumaDeck: keys.txt post-check read error: {exc}")
        return -1
    return count


async def _process_and_install_lua(appid: int, zip_path: str) -> None:
    """Process the downloaded Hubcap zip via lumalinux's steamidra_lite.

    Approach (LumaDeck flow):
      1. Extract the zip to a temp directory.
      2. Locate the <appid>.lua and (optionally) enrich it with the Linux
         depot — done in the plugin because steamidra_lite doesn't query
         PICS. The enrichment runs ONLY if the corresponding .manifest is
         already in the extracted tree (no point adding a depot we can't
         decrypt).
      3. Invoke steamidra_lite with the (possibly enriched) .lua and the
         directory of extracted manifests. The script writes:
           - manifests into depotcache + config/depotcache
           - keys.txt for lumalinux
           - DecryptionKey entries into config.vdf
           - AdditionalApps entry in SLSsteam config.yaml
           - clean .acf stub
           - .lua copied to stplug-in (interop with the rest of the ecosystem)
           - ACCELA / ASSella markers (.DepotDownloader/, <accela>/depots/*.depot)
      4. Steam itself does the actual download once Game Mode relaunches it
         (handled outside this function, in _download_zip_for_app).

    Notes:
      - This runs steamidra_lite in its default NO-PIN mode (no --pin flag): it
        writes manifest_gid=0 to keys.txt and comments out the setManifestid
        lines, so Steam pulls the latest manifest and the game auto-updates. The
        depot AES keys are version-independent, so the download still decrypts.
        Version pinning is opt-in per game (pin_game -> --pin-installed) and is
        currently a no-op at the lumalinux layer: SLSsteam 20260714 owns
        BuildDepotDependency, so lumalinux's BuildDep hook is disabled. Re-homing
        the pin onto SLSsteam's ManifestIds is tracked separately.
      - No ACCELA launcher integration. If the user wants ACCELA to handle
        the zip instead, they can run it manually from Desktop Mode.
    """
    import zipfile
    import shutil as _shutil
    import tempfile

    if _is_download_cancelled(appid):
        raise RuntimeError("cancelled")

    base_path = detect_steam_install_path()
    if not base_path:
        raise RuntimeError("Steam install path not found")

    tmp_dir = tempfile.mkdtemp(prefix=f"lumadeck_{appid}_")
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(tmp_dir)

        if _is_download_cancelled(appid):
            raise RuntimeError("cancelled")

        # Locate the .lua. Prefer <appid>.lua, fall back to any numeric .lua
        # file found anywhere in the extracted tree.
        from pathlib import Path
        lua_candidates = [
            p for p in Path(tmp_dir).rglob("*.lua")
            if re.fullmatch(r"\d+", p.stem)
        ]
        if not lua_candidates:
            raise RuntimeError("No numeric .lua file found in zip")
        preferred = next(
            (p for p in lua_candidates if p.stem == str(appid)),
            lua_candidates[0],
        )
        lua_path = preferred

        # Optional enrichment with Linux depot (consults PICS via
        # api.steamcmd.net). Updates the file in-place if it adds anything.
        try:
            lua_text = lua_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            lua_text = lua_path.read_bytes().decode("utf-8", errors="replace")
        enriched_text, has_linux_depot = await _enrich_lua_with_linux_depot(
            appid, lua_text,
        )
        if enriched_text != lua_text:
            lua_path.write_text(enriched_text, encoding="utf-8")
        _set_download_state(appid, {"hasLinuxDepot": has_linux_depot})

        if _is_download_cancelled(appid):
            raise RuntimeError("cancelled")

        # Pick the directory that holds the manifest files (usually the
        # same dir as the lua, but ZIPs sometimes ship them in a subfolder).
        manifests_dir = lua_path.parent
        if not any(p.suffix.lower() == ".manifest" for p in manifests_dir.iterdir()):
            for cand in Path(tmp_dir).rglob("*.manifest"):
                manifests_dir = cand.parent
                break

        # Run steamidra_lite. It handles everything: depotcache,
        # keys.txt, config.vdf, config.yaml, .acf stub, stplug-in lua,
        # ACCELA markers, .depot tracker.
        _set_download_state(appid, {"status": "installing"})
        # Resolve the canonical name (local applist cache first, store API
        # fallback) so steamidra writes it as the .acf installdir. Empty on a
        # miss — steamidra then does its own lookup / appid fallback.
        game_name = await fetch_app_name(appid)
        ok, output = await _invoke_steamidra_lite(
            str(lua_path),
            manifests_dir=str(manifests_dir),
            appid_for_log=appid,
            game_name=game_name or "",
        )
        if not ok:
            raise RuntimeError(
                f"steamidra_lite failed:\n{output[-2000:]}"  # last 2KB is plenty
            )

        # Post-condition guard against a "phantom install". steamidra_lite is
        # built for the Hubcap zip dialect; a non-Hubcap endpoint can ship a
        # zip whose .lua parses to nothing usable (different format / quotes,
        # or oddly named manifests). The exit code is still 0, but keys.txt got
        # no decryption key — so Steam would relaunch, show the game as owned,
        # and never actually download / fail to decrypt. If the zip carried
        # manifests (there IS content that needs keys) but no usable key landed
        # for this app, fail loudly here instead of restarting Steam into a
        # broken state.
        manifest_count = sum(1 for _ in Path(tmp_dir).rglob("*.manifest"))
        if manifest_count > 0:
            key_count = _count_app_depot_keys(appid)
            if key_count == 0:
                raise RuntimeError(
                    f"Install aborted: the download succeeded but no usable depot "
                    f"key was written for app {appid}, despite the zip carrying "
                    f"{manifest_count} manifest(s). The endpoint's zip format is "
                    f"likely incompatible with the Hubcap-style processing "
                    f"(non-Hubcap source?). Steam was NOT restarted; if the game "
                    f"shows up in your library, remove it and retry with the "
                    f"official Hubcap source."
                )
            if key_count < 0:
                logger.warning(
                    f"LumaDeck: keys.txt post-check skipped for app {appid} "
                    f"(couldn't read keys.txt) — proceeding"
                )
            else:
                logger.info(
                    f"LumaDeck: post-check OK — {key_count} depot key(s) in "
                    f"keys.txt for app {appid} ({manifest_count} manifest(s))"
                )

        # Record the installed lua path for any downstream code that looks
        # it up (the canonical place is stplug-in, written by the script).
        _set_download_state(appid, {
            "installedPath": os.path.join(
                base_path, "config", "stplug-in", f"{appid}.lua"
            ),
        })
    finally:
        try:
            _shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        # Drop the original zip too — we've consumed it.
        try:
            os.remove(zip_path)
        except Exception:
            pass


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
                    logger.info(f"LumaDeck: installdir from Steam API: {install_dir}")
                    return install_dir
    except Exception as e:
        logger.debug(f"LumaDeck: Failed to fetch installdir from API: {e}")
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


async def _restart_steam_delayed(delay: int = 5) -> None:
    """Ask Steam to shut down after a delay; on Steam Deck Game Mode the session
    manager then auto-relaunches it, so SLSsteam/lumalinux read the fresh config
    on the new start.

    MUST run as the `deck` user. The Decky plugin runs as root, but Steam runs as
    `deck`, and `steam -shutdown` talks to the running client over a per-user IPC
    tied to that user's HOME / XDG_RUNTIME_DIR. Invoked as root it never reaches
    the deck-user Steam, so the shutdown silently no-ops (this is why the restart
    was never happening). We drop to `deck` via runuser, with a clean env (no
    PyInstaller LD_LIBRARY_PATH), the deck user's runtime dir, and the full
    /usr/bin/steam path."""
    await asyncio.sleep(delay)
    try:
        import subprocess
        from subprocess_env import clean_env
        logger.info("LumaDeck: Restarting Steam (steam -shutdown as deck)...")
        # As root, drop to deck via runuser (Steam's IPC is per-user). If Decky
        # runs this backend unprivileged (as deck) instead, runuser fails
        # ("may not be used by non-root users") — we're already deck, so call
        # steam directly. Either way the process runs as deck with deck's runtime
        # dir, which is what `steam -shutdown` needs to reach the live client.
        if os.geteuid() == 0:
            cmd = ["runuser", "-u", "deck", "--", "/usr/bin/steam", "-shutdown"]
        else:
            cmd = ["/usr/bin/steam", "-shutdown"]
        subprocess.Popen(
            cmd,
            env=clean_env(HOME="/home/deck", XDG_RUNTIME_DIR="/run/user/1000"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning(f"LumaDeck: Failed to restart Steam: {e}")
        return


async def repair_appmanifest(appid: int) -> dict:
    """Repair the .acf for an installed game by deleting it so Steam
    recreates it on its next refresh.

    Rationale: in the LumaDeck flow Steam writes the .acf itself during
    the native download (after steamidra_lite seeds the stub). Manually
    reconstructing it the way the upstream DDL flow did — with a fixed
    InstalledDepots / SizeOnDisk and chmod 0444 to lock Steam out — would
    prevent Steam from maintaining its own bookkeeping after the repair.
    The simplest, conflict-free recovery is therefore to delete the
    current .acf and let Steam regenerate it.

    Looks across every Steam library (some users move games to a SD card
    or external drive). Removes the read-only bit first in case the .acf
    being repaired was written by the legacy chmod 0444 path. Returns
    the list of removed paths.

    Does NOT auto-restart Steam — Repair is a per-game operation and
    silently restarting Steam would surprise the user. They can pair this
    with the existing 'Restart Steam' action when they're ready.
    """
    from steam_utils import get_steam_libraries, detect_steam_install_path

    libs = get_steam_libraries() or [{"path": detect_steam_install_path() or ""}]
    removed_paths: list[str] = []
    for lib in libs:
        lib_path = lib.get("path") if isinstance(lib, dict) else str(lib)
        if not lib_path:
            continue
        acf_path = os.path.join(lib_path, "steamapps", f"appmanifest_{appid}.acf")
        if not os.path.exists(acf_path):
            continue
        try:
            # Legacy DDL-era repairs chmod'd to 0444 — unlock before unlink.
            os.chmod(acf_path, 0o644)
        except Exception:
            pass
        try:
            os.remove(acf_path)
            removed_paths.append(acf_path)
            logger.info(f"LumaDeck: removed stale .acf {acf_path}")
        except Exception as exc:
            logger.warning(f"LumaDeck: could not remove {acf_path}: {exc}")

    if not removed_paths:
        return {
            "success": True, "removed": False,
            "message": f"No .acf found for AppID {appid}",
        }
    return {
        "success": True, "removed": True,
        "removed_paths": removed_paths,
        "message": (
            f"Removed {len(removed_paths)} .acf file(s). "
            "Restart Steam so it regenerates them, then click Install/Update "
            "on the game in your library."
        ),
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
        "errorCode": None,  # clear any stale code from a previous failed attempt
    })

    # Reactive degradation for a stuck-update Fix / re-deploy: if a Hubcap source
    # answers 401/403, the API key has expired (they last 7 days). Record it so
    # the terminal failure can surface a dedicated "renew your key" message + a
    # Settings link instead of the generic "Not available on any API" error (#21).
    hubcap_key_expired = False

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
        try:
            headers = {"User-Agent": USER_AGENT}

            # Hubcap auth: the api.json template embeds the key in the URL
            # as ?api_key=... because that's the shape Star123451's upstream
            # api.json publishes. Hubcap also accepts the same key via
            # Authorization: Bearer; we extract it from the URL and move it
            # to the header so the cleaned URL we log doesn't contain the
            # key. Backports the upstream DeckTools d557f2a fix to LumaDeck.
            if "hubcapmanifest.com" in url or "morrenus.xyz" in url:
                from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
                _parts = urlsplit(url)
                _remaining_qs = []
                _hubcap_token = None
                for _k, _v in parse_qsl(_parts.query, keep_blank_values=True):
                    if _k == "api_key":
                        _hubcap_token = _v
                    else:
                        _remaining_qs.append((_k, _v))
                url = urlunsplit((
                    _parts.scheme, _parts.netloc, _parts.path,
                    urlencode(_remaining_qs), _parts.fragment,
                ))
                if _hubcap_token:
                    headers["Authorization"] = f"Bearer {_hubcap_token}"

            # Log AFTER scrubbing the URL so the api_key never lands here.
            logger.info(f"LumaDeck: Trying API '{name}' -> {url}")

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
                    logger.warning("LumaDeck: Ryuu API detected but ryuu_cookie.txt not found or empty!")

            if _is_download_cancelled(appid):
                return

            async with client.stream("GET", url, headers=headers, follow_redirects=True, timeout=30) as resp:
                code = resp.status_code
                logger.info(f"LumaDeck: API '{name}' status={code}")
                if code == unavailable_code:
                    continue
                if code != success_code:
                    if "ryuu.lol" in url and code in (401, 403):
                        logger.warning(f"LumaDeck: Ryuu access denied ({code}). Check if cookie expired.")
                    if ("hubcapmanifest.com" in url or "morrenus.xyz" in url) and code in (401, 403):
                        hubcap_key_expired = True
                        logger.warning(f"LumaDeck: Hubcap access denied ({code}). API key likely expired.")
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
                                f"LumaDeck: API '{name}' returned non-zip (magic={magic.hex()}, size={file_size}, preview={content_preview[:50]})"
                            )
                            if "Login required" in content_preview or "Sign in" in content_preview:
                                logger.error("LumaDeck: Ryuu site asked for login. Cookie is invalid or expired.")
                            try:
                                os.remove(dest_path)
                            except Exception:
                                pass
                            continue
                except FileNotFoundError:
                    continue

                # Process and install via steamidra_lite (LumaDeck flow).
                # The script writes everything we used to do across the
                # plugin: depotcache, keys.txt, config.vdf DecryptionKeys,
                # AdditionalApps in SLSsteam config.yaml, the .acf stub, the
                # .lua copy into stplug-in, ACCELA markers, and the .depot
                # update tracker. After that, we trigger `steam -shutdown` so
                # SteamOS Game Mode relaunches Steam with the hooks reading
                # the fresh config; Steam itself downloads the game natively.
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
                        fetched_name = f"Unknown ({appid})"

                    # Best-effort SLSsteam DLC enrichment. steamidra_lite has
                    # already written AdditionalApps + DecryptionKeys, so the
                    # only thing left from the upstream "configure SLSsteam"
                    # block that wasn't covered is the DLC list (we'd query
                    # Steam Web API to discover DLC ids and add them to
                    # DlcData). Token and AdditionalApps are intentionally
                    # NOT called again here — they're idempotent inside the
                    # script anyway.
                    _set_download_state(appid, {"status": "configuring"})
                    try:
                        from slssteam_ops import add_game_dlcs
                        dlc_result = await add_game_dlcs(appid)
                        logger.info(f"LumaDeck: SLSsteam add_game_dlcs({appid}): {dlc_result}")
                    except Exception as dlc_exc:
                        logger.warning(f"LumaDeck: SLSsteam DLC enrichment failed: {dlc_exc}")

                    # TEMP (native-achievement test): the Steam Web API schema
                    # auto-gen is disabled so a fresh install writes NOTHING of
                    # ours and SLSsteam's native achievement support can be tested
                    # from a clean slate. Re-enable by uncommenting the block below.
                    # try:
                    #     from achievements import auto_generate_on_install
                    #     ach_result = await auto_generate_on_install(appid)
                    #     logger.info(f"LumaDeck: achievement auto-gen({appid}): {ach_result}")
                    # except Exception as ach_exc:
                    #     logger.warning(f"LumaDeck: achievement auto-gen failed: {ach_exc}")
                    logger.info(f"LumaDeck: achievement auto-gen DISABLED (native test build) for {appid}")

                    # Force Proton if no Linux depot was added during the
                    # enrich pass — Steam wouldn't otherwise launch a Windows
                    # binary on the Deck without explicit compat tool.
                    if not _get_download_state(appid).get("hasLinuxDepot", False):
                        try:
                            from steam_utils import set_compat_tool_for_app
                            if set_compat_tool_for_app(appid):
                                logger.info(f"LumaDeck: Forced proton_experimental for {appid} (Windows-only depot)")
                        except Exception as proton_exc:
                            logger.warning(f"LumaDeck: set_compat_tool error: {proton_exc}")

                    # Trigger Steam restart so Game Mode reloads it with the
                    # fresh config + hooks active. SteamOS auto-relaunches.
                    # See _restart_steam_delayed: it sleeps `delay` seconds
                    # so the frontend sees the "restarting" state before the
                    # shutdown actually fires. The actual game download is
                    # native Steam after the restart — progress shows in the
                    # Steam library UI itself, not in this plugin.
                    _set_download_state(appid, {
                        "status": "restarting_steam",
                        "message": "Restarting Steam to start the download…",
                    })
                    _t = asyncio.create_task(_restart_steam_delayed(delay=5))
                    _BACKGROUND_TASKS.add(_t)
                    _t.add_done_callback(_BACKGROUND_TASKS.discard)

                    _set_download_state(appid, {
                        "status": "done", "success": True, "api": name,
                    })
                    return
                except Exception as install_exc:
                    if isinstance(install_exc, RuntimeError) and str(install_exc) == "cancelled":
                        try:
                            if os.path.exists(dest_path):
                                os.remove(dest_path)
                        except Exception:
                            pass
                        return
                    logger.warning(f"LumaDeck: Processing failed -> {install_exc}")
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
            logger.warning(f"LumaDeck: API '{name}' failed: {err}")
            continue

    if hubcap_key_expired:
        _set_download_state(appid, {
            "status": "failed",
            "error": "Hubcap API key expired",
            "errorCode": "hubcap_key_expired",
        })
    else:
        _set_download_state(appid, {"status": "failed", "error": "Not available on any API"})


async def start_download(appid: int, target_library_path: str = "") -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    logger.info(f"LumaDeck: start_download appid={appid} library={target_library_path or '(default)'}")
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
            logger.warning(f"LumaDeck: Failed to delete {path}: {exc}")
    try:
        name = _get_loaded_app_name(appid) or f"Unknown ({appid})"
        _remove_loaded_app(appid)
        if deleted:
            _log_appid_event("REMOVED", appid, name)
    except Exception:
        pass
    return {"success": True, "deleted": deleted, "count": len(deleted)}


def _dir_has_real_content(game_dir: str) -> bool:
    """True if the game folder has any entry that isn't an ACCELA marker / OS
    metadata / dotfile — i.e. Steam has actually finished downloading the game.
    Mirrors ASSella game_manager._has_game_content."""
    ignore = {".accela", ".depotdownloader", "desktop.ini", "thumbs.db"}
    try:
        for entry in os.scandir(game_dir):
            name = entry.name
            if name.lower() in ignore or name.startswith("."):
                continue
            return True
    except OSError:
        return False
    return False


def _ensure_accela_mark(appid: int, base_path: str) -> None:
    """Best-effort: (re)create the ACCELA marker for a game that's fully
    installed but not yet marked, by running `steamidra_lite --accela-mark`.

    Why here (on library refresh): the download flow sets up Steam's config
    BEFORE Steam downloads the game, so at that point the game folder is empty
    and the in-game `.DepotDownloader` marker can't take effect (ACCELA only
    lists folders with real content). Doing it on refresh means it fires once
    the game has actually been installed. Idempotent, non-blocking, and a no-op
    unless a marker is genuinely missing on a downloaded game.

    Passes --steam-root and HOME=/home/deck explicitly so the marker and the
    ~/.local/share/ACCELA/depots tracker land in the deck user's tree (the
    plugin runs as root, where ~ would otherwise be /root).

    Requires lumalinux v0.13.0+. --accela-mark itself landed in v0.11.0, but
    the install flow this self-heal feeds off (Steam actually downloading the
    game) only works once the package-0 finder is on by default, which
    happened in v0.13.0. Against an older script the spawn just no-ops
    (argparse error to a discarded stderr)."""
    try:
        import subprocess
        from subprocess_env import clean_env

        acf = os.path.join(base_path, "steamapps", f"appmanifest_{appid}.acf")
        if not os.path.exists(acf):
            return
        with open(acf, "r", encoding="utf-8", errors="ignore") as fh:
            m = re.search(r'"installdir"\s+"([^"]+)"', fh.read())
        if not m:
            return
        installdir = m.group(1)
        game_dir = os.path.join(base_path, "steamapps", "common", installdir)
        if os.path.exists(os.path.join(game_dir, ".DepotDownloader")):
            return  # already marked, nothing to do
        if not _dir_has_real_content(game_dir):
            return  # Steam hasn't finished downloading yet
        script = _find_steamidra_lite_script()
        if not script:
            return
        subprocess.Popen(
            [_LUMALINUX_PYTHON, script, "--accela-mark", str(appid), "--steam-root", base_path],
            env=clean_env(HOME="/home/deck"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f"LumaDeck: self-heal ACCELA mark for {appid} (installdir='{installdir}')")
    except Exception as exc:
        logger.debug(f"LumaDeck: _ensure_accela_mark({appid}) skipped: {exc}")


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

        # Best-effort self-heal: ensure ACCELA markers for games that are fully
        # installed. The download flow can't do this (Steam downloads the game
        # AFTER our setup runs), so we do it here, on library refresh. Idempotent
        # and non-blocking — only spawns steamidra_lite when a marker is missing.
        for s in installed_scripts:
            if s.get("hasGameFiles"):
                _ensure_accela_mark(int(s["appid"]), base_path)

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


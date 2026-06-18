"""Management of the LumaDeck API manifest (free API list)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from config import (
    API_JSON_FILE,
    API_MANIFEST_PROXY_URL,
    API_MANIFEST_URL,
    HTTP_PROXY_TIMEOUT_SECONDS,
)
from http_client import ensure_http_client
from paths import data_path
from utils import count_apis, normalize_manifest_text, read_text, write_text

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

_APIS_INIT_DONE = False
_INIT_APIS_LAST_MESSAGE = ""


async def init_apis() -> dict:
    """Initialise the free API manifest if it has not been loaded yet."""
    global _APIS_INIT_DONE, _INIT_APIS_LAST_MESSAGE
    logger.info("InitApis: invoked")
    if _APIS_INIT_DONE:
        return {"success": True, "message": _INIT_APIS_LAST_MESSAGE}

    client = await ensure_http_client("InitApis")
    api_json_path = data_path(API_JSON_FILE)
    message = ""

    if os.path.exists(api_json_path):
        logger.info(f"InitApis: Local file exists -> {api_json_path}; skipping remote fetch")
    else:
        logger.info(f"InitApis: Local file not found -> {api_json_path}")
        manifest_text = ""
        try:
            try:
                resp = await client.get(API_MANIFEST_URL)
                resp.raise_for_status()
                manifest_text = resp.text
            except Exception as primary_err:
                logger.warning(f"InitApis: Primary URL failed ({primary_err}), trying proxy...")
                if API_MANIFEST_PROXY_URL:
                    try:
                        resp = await client.get(API_MANIFEST_PROXY_URL, timeout=HTTP_PROXY_TIMEOUT_SECONDS)
                        resp.raise_for_status()
                        manifest_text = resp.text
                    except Exception as proxy_err:
                        logger.warning(f"InitApis: Proxy also failed: {proxy_err}")
                        raise primary_err
                else:
                    raise
        except Exception as fetch_err:
            logger.warning(f"InitApis: Failed to fetch free API manifest: {fetch_err}")

        normalized = normalize_manifest_text(manifest_text) if manifest_text else ""
        if normalized:
            write_text(api_json_path, normalized)
            count = count_apis(normalized)
            message = f"Loaded {count} Free APIs"
        else:
            message = "Failed to load free APIs"

    _APIS_INIT_DONE = True
    _INIT_APIS_LAST_MESSAGE = message
    return {"success": True, "message": message}


def get_init_apis_message() -> dict:
    """Return and clear the last InitApis message."""
    global _INIT_APIS_LAST_MESSAGE
    msg = _INIT_APIS_LAST_MESSAGE or ""
    _INIT_APIS_LAST_MESSAGE = ""
    return {"success": True, "message": msg}


async def fetch_free_apis_now() -> dict:
    """Force refresh of the free API manifest."""
    client = await ensure_http_client("FetchFreeApisNow")
    try:
        manifest_text = ""
        try:
            resp = await client.get(API_MANIFEST_URL, follow_redirects=True)
            resp.raise_for_status()
            manifest_text = resp.text
        except Exception as primary_err:
            if API_MANIFEST_PROXY_URL:
                try:
                    resp = await client.get(API_MANIFEST_PROXY_URL, follow_redirects=True, timeout=HTTP_PROXY_TIMEOUT_SECONDS)
                    resp.raise_for_status()
                    manifest_text = resp.text
                except Exception as proxy_err:
                    return {"success": False, "error": f"Both URLs failed: {primary_err}, {proxy_err}"}
            else:
                return {"success": False, "error": str(primary_err)}

        normalized = normalize_manifest_text(manifest_text) if manifest_text else ""
        if not normalized:
            return {"success": False, "error": "Empty manifest"}

        write_text(data_path(API_JSON_FILE), normalized)
        try:
            data = json.loads(normalized)
            count = len(data.get("api_list", []))
        except Exception:
            count = normalized.count('"name"')

        return {"success": True, "count": count}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def load_api_manifest() -> List[Dict[str, Any]]:
    """Return the list of enabled APIs from api.json."""
    path = data_path(API_JSON_FILE)
    text = read_text(path)
    normalized = normalize_manifest_text(text)
    if normalized and normalized != text:
        try:
            write_text(path, normalized)
        except Exception:
            pass
        text = normalized

    try:
        data = json.loads(text or "{}")
        apis = data.get("api_list", [])
        return [api for api in apis if api.get("enabled", False)]
    except Exception as exc:
        logger.error(f"LumaDeck: Failed to parse api.json: {exc}")
        return []


def save_ryu_cookie(cookie_content: str) -> dict:
    """Save the Ryuu cookie to data/ryuu_cookie.txt."""
    try:
        from paths import data_path
        path = data_path("ryuu_cookie.txt")
        clean_cookie = cookie_content.strip()
        if clean_cookie and not clean_cookie.startswith("session="):
            clean_cookie = f"session={clean_cookie}"
        with open(path, "w", encoding="utf-8") as f:
            f.write(clean_cookie)
        return {"success": True, "message": "Cookie saved successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def load_ryu_cookie() -> str:
    """Read the Ryuu cookie from file."""
    try:
        from paths import data_path
        path = data_path("ryuu_cookie.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def update_hubcap_key(key_content: str) -> dict:
    """Update the Hubcap API key in api.json."""
    try:
        path = data_path(API_JSON_FILE)
        key_content = key_content.strip()
        if not key_content:
            return {"success": False, "error": "Key cannot be empty"}

        root_data = {"api_list": []}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                try:
                    content = f.read()
                    if content.strip():
                        root_data = json.loads(content)
                except json.JSONDecodeError:
                    root_data = {"api_list": []}

        if "api_list" not in root_data:
            root_data["api_list"] = []

        api_list = root_data["api_list"]
        # Hubcap (formerly Morrenus, the API rebranded) (hubcapmanifest.com). The endpoint still
        # accepts the legacy ?api_key= querystring (Star123451's upstream
        # api.json uses this form), so we keep the URL shape, only the host
        # changes. Old api.json entries with manifest.morrenus.xyz are matched
        # below by the legacy substring so they get rewritten on first edit.
        new_url = f"https://hubcapmanifest.com/api/v1/manifest/<appid>?api_key={key_content}"
        found = False

        for api in api_list:
            name = api.get("name", "").lower()
            url = api.get("url", "")
            if ("morrenus" in name or "hubcap" in name
                    or "morrenus.xyz" in url or "hubcapmanifest.com" in url):
                api["url"] = new_url
                api["enabled"] = True
                found = True
                break

        if not found:
            api_list.insert(0, {
                "name": "Hubcap (Official ACCELA)",
                "url": new_url,
                "success_code": 200,
                "unavailable_code": 404,
                "enabled": True,
            })

        with open(path, "w", encoding="utf-8") as f:
            json.dump(root_data, f, indent=4)

        return {"success": True, "message": "Hubcap key updated successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_hubcap_key() -> str:
    """Extract the Hubcap API key from api.json. Accepts both the
    legacy host (manifest.morrenus.xyz) and the new one (hubcapmanifest.com)
    in case an older api.json file is still cached locally."""
    try:
        path = data_path(API_JSON_FILE)
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
        for api in data.get("api_list", []):
            url = api.get("url", "")
            host_match = "hubcapmanifest.com" in url or "morrenus.xyz" in url
            if host_match and "api_key=" in url:
                key = url.split("api_key=")[-1].strip()
                # Skip template placeholders like `<moapikey>` left in default
                # api.json files — they aren't real keys, and surfacing one as a
                # prefilled value in the UI looks like junk default text.
                if not key or "<" in key or ">" in key:
                    continue
                return key
        return ""
    except Exception:
        return ""


def load_hubcap_key() -> str:
    """Return the current Hubcap API key."""
    return _get_hubcap_key()


async def search_hubcap(query: str) -> dict:
    """Search for games by name using the Hubcap API."""
    try:
        key = _get_hubcap_key()
        if not key:
            return {"success": False, "error": "Hubcap API key not configured. Set it in Settings."}

        if len(query.strip()) < 2:
            return {"success": False, "error": "Search query must be at least 2 characters"}

        from urllib.parse import urlencode
        client = await ensure_http_client("HubcapSearch")
        qs = urlencode({"q": query.strip(), "limit": 50})
        # Morrenus → Hubcap rebrand. Endpoint still accepts Bearer auth (same
        # mechanism SFF uses, see sff/lua/endpoints.py:181). Querystring api_key
        # is the alternative the manifest endpoint accepts, but /search wants
        # the header form.
        resp = await client.get(
            f"https://hubcapmanifest.com/api/v1/search?{qs}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )

        if resp.status_code == 401:
            return {"success": False, "error": "Invalid API key. Check Settings."}
        elif resp.status_code == 429:
            return {"success": False, "error": "Daily API limit exceeded. Try again later."}
        elif resp.status_code != 200:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            return {"success": False, "error": f"API error ({resp.status_code}): {detail}"}

        data = resp.json()
        results = data.get("results", [])

        # Filter out non-game results (soundtracks, demos, tools, etc.)
        import re
        blacklist = [
            "soundtrack", "ost", "original soundtrack", "artbook",
            "graphic novel", "demo", "server", "dedicated server",
            "tool", "sdk", "3d print model",
        ]
        filtered = []
        for game in results:
            name = game.get("game_name", "")
            name_lower = name.lower()
            is_blacklisted = any(re.search(r'\b' + kw + r'\b', name_lower) for kw in blacklist)
            if not is_blacklisted:
                filtered.append({
                    "appid": game.get("game_id"),
                    "name": game.get("game_name", f"Unknown ({game.get('game_id', '?')})"),
                })

        return {"success": True, "results": filtered, "total": len(results), "filtered": len(filtered)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _depot_snapshot_path(appid: int) -> str:
    """Return path to the depot snapshot file for an appid."""
    from paths import data_path
    depots_dir = os.path.join(os.path.dirname(data_path("x")), "depots")
    os.makedirs(depots_dir, exist_ok=True)
    return os.path.join(depots_dir, f"{appid}.json")


async def _fetch_steamcmd_manifests(appid: int) -> dict:
    """Fetch public manifest IDs from SteamCMD API. Returns {depot_id: manifest_gid}."""
    client = await ensure_http_client("UpdateCheck")
    resp = await client.get(
        f"https://api.steamcmd.net/v1/info/{appid}",
        timeout=10,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"SteamCMD API error ({resp.status_code})")

    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError("SteamCMD API returned failure")

    app_data = data.get("data", {}).get(str(appid), {})
    depots_data = app_data.get("depots", {})

    result = {}
    for depot_id, depot_info in depots_data.items():
        if not depot_id.isdigit():
            continue
        manifests = depot_info.get("manifests", {})
        public_manifest = manifests.get("public", {})
        gid = public_manifest.get("gid") if isinstance(public_manifest, dict) else str(public_manifest) if public_manifest else None
        if gid:
            result[depot_id] = str(gid)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Depot snapshot helpers — currently orphaned in the LumaDeck flow.
#
# These two functions are kept callable but nothing in the live code path
# invokes them. The download flow used to call save_depot_snapshot at the end
# of an install (commit f63bd6e removed that call), and check_game_update
# below only uses save_depot_snapshot_from_depotcache as a fallback when no
# baseline exists. The design (see DESIGN.md decision #11) is to migrate
# check_game_update to read ACCELA's <accela_root>/depots/<appid>.depot
# tracker as the single source of truth across the ecosystem; once that
# migration lands, these two helpers can come out entirely.
#
# Left here on purpose for the time being so the rollback / comparison path
# stays intact and DESIGN.md's "TODO migrate to .depot" reference points at
# something concrete.
# ─────────────────────────────────────────────────────────────────────────────


async def save_depot_snapshot(appid: int) -> dict:
    """Save current SteamCMD public manifests as the known-installed version for an appid."""
    try:
        appid = int(appid)
        remote = await _fetch_steamcmd_manifests(appid)
        if not remote:
            return {"success": False, "error": "No depot data from SteamCMD"}

        path = _depot_snapshot_path(appid)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"appid": appid, "manifests": remote}, f)
        logger.info(f"LumaDeck: Saved depot snapshot for {appid} ({len(remote)} depots)")
        return {"success": True}
    except Exception as e:
        logger.warning(f"LumaDeck: Failed to save depot snapshot for {appid}: {e}")
        return {"success": False, "error": str(e)}


def save_depot_snapshot_from_depotcache(appid: int, depot_ids: list, depotcache_dir: str) -> dict:
    """Save depot snapshot by reading manifest files actually downloaded into depotcache.

    Scans depotcache_dir for files named {depot_id}_{manifest_id}.manifest for each
    depot_id in depot_ids and records the installed manifest IDs.  This is the source
    of truth for what DDM actually downloaded (not what SteamCMD currently reports).
    """
    import re as _re

    try:
        appid = int(appid)
        manifests: dict = {}

        depot_id_set = {str(d) for d in depot_ids}

        if os.path.isdir(depotcache_dir):
            for fname in os.listdir(depotcache_dir):
                m = _re.fullmatch(r"(\d+)_(\d+)\.manifest", fname)
                if m and m.group(1) in depot_id_set:
                    depot_id = m.group(1)
                    manifest_id = m.group(2)
                    # Keep the newest file per depot (largest manifest ID as tiebreak)
                    if depot_id not in manifests or int(manifest_id) > int(manifests[depot_id]):
                        manifests[depot_id] = manifest_id

        if not manifests:
            logger.warning(f"LumaDeck: No manifest files found in depotcache for {appid}, depot_ids={depot_ids}")
            return {"success": False, "error": "No manifest files found in depotcache"}

        path = _depot_snapshot_path(appid)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"appid": appid, "manifests": manifests}, f)
        logger.info(f"LumaDeck: Saved depot snapshot for {appid} from depotcache ({len(manifests)} depots)")
        return {"success": True}
    except Exception as e:
        logger.warning(f"LumaDeck: Failed to save depot snapshot from depotcache for {appid}: {e}")
        return {"success": False, "error": str(e)}


async def check_game_update(appid: int) -> dict:
    """Check if a game has an update by comparing saved depot snapshot with SteamCMD public API."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    # Pinned games are frozen on purpose (BuildDep holds them) — don't surface an
    # update badge. Report it explicitly so the UI can say "pinned" vs "up to date".
    try:
        from downloads import get_pin_status
        pin = await get_pin_status(appid)
        if pin.get("pinned"):
            return {"success": True, "updateAvailable": False, "pinned": True}
    except Exception:
        pass

    try:
        # 1. Read saved snapshot (created after last download)
        snapshot_path = _depot_snapshot_path(appid)
        if not os.path.exists(snapshot_path):
            # No snapshot — try to build baseline from depotcache (actual installed manifests).
            # Using SteamCMD here would create a baseline that matches current remote,
            # making the comparison trivially equal and masking real pending updates.
            from steam_utils import detect_steam_install_path
            steam_path = detect_steam_install_path() or "/home/deck/.local/share/Steam"
            depotcache_dir = os.path.join(steam_path, "depotcache")
            remote_manifests_for_baseline = await _fetch_steamcmd_manifests(appid)
            depot_ids = list(remote_manifests_for_baseline.keys())
            if depot_ids and os.path.isdir(depotcache_dir):
                result = save_depot_snapshot_from_depotcache(appid, depot_ids, depotcache_dir)
                if result.get("success") and os.path.exists(snapshot_path):
                    logger.info(f"LumaDeck: Built update baseline for {appid} from depotcache")
                    # Fall through to comparison below using the just-saved snapshot
                else:
                    # No manifest files in depotcache — game was not installed via LumaDeck
                    return {"success": False, "error": "No update baseline. Re-download the game first."}
            else:
                return {"success": False, "error": "No update baseline. Re-download the game first."}

        with open(snapshot_path, "r", encoding="utf-8") as f:
            snapshot = json.loads(f.read())
        local_manifests = snapshot.get("manifests", {})

        if not local_manifests:
            return {"success": False, "error": "Empty depot snapshot"}

        # 2. Query SteamCMD for current public manifests
        remote_manifests = await _fetch_steamcmd_manifests(appid)

        # 3. Compare saved vs current
        update_available = False
        changes = []
        for depot_id, local_mid in local_manifests.items():
            remote_mid = remote_manifests.get(depot_id)
            if remote_mid and str(local_mid) != str(remote_mid):
                update_available = True
                changes.append({"depot": depot_id, "local": local_mid, "remote": remote_mid})

        return {
            "success": True,
            "updateAvailable": update_available,
            "localDepots": len(local_manifests),
            "remoteDepots": len(remote_manifests),
            "changes": changes,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

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


# ---------------------------------------------------------------------------
# Persistent credential store (survives plugin reinstalls)
# ---------------------------------------------------------------------------
#
# The Hubcap key lives in backend/data/api.json and the Ryuu cookie in
# backend/data/ryuu_cookie.txt — both inside the plugin dir, which Decky wipes
# and replaces on a manual "Install from ZIP" reinstall, taking the credentials
# with it. To stop them vanishing on every update we mirror them into the Decky
# settings dir (which Decky leaves untouched across reinstalls) and restore them
# at load when the plugin-dir copies are gone.

def _cred_store_path() -> str:
    from paths import settings_dir
    return os.path.join(settings_dir(), "credentials.json")


def _read_cred_store() -> dict:
    try:
        p = _cred_store_path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _mirror_cred(**values: str) -> None:
    """Merge non-empty credential values into the persistent settings-dir store."""
    try:
        store = _read_cred_store()
        changed = False
        for k, v in values.items():
            if v:
                store[k] = v
                changed = True
        if not changed:
            return
        p = _cred_store_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2)
    except Exception:
        pass


def restore_credentials_from_settings() -> None:
    """Re-apply credentials saved in the settings dir when the plugin-dir copies
    are missing (e.g. right after a reinstall wiped backend/data/). Idempotent,
    so it is safe to call on every plugin load."""
    store = _read_cred_store()
    if not store:
        return
    key = store.get("hubcap_key")
    if key and not _get_hubcap_key():
        try:
            update_hubcap_key(key)
            logger.info("LumaDeck: restored Hubcap key from settings store")
        except Exception:
            pass
    cookie = store.get("ryuu_cookie")
    if cookie and not load_ryu_cookie():
        try:
            save_ryu_cookie(cookie)
            logger.info("LumaDeck: restored Ryuu cookie from settings store")
        except Exception:
            pass
    expiry = store.get("ryuu_cookie_expiry")
    if expiry and not load_ryu_cookie_expiry():
        try:
            save_ryu_cookie_expiry(expiry)
        except Exception:
            pass



# Our own curated manifest-source list (option B): shipped in the plugin, NOT
# fetched from any third-party repo, so we don't inherit an outside list's order,
# selection, or fate. Order = reliability + freshness first:
#   1. Morrenus / Hubcap   (key)   — maintained, most complete, day-one releases
#   2. Forced Ryu (Cookie)         — day-one releases, credential fallback
#   3. Sushi               (free)  — DISABLED: free GitHub mirror, lags new games
#   4. Spinoza             (free)  — DISABLED: free GitHub mirror, lags new games
# Sushi/Spinoza stay in the list but disabled, so re-enabling them later is a
# one-line `"enabled": True` flip. The old Ryuu IP mirror (167.235.229.108) is
# dropped: a hardcoded IP with no domain to relocate it, and it just repackaged
# Sushi's content anyway. The name "Morrenus" is kept because the Hubcap-key
# injector (`update_hubcap_key`) matches the entry by that name.
DEFAULT_API_LIST = [
    {"name": "Morrenus", "url": "https://hubcapmanifest.com/api/v1/manifest/<appid>?api_key=<moapikey>", "success_code": 200, "unavailable_code": 404, "enabled": True},
    {"name": "Forced Ryu (Cookie)", "url": "https://generator.ryuu.lol/download?appid=<appid>&file_type=manifest", "success_code": 200, "unavailable_code": 404, "enabled": True},
    {"name": "Sushi", "url": "https://raw.githubusercontent.com/sushi-dev55-alt/sushitools-games-repo-alt/refs/heads/main/<appid>.zip", "success_code": 200, "unavailable_code": 404, "enabled": False},
    {"name": "Spinoza", "url": "https://github.com/SPIN0ZAi/SB_manifest_DB/archive/refs/heads/<appid>.zip", "success_code": 200, "unavailable_code": 404, "enabled": False},
]


async def init_apis() -> dict:
    """Seed the manifest-source list from our own curated DEFAULT_API_LIST.

    Option B: LumaDeck owns the list — no fetch from any third-party repo. We
    re-seed on every launch so all installs converge on the curated order and
    enabled-set, preserving the user's Hubcap key across the rewrite (the Ryuu
    cookie lives in a separate file and is untouched)."""
    global _APIS_INIT_DONE, _INIT_APIS_LAST_MESSAGE
    logger.info("InitApis: invoked")
    if _APIS_INIT_DONE:
        return {"success": True, "message": _INIT_APIS_LAST_MESSAGE}

    api_json_path = data_path(API_JSON_FILE)
    # Preserve an existing Hubcap key (embedded in api.json) across the reseed;
    # main._main also runs restore_credentials_from_settings() right after, which
    # re-applies the key from the settings-dir store for the wiped-data case.
    saved_hubcap_key = _get_hubcap_key()

    try:
        root = {"api_list": [dict(a) for a in DEFAULT_API_LIST]}
        write_text(api_json_path, json.dumps(root, indent=4))
        if saved_hubcap_key:
            update_hubcap_key(saved_hubcap_key)
        enabled = sum(1 for a in DEFAULT_API_LIST if a.get("enabled"))
        message = f"Loaded {enabled} manifest source(s)"
    except Exception as exc:
        logger.warning(f"InitApis: failed to seed curated list: {exc}")
        message = "Failed to seed manifest sources"

    _APIS_INIT_DONE = True
    _INIT_APIS_LAST_MESSAGE = message
    return {"success": True, "message": message}


def get_init_apis_message() -> dict:
    """Return and clear the last InitApis message."""
    global _INIT_APIS_LAST_MESSAGE
    msg = _INIT_APIS_LAST_MESSAGE or ""
    _INIT_APIS_LAST_MESSAGE = ""
    return {"success": True, "message": msg}


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
        # Mirror to the settings-dir store so a reinstall can restore it.
        _mirror_cred(ryuu_cookie=clean_cookie)
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


def save_ryu_cookie_expiry(iso) -> None:
    """Persist the imported Ryuu cookie's expiry (ISO-8601) alongside it, so the
    credential-status check can compute days-left without re-reading the browser
    DB. A falsy value (session cookie / unknown) clears any stale sidecar."""
    try:
        path = data_path("ryuu_cookie_expiry.txt")
        if iso:
            with open(path, "w", encoding="utf-8") as f:
                f.write(str(iso))
            _mirror_cred(ryuu_cookie_expiry=str(iso))
        elif os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def load_ryu_cookie_expiry() -> str:
    """Read the saved Ryuu cookie expiry (ISO-8601), or "" if unknown."""
    try:
        path = data_path("ryuu_cookie_expiry.txt")
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

        # Mirror to the settings-dir store so a reinstall can restore it.
        _mirror_cred(hubcap_key=key_content)

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


# Credential-expiry warning thresholds (days). Ryuu cookies live ~3 days, so a
# wide window would keep them permanently "expiring soon" — keep it tight.
# Hubcap keys live weeks, so 5 days' notice is useful.
HUBCAP_WARN_DAYS = 5
RYUU_WARN_DAYS = 1


def _classify_expiry(expires_at_iso, warn_days):
    """Map an ISO-8601 expiry to (state, days_left), state ∈ ok|soon|expired.
    Returns (None, None) when the expiry is missing or unparseable."""
    if not expires_at_iso:
        return None, None
    try:
        import datetime
        # Accept a trailing 'Z'; fromisoformat() doesn't.
        exp = datetime.datetime.fromisoformat(str(expires_at_iso).rstrip("Z"))
        days_left = (exp - datetime.datetime.utcnow()).total_seconds() / 86400.0
    except Exception:
        return None, None
    if days_left <= 0:
        return "expired", days_left
    if days_left <= warn_days:
        return "soon", days_left
    return "ok", days_left


async def get_credential_status() -> dict:
    """Resolve Hubcap key + Ryuu cookie expiry for the UI. Each credential →
    {state, days_left, expires_at, ...} where
      state: none | unknown | ok | soon | expired
    Hubcap expiry comes from the free, no-quota /user/stats endpoint; Ryuu
    expiry from the sidecar captured at cookie-import time."""
    try:
        import dev
        _dov = dev.all_()
        if "hubcap_cred" in _dov or "ryuu_cred" in _dov:
            return dev.cred(dev.get("hubcap_cred"), dev.get("ryuu_cred"))
    except Exception:
        pass
    # ---- Hubcap ----
    hubcap = {"state": "none", "days_left": None, "expires_at": None,
              "daily_usage": None, "daily_limit": None}
    key = _get_hubcap_key()
    if key:
        hubcap["state"] = "unknown"
        try:
            client = await ensure_http_client("HubcapStats")
            # /user/stats is documented as "Free - No usage count", so this poll
            # never eats the user's daily quota.
            resp = await client.get(
                "https://hubcapmanifest.com/api/v1/user/stats",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                hubcap["expires_at"] = data.get("api_key_expires_at")
                hubcap["daily_usage"] = data.get("daily_usage")
                hubcap["daily_limit"] = data.get("daily_limit")
                state, days = _classify_expiry(hubcap["expires_at"], HUBCAP_WARN_DAYS)
                if state:
                    hubcap["state"] = state
                    hubcap["days_left"] = days
            elif resp.status_code == 401:
                # Key present but rejected → expired/invalid; nudge a refresh.
                hubcap["state"] = "expired"
        except Exception as exc:
            logger.warning(f"Credential status: Hubcap stats failed: {exc}")

    # ---- Ryuu ----
    ryuu = {"state": "none", "days_left": None, "expires_at": None}
    if load_ryu_cookie():
        ryuu["state"] = "unknown"
        iso = load_ryu_cookie_expiry()
        if iso:
            ryuu["expires_at"] = iso
            state, days = _classify_expiry(iso, RYUU_WARN_DAYS)
            if state:
                ryuu["state"] = state
                ryuu["days_left"] = days

    return {"success": True, "hubcap": hubcap, "ryuu": ryuu}


"""LuaTools (lua.tools) account integration.

The lua.tools fix catalogue is served from an authenticated API behind a Discord
login: the direct `files.luatools.work` bucket is private (403), and the real
download is a two-step flow — an authed `/api/denuvo/download?fix=...` call that
returns a signed URL, then a fetch of that URL.

We reuse the same "log in via the Steam CEF browser, then harvest the cookie"
pattern already used for Ryuu (ryuu_cookie.py): after the user logs in with
Discord on lua.tools, its Supabase session lands in a (chunked) cookie
`sb-db-auth-token.0/.1/...`. We poll the CEF cookie store, reassemble + decode
that session, and use its access token as a Bearer for the fix API — refreshing
via the refresh token as needed.

NOTE (verify on-device): whether the API needs Cloudflare's `cf_clearance` in
addition to the Bearer is unconfirmed — Ryuu works with just the cookie + a
browser-ish header set, so we start the same way and add cf_clearance only if the
API challenges us.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from urllib.parse import quote

from http_client import ensure_http_client
from paths import data_path
from utils import read_text, write_text

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

# lua.tools' Supabase project ("db" = db.lua.tools). The chunked session cookie is
# `sb-db-auth-token.0`, `.1`, ... (Supabase splits tokens > ~4 KB across cookies).
_HOST = "lua.tools"
_TOKEN_COOKIE_PREFIX = "sb-db-auth-token"
_REFRESH_URL = "https://db.lua.tools/auth/v1/token?grant_type=refresh_token"
# Public anon key (safe to embed — it is meant to ship in clients), lifted from
# the LuaTools app. Sent as the Supabase `apikey` header on refresh.
_SUPABASE_ANON = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpYXQiOjE3NzYwMzkzNzYsImV4cCI6MTg5MzQ1NjAwMCwicm9sZSI6ImFub24iLCJpc3MiOiJzdXBhYmFzZSJ9."
    "f_-K38u3odjltP-g_67FVmG32Vg-_-k-lNBvIaVUVBM"
)

_SESSION_FILE = "luatools_session.json"

# Make requests look like the in-client browser (same trick as Ryuu). ⚠️ swap the
# UA for the real Steam CEF UA if the API turns out to gate on it.
_BROWSERISH = {
    "Referer": "https://lua.tools/",
    "Origin": "https://lua.tools",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# connect-flow progress, surfaced to the UI via get_luatools_status()
_connect_state: dict = {"status": "idle"}


# ---------------------------------------------------------------------------
# Session persistence (mirrors the credential store so it survives reinstalls)
# ---------------------------------------------------------------------------
def _save_session(session: dict) -> None:
    try:
        write_text(data_path(_SESSION_FILE), json.dumps(session))
        try:
            from api_manifest import _mirror_cred
            _mirror_cred(luatools_session=json.dumps(session))
        except Exception:
            pass
    except Exception as exc:
        logger.warning(f"LuaTools: failed to save session: {exc}")


def _load_session() -> dict | None:
    try:
        raw = read_text(data_path(_SESSION_FILE))
        return json.loads(raw) if raw else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cookie harvest → Supabase session
# ---------------------------------------------------------------------------
def _reassemble(chunks: dict) -> dict | None:
    """chunks = {"sb-db-auth-token.0": v0, ".1": v1, ...} → decoded session dict.
    Supabase stores `base64-<b64url(json)>`, split across .0/.1/... cookies."""
    if not chunks:
        return None
    try:
        ordered = sorted(chunks, key=lambda k: int(k.rsplit(".", 1)[-1]))
    except Exception:
        ordered = sorted(chunks)
    raw = "".join(chunks[k] for k in ordered)
    if raw.startswith("base64-"):
        raw = raw[len("base64-"):]
    try:
        padded = raw + "=" * (-len(raw) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:
        logger.warning(f"LuaTools: could not decode session cookie: {exc}")
        return None


def _harvest_once() -> dict | None:
    """Read the CEF cookie store and return the lua.tools Supabase session, or
    None if the user hasn't logged in yet. Blocking (copies the SQLite DB)."""
    from ryuu_cookie import _read_all_cookies_for_host
    # Only decrypt the session cookie(s) — narrowing the query avoids spawning an
    # openssl decrypt per unrelated lua.tools cookie (cf_clearance, analytics, …)
    # on every poll of the connect loop.
    cookies = _read_all_cookies_for_host(_HOST, name_prefix=_TOKEN_COOKIE_PREFIX)
    chunks = {n: v for n, v in cookies.items() if n.startswith(_TOKEN_COOKIE_PREFIX)}
    session = _reassemble(chunks)
    if session and session.get("access_token"):
        return session
    return None


# ---------------------------------------------------------------------------
# Connect flow (called right after the frontend opens the login in the browser)
# ---------------------------------------------------------------------------
async def connect_luatools(timeout_s: int = 180) -> dict:
    """Poll the CEF cookie store until the Discord-login session appears, then
    persist it. Resolves as soon as the token is captured (so the frontend can
    close the browser), or after `timeout_s`."""
    global _connect_state
    _connect_state = {"status": "waiting"}
    loop = asyncio.get_event_loop()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _connect_state.get("status") == "cancelled":
            return {"success": False, "cancelled": True}
        try:
            session = await loop.run_in_executor(None, _harvest_once)
        except Exception as exc:
            logger.warning(f"LuaTools: harvest error: {exc}")
            session = None
        if session:
            _save_session(session)
            _connect_state = {"status": "connected"}
            logger.info("LuaTools: session captured from the Steam browser.")
            return {"success": True}
        # Poll fast (1s) so the browser closes promptly once the login lands; the
        # per-poll cost is now just the session cookie's decrypt (see above).
        await asyncio.sleep(1)
    _connect_state = {"status": "timeout"}
    return {"success": False, "error": "timeout"}


def get_luatools_status() -> dict:
    return {"success": True, "status": _connect_state.get("status", "idle"),
            "connected": _load_session() is not None}


def cancel_connect_luatools() -> dict:
    _connect_state["status"] = "cancelled"
    return {"success": True}


def disconnect_luatools() -> dict:
    try:
        p = data_path(_SESSION_FILE)
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass
    return {"success": True}


# ---------------------------------------------------------------------------
# Access token (auto-refresh)
# ---------------------------------------------------------------------------
async def _access_token() -> str | None:
    session = _load_session()
    if not session:
        return None
    access = session.get("access_token")
    # `expires_at` is unix seconds; refresh a minute early. Parse defensively —
    # a missing/odd value must not throw (it would surface as a bogus error).
    try:
        not_expired = float(session.get("expires_at", 0) or 0) > time.time() + 60
    except (TypeError, ValueError):
        not_expired = False
    if access and not_expired:
        return access
    # Token is (or looks) stale → try to refresh. Crucially, if the refresh can't
    # run or fails, DON'T drop the token we already hold: a freshly harvested
    # session often has no usable `expires_at`, so returning None here made the
    # UI say "connect first" while Settings showed connected. Fall back to the
    # existing token instead and let the server reject it (401 → "session
    # expired") if it really is dead.
    refresh = session.get("refresh_token")
    if refresh:
        try:
            client = await ensure_http_client("LuaToolsAuth")
            resp = await client.post(
                _REFRESH_URL,
                headers={"apikey": _SUPABASE_ANON, "Content-Type": "application/json"},
                json={"refresh_token": refresh},
                timeout=15,
            )
            if resp.status_code == 200:
                new_session = resp.json()
                _save_session(new_session)
                return new_session.get("access_token")
            logger.warning(f"LuaTools: token refresh failed ({resp.status_code}); using existing token")
        except Exception as exc:
            logger.warning(f"LuaTools: token refresh error: {exc}; using existing token")
    else:
        logger.info("LuaTools: session has no refresh_token; using existing access token")
    return access


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", **_BROWSERISH}


# ---------------------------------------------------------------------------
# Fix catalogue (authenticated)
# ---------------------------------------------------------------------------
async def list_luatools_fixes(appid: int) -> dict:
    """Fixes available for `appid` in the lua.tools catalogue.

    This endpoint is PUBLIC — the LuaTools client hits `/api/denuvo/fixes?appid=`
    with a plain HttpClient (no Authorization header), which is why the web page
    `lua.tools/fixes/<appid>` is browsable without logging in. So we do NOT require
    a session here; we only attach a Bearer if we happen to already have one (it is
    harmless and lets the server personalise the response if it wants to). Login is
    only needed for the *download* step (signed URL)."""
    headers = dict(_BROWSERISH)
    token = await _access_token()  # None when not connected — that's fine
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        client = await ensure_http_client("LuaToolsFixes")
        resp = await client.get(
            f"https://lua.tools/api/denuvo/fixes?appid={appid}",
            headers=headers, timeout=15,
        )
        if resp.status_code == 404:
            # lua.tools returns 404 for a game with no catalogue entry (same as the
            # web page lua.tools/fixes/<appid>). That's "no fixes", not an error —
            # surface it as an empty result so the UI shows "No fixes for this game".
            logger.info(f"LuaTools: fixes list for {appid} -> 404 (no catalogue entry)")
            return {"success": True, "fixes": []}
        if resp.status_code != 200:
            logger.warning(f"LuaTools: fixes list for {appid} -> HTTP {resp.status_code}")
            return {"success": False, "error": f"api_error_{resp.status_code}"}
        data = resp.json() or {}
        # Response shape (from the .NET client): { appId, name, fixes: [ {id,title,
        # description,tags,hasManifest,hasFix,...} ] }. Pass fixes straight through.
        fixes = data.get("fixes", [])
        logger.info(f"LuaTools: fixes list for {appid} -> {len(fixes)} fix(es)")
        return {"success": True, "fixes": fixes, "raw": data}
    except Exception as exc:
        logger.warning(f"LuaTools: fixes list error for {appid}: {exc}")
        return {"success": False, "error": str(exc)}


async def download_luatools_fix(appid: int, fix_id: str, install_path: str,
                                slot: str = "") -> dict:
    """Resolve the signed download URL for a catalogue fix and hand it to the
    existing fix pipeline (download → extract → Proton launch-option wiring)."""
    token = await _access_token()
    if not token:
        return {"success": False,
                "error": "Connect your LuaTools account first (Settings → Connect LuaTools)."}
    try:
        client = await ensure_http_client("LuaToolsFixDL")
        resp = await client.get(
            f"https://lua.tools/api/denuvo/download?fix={quote(str(fix_id))}"
            f"&slot={quote(str(slot))}",
            headers=_auth_headers(token), timeout=30,
        )
        if resp.status_code == 401:
            return {"success": False, "error": "session_expired"}
        if resp.status_code != 200:
            return {"success": False, "error": f"api_error_{resp.status_code}"}
        signed_url = (resp.json() or {}).get("url")
        if not signed_url:
            return {"success": False, "error": "The download link was empty — try again."}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    if slot == "manifest":
        # A version manifest (not a crack): a .lua/zip whose setManifestid pins the
        # game to the build this fix targets. Install it via steamidra_lite --pin,
        # which re-homes those gids onto SLSsteam's ManifestIds → Steam re-plans the
        # depots to that (usually older) build. This is a downgrade, so the caller
        # must restart Steam for it to take effect; nothing is dropped into the game
        # dir here (that's the fix slot's job).
        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix=f"luatools_manifest_{appid}_")
        zip_path = os.path.join(tmp_dir, f"{appid}_manifest.zip")
        try:
            client = await ensure_http_client("LuaToolsManifestDL")
            async with client.stream("GET", signed_url, follow_redirects=True,
                                      timeout=60) as r:
                if r.status_code != 200:
                    return {"success": False, "error": f"download_error_{r.status_code}"}
                with open(zip_path, "wb") as fh:
                    async for chunk in r.aiter_bytes():
                        fh.write(chunk)
            from downloads import _process_and_install_lua
            await _process_and_install_lua(appid, zip_path, pin=True)
            logger.info(f"LuaTools: version manifest installed + pinned for {appid}")
            return {"success": True, "needsRestart": True}
        except Exception as exc:
            logger.warning(f"LuaTools: manifest install failed for {appid}: {exc}")
            return {"success": False, "error": str(exc)}
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # slot="fix" (default): reuse the existing apply pipeline — it streams the
    # (signed) URL, extracts into the game dir with zip-slip protection, logs the
    # [FIX] block, and the frontend computes WINEDLLOVERRIDES from the dropped DLLs.
    from fixes import apply_game_fix
    return await apply_game_fix(appid, signed_url, install_path,
                                fix_type="LuaTools Catalog")

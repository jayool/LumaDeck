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

# Make requests look like the in-client browser (same trick as Ryuu). The
# http_client stamps a default `lumadeck-v0-decky` UA on every request, which —
# combined with the browser CORS headers below — is a contradictory shape (bot UA
# + browser origin) that lua.tools' Cloudflare edge can choke on with a 502. The
# caller's UA overrides the default (urllib add_header, last write wins), so pin a
# real Steam-CEF-ish Chromium UA here.
_BROWSERISH = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36 Valve Steam Client"
    ),
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


# A 401 (or a definitively rejected refresh) marks the session REJECTED rather
# than deleting it: a single 401 can be Cloudflare having a bad minute, and
# throwing the session away would also throw away the refresh token that might
# still work. The mark lives inside the session file so it survives a restart,
# and any call that succeeds clears it.
_REJECTED_KEY = "_lumadeck_rejected"


def _mark_session_rejected() -> None:
    session = _load_session()
    if session is None or session.get(_REJECTED_KEY):
        return
    session[_REJECTED_KEY] = True
    _save_session(session)
    logger.info("LuaTools: session marked as expired (server rejected the token)")


def _clear_session_rejected() -> None:
    session = _load_session()
    if session is None or not session.get(_REJECTED_KEY):
        return
    session.pop(_REJECTED_KEY, None)
    _save_session(session)
    logger.info("LuaTools: session works again; cleared the expired mark")


def restore_session(raw: str) -> bool:
    """Re-apply a session mirrored into the settings credential store, after a
    reinstall or update wiped backend/data/. Returns True if it was written.

    _save_session has mirrored the session on every save since it was written,
    but restore_credentials_from_settings never read that mirror back — Hubcap
    and Ryuu were restored, LuaTools was not. So every LumaDeck update logged the
    user out of LuaTools.

    Only writes when there is NO current session: a live one is always newer than
    the mirror (a refresh rotates the token and saves, and the mirror is only as
    fresh as the last save that reached it), so restoring over it could hand back
    a spent refresh token.
    """
    if _load_session() is not None:
        return False
    try:
        session = json.loads(raw)
    except Exception:
        return False
    if not isinstance(session, dict) or not session.get("access_token"):
        return False
    write_text(data_path(_SESSION_FILE), json.dumps(session))
    return True


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
    """Return the lua.tools Supabase session from the CEF cookie store, or None if
    the user hasn't logged in yet.

    Prefers CDP (the Steam CEF debug port): it reads the LIVE, already-decrypted
    cookie, which CEF holds in memory ~15 s before flushing to the on-disk SQLite
    store — so the login is captured the instant it lands instead of after that
    flush. Only when the debug port isn't reachable does it fall back to the
    on-disk scrape (copy DB + openssl decrypt) that this used to do exclusively."""
    import cef_cdp
    live = cef_cdp.get_cookies()
    if live is not None:
        chunks = {c["name"]: c["value"] for c in live
                  if c.get("name", "").startswith(_TOKEN_COOKIE_PREFIX)
                  and _HOST in c.get("domain", "")}
        session = _reassemble(chunks)
        if session and session.get("access_token"):
            return session
        return None  # debug port reachable but no session yet — skip the disk

    # Debug port unreachable → on-disk fallback. Narrow the query to the session
    # cookie(s) so we don't openssl-decrypt every unrelated lua.tools cookie.
    from ryuu_cookie import _read_all_cookies_for_host
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


async def get_luatools_status() -> dict:
    """Whether we hold a USABLE LuaTools session — not merely a session file.

    This used to answer `_load_session() is not None`, i.e. "does the file
    exist". The file exists whether the token is alive or three weeks dead, so
    Settings said "Connected" to users whose session had expired and the truth
    only surfaced as a raw `session_expired` at the moment they applied a fix.

    Now it asks for a real token, which is exactly what applying a fix does: a
    live token returns instantly without touching the network, and an expired one
    goes through the refresh first. `expired` is only reported when we KNOW the
    session is dead (the server rejected it), never on a network wobble — an
    offline Deck keeps showing the last known state instead of nagging for a
    re-login it can't complete.
    """
    session = _load_session()
    if session is None:
        return {"success": True, "status": _connect_state.get("status", "idle"),
                "connected": False, "expired": False}
    token = await _access_token()
    # Re-read: _access_token may have refreshed (clearing nothing) or marked the
    # session rejected, so the copy loaded above can be stale by now.
    after = _load_session() or {}
    expired = bool(after.get(_REJECTED_KEY))
    return {"success": True, "status": _connect_state.get("status", "idle"),
            "connected": bool(token) and not expired, "expired": expired}


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
    # Drop the settings-store mirror too. _save_session mirrors on every save,
    # and restore_credentials_from_settings now reads that mirror back on every
    # plugin load — so deleting only the file left the logout to be undone on the
    # next Steam restart, handing the user back the session they just discarded.
    try:
        from api_manifest import _forget_cred
        _forget_cred("luatools_session")
    except Exception as exc:
        logger.warning(f"LuaTools: could not clear the session mirror: {exc}")
    # Also clear the LIVE CEF cookie. Deleting the on-disk store (or our session
    # file) doesn't drop CEF's in-memory copy, so without this the browser stays
    # logged in and lua.tools shows the account as signed in on the next login.
    try:
        import cef_cdp
        n = cef_cdp.delete_cookies_matching(_TOKEN_COOKIE_PREFIX, _HOST)
        if n > 0:
            logger.info(f"LuaTools: cleared {n} live CEF session cookie(s)")
    except Exception as exc:
        logger.info(f"LuaTools: CEF cookie clear skipped: {exc}")
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
                # Supabase returns `expires_in`; `expires_at` is added by its JS
                # client, not the endpoint. Without it the check above reads the
                # brand-new session as already stale and we'd refresh on EVERY
                # call, so derive it when the server didn't send one.
                if not new_session.get("expires_at"):
                    try:
                        new_session["expires_at"] = int(time.time()) + int(new_session.get("expires_in") or 3600)
                    except (TypeError, ValueError):
                        new_session["expires_at"] = int(time.time()) + 3600
                _save_session(new_session)
                return new_session.get("access_token")
            # 4xx = the refresh token itself is dead (spent, revoked, expired):
            # no retry will fix it, so record it and let the UI offer a re-login.
            # 5xx / network errors are transient — keep quiet and try again later.
            if 400 <= resp.status_code < 500:
                _mark_session_rejected()
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
    # The real LuaTools client hits this PUBLIC endpoint with a PLAIN request — no
    # Authorization, and crucially NO Origin/Referer/Sec-Fetch. Our earlier
    # browser-CORS header set made a server-side request look like a cross-origin
    # browser fetch, which lua.tools' Cloudflare edge answered with a 502 almost
    # every time. So mimic the plain client: just a normal UA + Accept, nothing
    # else (no Bearer — the listing is public and a stale token only risks a 401).
    headers = {
        "User-Agent": _BROWSERISH.get("User-Agent", ""),
        "Accept": "application/json, text/plain, */*",
    }
    url = f"https://lua.tools/api/denuvo/fixes?appid={appid}"
    client = await ensure_http_client("LuaToolsFixes")

    # Retry transient 5xx a few times with a short backoff (harmless if the header
    # shape above was the real cause). 404 (no entry) / other 4xx are terminal.
    last_status = 0
    last_err = ""
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=headers, timeout=8)
        except Exception as exc:
            last_err = str(exc)
            last_status = 0
        else:
            if resp.status_code == 200:
                data = resp.json() or {}
                # Response shape (from the .NET client): { appId, name, fixes: [
                # {id,title,description,tags,hasManifest,hasFix,...} ] }. Passed through.
                fixes = data.get("fixes", [])
                logger.info(
                    f"LuaTools: fixes list for {appid} -> {len(fixes)} fix(es)"
                    + ("" if attempt == 0 else f" (attempt {attempt + 1})")
                )
                return {"success": True, "fixes": fixes, "raw": data}
            if resp.status_code == 404:
                # No catalogue entry (same as the web page lua.tools/fixes/<appid>).
                logger.info(f"LuaTools: fixes list for {appid} -> 404 (no catalogue entry)")
                return {"success": True, "fixes": []}
            last_status = resp.status_code
            # Log a snippet of the error body — a CF/Worker 5xx page usually names
            # the real cause (ray id, worker exception), so it's diagnosable remotely.
            try:
                body = " ".join((resp.text or "")[:400].split())
            except Exception:
                body = "<unreadable>"
            logger.warning(
                f"LuaTools: fixes list for {appid} -> HTTP {resp.status_code} body={body!r}"
            )
            if resp.status_code < 500:
                break  # a non-5xx error is terminal
        if attempt < 2:
            await asyncio.sleep(0.5 * (attempt + 1))

    if last_status:
        return {"success": False, "error": f"api_error_{last_status}"}
    logger.warning(f"LuaTools: fixes list for {appid} failed after retries: {last_err}")
    return {"success": False, "error": last_err or "request_failed"}


async def download_luatools_fix(appid: int, fix_id: str, install_path: str,
                                slot: str = "", title: str = "",
                                online: bool = False) -> dict:
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
            _mark_session_rejected()
            return {"success": False, "error": "session_expired"}
        if resp.status_code != 200:
            return {"success": False, "error": f"api_error_{resp.status_code}"}
        _clear_session_rejected()
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
    # Use the catalogue fix's real title as the recorded fix type (falls back to a
    # generic label), and pass the catalogue's online tag so the installed entry is
    # filed under the right tab even for EOS/EpicFix fixes (no FakeAppId).
    return await apply_game_fix(appid, signed_url, install_path,
                                fix_type=(title.strip() or "LuaTools Catalog"),
                                online=bool(online))

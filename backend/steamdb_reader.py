"""SteamDB reader: fetch the feed / pages that versions.py parses.

SteamDB sits behind Cloudflare. A plain request from the backend is answered
with a JavaScript challenge ("Just a moment..."), never the page. Steam's own
CEF browser is a real browser, so it passes. Reading order, per URL:

  1. cache   — ~/.cache/lumadeck/steamdb/, one file per path, with a TTL
               (feed 1 h, depot history 6 h, build page 24 h: a build's
               depot list never changes).
  2. direct  — one HTTP GET from the backend. Kept only so a probe can show
               whether it works; after one challenge it is skipped for an
               hour instead of costing every read a round trip.
  3. browser — an off-screen BrowserView (cef_cdp.HiddenView) is created
               through SharedJSContext and NAVIGATED to the page; the HTML
               is read from the loaded document. A real navigation is the
               only thing that can pass a Cloudflare JS challenge: an in-page
               fetch() of a challenged path just gets the 403 challenge page
               back (measured 2026-09-21: the app page loads, fetch() of
               /depot/…/manifests/ from it answers 403 + 10.9 KB of
               challenge). The feed (/api/PatchnotesRSS/) is XML; a navigation would
               render it through the XML viewer, so it alone is read with
               fetch() from a page already on steamdb.info; every other
               path, /api/RenderAppSection/ included, is a navigation. The view lives
               for the Reader's life and is destroyed on close().

If the hidden page is still on a challenge after 20 s it is an interactive
one: the result says needs_user and carries challenge_url — the UI has to
open THAT url visibly once; the clearance cookie is shared with the hidden
view on the next try.

Nothing is guessed from a bad answer: a challenge page, an HTTP error or an
empty body is reported as such and never cached.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

from paths import real_home

BASE = "https://steamdb.info"
CACHE_DIR = os.path.join(real_home(), ".cache/lumadeck/steamdb")
TTL_FEED = 3600
TTL_DEPOT = 6 * 3600
TTL_BUILD = 24 * 3600
DIRECT_BACKOFF_S = 3600

# Markers of Cloudflare's CHALLENGE page only. Not "challenge-platform" or
# "cf-chl" on their own: normal pages behind Cloudflare bot management carry
# /cdn-cgi/challenge-platform/scripts/jsd/main.js too, and would all count.
_CHALLENGE_RE = re.compile(
    r"Just a moment|chl_page|_cf_chl_opt|cf-turnstile|challenge-running|challenge-error-text|"
    r"Attention Required! \| Cloudflare", re.IGNORECASE)

_direct_blocked_until = 0.0


def feed_path(appid: int) -> str:
    return f"/api/PatchnotesRSS/?appid={int(appid)}"


def depot_path(depot: int) -> str:
    return f"/depot/{int(depot)}/manifests/"


def build_path(buildid: int) -> str:
    return f"/patchnotes/{int(buildid)}/"


def app_url(appid: int) -> str:
    return f"{BASE}/app/{int(appid)}/"


def patchnotes_path(appid: int) -> str:
    return f"/app/{int(appid)}/patchnotes/"


# The app's builds table (<tbody id="js-builds">) is filled by script only
# once the Patches tab is activated — in Steam's browser the URL alone does
# not do it (measured: 8 build links before clicking the tab, 74 after). So
# the reader clicks the tab, then waits for the rows to settle.
BUILDS_PREPARE_JS = """(function(){try{
  var a=document.querySelector('a.tabnav-tab[href$="/patchnotes/"]')
       ||[].slice.call(document.querySelectorAll('a[role="tab"]')).filter(function(x){return /\\/patchnotes\\/?$/.test(x.getAttribute('href')||'');})[0];
  if(!a) return 'no tab';
  a.click(); return 'ok';
}catch(e){return 'error: '+String(e);}})()"""
BUILDS_SETTLE_JS = "document.querySelectorAll('#js-builds tr').length"
LIST_RETRIES = 4          # re-requests of an empty list (tab clicks)
LIST_RETRY_SLEEP_S = 3.0  # pause before each, for Cloudflare's cookie
LIST_WAIT_S = 6.0         # settle wait per attempt

# When the table does not fill: what the page looks like, for the log.
_UNFILLED_SNAPSHOT_JS = """(function(){try{
  var q=function(s){return document.querySelector(s);};
  var nav=(performance.getEntriesByType&&performance.getEntriesByType('navigation')[0])||{};
  var pn=q('#js-patchnotes')||q('#patchnotes');
  var tb=q('#js-builds');
  var tab=q('a.tabnav-tab[href$="/patchnotes/"]');
  return JSON.stringify({href:location.href,rs:document.readyState,size:document.documentElement.outerHTML.length,
    navType:nav.type||'',cookies:document.cookie.split(';').map(function(c){return c.split('=')[0].trim();}),
    tab:tab?(tab.className+' '+(tab.getAttribute('aria-selected')||'')):null,
    paneActive:pn?(pn.closest('.tab-pane')||{}).className:null,
    tbody:tb?tb.outerHTML.slice(0,400):null,
    paneText:pn?pn.textContent.replace(/\\s+/g,' ').slice(0,600):null,
    loaders:[].slice.call(document.querySelectorAll('.loader')).length,
    });
}catch(e){return JSON.stringify({err:String(e)});}})()"""


def steamdb_cookies() -> list:
    """SteamDB's cookies in Steam's browser (names, expiry, flags; never the
    values), straight from CEF's live jar — HttpOnly ones included, which
    document.cookie never shows. Which Cloudflare cookie exists, and for how
    long, decides whether /api/ answers 200 or 403."""
    import cef_cdp
    out = []
    for c in cef_cdp.get_cookies() or []:
        if "steamdb.info" not in str(c.get("domain", "")):
            continue
        exp = c.get("expires")
        out.append({
            "name": c.get("name"), "domain": c.get("domain"), "path": c.get("path"),
            "httpOnly": c.get("httpOnly"), "secure": c.get("secure"),
            "expires": time.strftime("%H:%M:%S", time.gmtime(exp)) if isinstance(exp, (int, float)) and exp > 0 else "session",
            "minutes_left": int((exp - time.time()) / 60) if isinstance(exp, (int, float)) and exp > 0 else None,
        })
    return out


def classify(status: int, text: str) -> str:
    """ok | challenge | http_error | empty — what an answer really is."""
    head = (text or "")[:40000]
    if _CHALLENGE_RE.search(head):
        return "challenge"
    if status != 200:
        return "http_error"
    if not (text or "").strip():
        return "empty"
    return "ok"


@dataclass
class Fetched:
    path: str
    outcome: str = "error"      # ok | challenge | http_error | empty | needs_user | error
    transport: str = "none"     # cache | direct | browser | none
    status: int = 0
    text: str = ""
    ms: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    def summary(self) -> dict:
        d = asdict(self)
        d["bytes"] = len(self.text.encode("utf-8", "replace"))
        d.pop("text", None)
        if not self.ok and self.text:
            # What the bad answer looked like: its <title> and its first words.
            m = re.search(r"<title[^>]*>(.*?)</title>", self.text, re.DOTALL | re.IGNORECASE)
            d["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else ""
            plain = re.sub(r"<script.*?</script>|<style.*?</style>", " ", self.text, flags=re.DOTALL | re.IGNORECASE)
            plain = re.sub(r"<[^>]+>", " ", plain)
            d["snippet"] = re.sub(r"\s+", " ", plain).strip()[:300]
            d["marker"] = (_CHALLENGE_RE.search(self.text[:40000]) or [None])[0]
        return d


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_file(cache_dir: str, path: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/")) or "root"
    return os.path.join(cache_dir, name + ".json")


def cache_get(path: str, ttl: float, cache_dir: str = CACHE_DIR,
              now: Callable[[], float] = time.time) -> Optional[Tuple[int, str]]:
    try:
        with open(_cache_file(cache_dir, path), "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("path") != path or now() - float(d.get("fetched", 0)) > ttl:
            return None
        return int(d.get("status", 200)), str(d.get("text", ""))
    except Exception:
        return None


def cache_put(path: str, status: int, text: str, cache_dir: str = CACHE_DIR,
              now: Callable[[], float] = time.time) -> None:
    try:
        os.makedirs(cache_dir, exist_ok=True)
        fn = _cache_file(cache_dir, path)
        tmp = fn + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"path": path, "status": status, "fetched": now(), "text": text}, f)
        os.replace(tmp, fn)
    except Exception as exc:
        logger.info(f"SteamDB cache write failed for {path}: {exc}")


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

async def _direct_get(url: str) -> Tuple[int, str]:
    from http_client import ensure_http_client
    client = await ensure_http_client("steamdb")
    resp = await client.get(url, timeout=15, headers={
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
    })
    data = getattr(resp, "data", b"") or b""
    return int(resp.status_code), data.decode("utf-8", "replace")


def _default_view_factory(appid: int):
    import cef_cdp
    return cef_cdp.HiddenView("lumadeck_steamdb")


class Reader:
    """One reading session for one app. Holds the browser view between reads
    so a probe or a resolution pays the challenge wait once. close() it."""

    def __init__(self, appid: int, *, cache_dir: str = CACHE_DIR,
                 direct: Optional[Callable] = None, view_factory: Optional[Callable] = None,
                 use_direct: bool = True, now: Callable[[], float] = time.time):
        self.appid = int(appid)
        self.cache_dir = cache_dir
        self._direct = direct or _direct_get
        self._view_factory = view_factory or _default_view_factory
        self._use_direct = use_direct
        self._now = now
        self._view = None
        self._view_err: Optional[str] = None   # sticky: once the view failed, say so and stop trying
        self.view_state: dict = {}             # what wait_ready saw last (for the probe)
        self.challenge_url: Optional[str] = None  # the page only the user can get past
        self.fetches: List[Fetched] = []

    # -- steps -------------------------------------------------------------

    def _from_cache(self, path: str, ttl: float) -> Optional[Fetched]:
        hit = cache_get(path, ttl, self.cache_dir, self._now)
        if hit is None:
            return None
        return Fetched(path=path, outcome="ok", transport="cache", status=hit[0], text=hit[1])

    async def _via_direct(self, path: str) -> Fetched:
        global _direct_blocked_until
        t0 = time.monotonic()
        f = Fetched(path=path, transport="direct")
        try:
            status, text = await self._direct(BASE + path)
            f.status, f.text = status, text
            f.outcome = classify(status, text)
        except Exception as exc:
            f.outcome, f.error = "error", str(exc)
        f.ms = int((time.monotonic() - t0) * 1000)
        if f.outcome == "challenge" or f.status in (403, 429, 503):
            # A challenge page or a bare block (SteamDB answers the backend
            # 403 with an empty body): don't pay this round trip again for an hour.
            _direct_blocked_until = self._now() + DIRECT_BACKOFF_S
        return f

    def _open_view(self) -> Optional[str]:
        """Make sure a usable page on steamdb.info exists. Returns None when
        ready, else the reason ('needs_user' when only the user can fix it)."""
        if self._view is not None:
            return None
        if self._view_err:
            return self._view_err
        try:
            view = self._view_factory(self.appid)
        except Exception as exc:
            self._view_err = f"error: {exc}"
            return self._view_err
        err = view.open(app_url(self.appid))
        if err:
            self._view_err = f"error: {err}"
            return self._view_err
        st = view.wait_ready(20.0, expect_url=app_url(self.appid))
        self.view_state = dict(st)
        state = st.get("state")
        if state != "ready":
            view.close()
            if state == "challenge":
                self._view_err = "needs_user"
                self.challenge_url = app_url(self.appid)
            else:
                self._view_err = f"error: page not ready ({state}: {st.get('title') or st.get('err') or st.get('href')})"
            return self._view_err
        self._view = view
        return None

    def _read_by_navigation(self, path: str, f: Fetched, settle_js: Optional[str] = None,
                            prepare_js: Optional[str] = None) -> None:
        """HTML pages: navigate the hidden view there and take the document.
        needs_user when the page stays on a challenge. `prepare_js` runs once
        the page is ready (e.g. click a tab); `settle_js` counts the rows a
        page fills by script after that, and the document is read once the
        count is stable."""
        st = self._view.navigate(BASE + path, 20.0)
        self.view_state = dict(st)
        state = st.get("state")
        if state == "ready":
            if settle_js:
                # The page's own request for the list fires at load and gets
                # a 403 from Cloudflare's bot check until the cookie its
                # script sets a few seconds later exists (measured 2026-09-21:
                # a tab click ~35 s after load filled the table at once, a
                # click at load never did). So: let the load request run,
                # and if the list is still empty re-request it (prepare_js,
                # the tab click) every few seconds, a handful of times.
                import cef_cdp
                attempts = []
                n = self._view.wait_settled(settle_js, LIST_WAIT_S)
                attempts.append(n)
                tries = 0
                while n == 0 and prepare_js and tries < LIST_RETRIES:
                    tries += 1
                    time.sleep(LIST_RETRY_SLEEP_S)
                    try:
                        self.view_state["prepared"] = cef_cdp.evaluate(self._view.ws, prepare_js, timeout=5, await_promise=False)
                    except Exception as exc:
                        self.view_state["prepared"] = f"error: {exc}"
                    n = self._view.wait_settled(settle_js, LIST_WAIT_S)
                    attempts.append(n)
                self.view_state["settled"] = n
                self.view_state["attempts"] = attempts
            f.status, f.text = 200, self._view.html()
            f.outcome = classify(f.status, f.text)
            if settle_js and f.outcome == "ok" and not self.view_state.get("settled"):
                # The list never filled: report it as empty and never cache
                # it (an empty shell cached for an hour hid every retry).
                f.outcome = "empty"
                f.error = f"list did not fill (prepare={self.view_state.get('prepared')!r})"
                try:
                    import cef_cdp
                    snap = cef_cdp.evaluate(self._view.ws, _UNFILLED_SNAPSHOT_JS, timeout=5, await_promise=False)
                except Exception as exc:
                    snap = f"snapshot failed: {exc}"
                self.view_state["snapshot"] = snap
                logger.info(f"SteamDB {path}: list did not fill after {self.view_state.get('attempts')}; {snap}")
                try:
                    self.view_state["cookies"] = steamdb_cookies()
                    logger.info(f"SteamDB cookies now: {self.view_state['cookies']}")
                except Exception as exc:
                    logger.info(f"SteamDB cookies: {exc}")
        elif state == "challenge":
            f.outcome, f.status = "needs_user", 403
            f.error = str(st.get("title") or "")
            self.challenge_url = BASE + path
        else:
            f.outcome = "error"
            f.error = f"page not ready ({state}: {st.get('title') or st.get('err') or st.get('href')})"

    def _browser_fetch(self, path: str, settle_js: Optional[str] = None,
                       prepare_js: Optional[str] = None) -> Fetched:
        t0 = time.monotonic()
        f = Fetched(path=path, transport="browser")
        why = self._open_view()
        if why:
            f.outcome = "needs_user" if why == "needs_user" else "error"
            f.error = "" if why == "needs_user" else why
        else:
            try:
                if path.startswith("/api/PatchnotesRSS/"):
                    # XML: a navigation would show it through the XML viewer.
                    status, text = self._view.fetch(path)
                    f.status, f.text = status, text
                    f.outcome = classify(status, text)
                    if f.outcome == "challenge":
                        f.outcome = "needs_user"
                        self.challenge_url = BASE + path
                else:
                    self._read_by_navigation(path, f, settle_js, prepare_js)
            except Exception as exc:
                f.outcome, f.error = "error", str(exc)
        f.ms = int((time.monotonic() - t0) * 1000)
        return f

    async def _via_browser(self, path: str, settle_js: Optional[str] = None,
                           prepare_js: Optional[str] = None) -> Fetched:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._browser_fetch, path, settle_js, prepare_js)

    # -- public --------------------------------------------------------------

    async def get(self, path: str, ttl: float, settle_js: Optional[str] = None,
                  prepare_js: Optional[str] = None,
                  validate: Optional[Callable[[str], bool]] = None) -> Fetched:
        """`prepare_js` / `settle_js`: see _read_by_navigation. A page that
        needs them is never read directly (the backend would only get the
        empty shell). `validate(text)` False turns a 200 into "empty": an
        error page served with 200, or a fragment without the rows — never
        cached."""
        f = self._from_cache(path, ttl)
        if f is None and not (settle_js or prepare_js) and self._use_direct and self._now() >= _direct_blocked_until:
            f = await self._via_direct(path)
            if not f.ok:
                self.fetches.append(f)
                f = None
        if f is None:
            f = await self._via_browser(path, settle_js, prepare_js)
        if f.ok and validate is not None and not validate(f.text):
            f.outcome = "empty"
            f.error = f"unexpected content: {re.sub(r'<[^>]+>', ' ', f.text[:600]).strip()[:200]!r}"
        if f.ok and f.transport != "cache":
            cache_put(path, f.status, f.text, self.cache_dir, self._now)
        self.fetches.append(f)
        logger.info(f"SteamDB {f.transport} {f.path}: {f.outcome} {f.status} "
                    f"{len(f.text)} chars {f.ms} ms{(' ' + f.error) if f.error else ''}")
        return f

    async def close(self) -> None:
        v, self._view = self._view, None
        if v is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, v.close)

    async def builds_page(self, ttl: float = TTL_FEED) -> Fetched:
        """The app's builds table: the app page, whose script requests
        /api/RenderAppSection/?section=patchnotes (public builds) into
        <tbody id="js-builds">; re-requested through the tab while empty.
        (That fragment cannot be navigated to: SteamDB answers an "Error"
        page — measured.)"""
        import versions
        has_rows = lambda text: bool(versions.parse_builds_page(text))  # noqa: E731
        f = await self.get(patchnotes_path(self.appid), ttl, BUILDS_SETTLE_JS, BUILDS_PREPARE_JS,
                           validate=has_rows)
        logger.info(f"SteamDB builds for {self.appid}: {f.outcome}; attempts={self.view_state.get('attempts')}")
        return f

    @property
    def needs_user(self) -> bool:
        return any(f.outcome == "needs_user" for f in self.fetches)


# ---------------------------------------------------------------------------
# Probe (dev): read everything for one app and run the translator on a sample
# ---------------------------------------------------------------------------

async def probe(appid: int, max_depots: int = 6) -> dict:
    """Read the feed, the depot histories and one build page for `appid`,
    run versions.resolve_build on the OLDEST build in the feed, and report
    every fetch (transport, ms, bytes, outcome). Depots come from the
    installed .acf; if the game is not installed, from the newest build's
    page. Written to ~/.cache/lumadeck/steamdb/probe_<appid>.json too."""
    import pins
    import versions

    appid = int(appid)
    t0 = time.monotonic()
    out: dict = {"success": True, "appid": appid, "fetches": [], "builds": 0,
                 "depots": {}, "sample": None, "needs_user": False, "notes": []}
    reader = Reader(appid)
    try:
        out["cookies_before"] = steamdb_cookies()
        feed = await reader.get(feed_path(appid), TTL_FEED)
        builds = versions.parse_builds_feed(feed.text) if feed.ok else []
        out["builds"] = len(builds)
        if builds:
            out["newest"] = {"buildid": builds[0].buildid, "date": builds[0].time.isoformat(), "label": builds[0].label}
            out["oldest"] = {"buildid": builds[-1].buildid, "date": builds[-1].time.isoformat(), "label": builds[-1].label}
        elif feed.ok:
            out["notes"].append("feed read but no builds parsed")

        depots = sorted(pins.installed_depots(appid).keys())
        out["depots_from"] = "acf" if depots else "none"
        if not depots and builds:
            page = await reader.get(build_path(builds[0].buildid), TTL_BUILD)
            depots = sorted(versions.parse_build_depots(page.text).keys()) if page.ok else []
            out["depots_from"] = "newest build page" if depots else "none"
        if len(depots) > max_depots:
            out["notes"].append(f"{len(depots)} depots, probing the first {max_depots}")
            depots = depots[:max_depots]

        history: Dict[int, List[versions.ManifestRow]] = {}
        for d in depots:
            page = await reader.get(depot_path(d), TTL_DEPOT)
            rows = versions.parse_depot_history(page.text, d) if page.ok else []
            history[d] = rows
            pub = [r for r in rows if r.public]
            out["depots"][str(d)] = {
                "rows": len(rows), "public": len(pub),
                "newest": pub[0].time.isoformat() if pub else None,
                "oldest": pub[-1].time.isoformat() if pub else None,
            }

        if builds and depots:
            sample = builds[-1]
            page = await reader.get(build_path(sample.buildid), TTL_BUILD)
            build_depots = versions.parse_build_depots(page.text) if page.ok else {}
            res = versions.resolve_build(sample, depots, history, build_depots)
            out["sample"] = {
                "buildid": sample.buildid, "date": sample.time.isoformat(), "label": sample.label,
                "build_page_depots": {str(k): str(v) for k, v in build_depots.items()},
                "resolutions": {str(d): {"gid": str(r.gid) if r.gid is not None else None,
                                         "status": r.status, "why": r.why}
                                for d, r in res.items()},
                "confirmed": len(versions.pins_from(res)), "of": len(depots),
            }

        # The full builds table (all of them, all branches), classified by
        # branch against the depot rows: public / other / unknown (no row at
        # the build's time — the depot did not change, or it is off the
        # visible history).
        page = await reader.builds_page()
        if page.ok:
            all_builds = versions.parse_builds_page(page.text)
            rows_all = [r for rows in history.values() for r in rows]
            by_branch: Dict[str, int] = {}
            for b in all_builds:
                br = versions.build_branch(b.time, rows_all) or "unknown"
                by_branch[br] = by_branch.get(br, 0) + 1
            feed_ids = {b.buildid for b in builds}
            out["builds_page"] = {
                "settled": reader.view_state.get("settled"), "prepared": reader.view_state.get("prepared"),
                "builds": len(all_builds), "with_label": sum(1 for b in all_builds if b.label),
                "newest": {"buildid": all_builds[0].buildid, "date": all_builds[0].time.isoformat(), "label": all_builds[0].label} if all_builds else None,
                "oldest": {"buildid": all_builds[-1].buildid, "date": all_builds[-1].time.isoformat(), "label": all_builds[-1].label} if all_builds else None,
                "in_feed": sum(1 for b in all_builds if b.buildid in feed_ids),
                "by_branch": by_branch,
                "first_rows": [{"buildid": b.buildid, "date": b.time.isoformat(), "title": b.title, "label": b.label} for b in all_builds[:4]],
            }
            if not all_builds:
                j = page.text.find('id="js-builds"')
                out["builds_page"]["snippet"] = page.text[j:j + 1500] if j >= 0 else "(no js-builds tbody)"
        else:
            out["builds_page"] = {"outcome": page.outcome, "error": page.error}
    except Exception as exc:
        out["success"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning(f"SteamDB probe {appid} failed: {exc}")
    finally:
        await reader.close()
    out["fetches"] = [f.summary() for f in reader.fetches]
    out["view"] = reader.view_state
    out["cookies_after"] = steamdb_cookies()
    out["challenge_url"] = reader.challenge_url
    out["needs_user"] = reader.needs_user
    out["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    logger.info(f"SteamDB probe {appid}: {json.dumps(out)}")
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR, f"probe_{appid}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
    except Exception:
        pass
    return out

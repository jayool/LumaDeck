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
               challenge). The feed (/api/…) is XML, which a navigation would
               render through the XML viewer, so it alone is read with
               fetch() from a page already on steamdb.info. The view lives
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

    def _read_by_navigation(self, path: str, f: Fetched) -> None:
        """HTML pages: navigate the hidden view there and take the document.
        needs_user when the page stays on a challenge."""
        st = self._view.navigate(BASE + path, 20.0)
        self.view_state = dict(st)
        state = st.get("state")
        if state == "ready":
            f.status, f.text = 200, self._view.html()
            f.outcome = classify(f.status, f.text)
            if f.outcome == "challenge":
                f.outcome = "needs_user"
                self.challenge_url = BASE + path
        elif state == "challenge":
            f.outcome, f.status = "needs_user", 403
            f.error = str(st.get("title") or "")
            self.challenge_url = BASE + path
        else:
            f.outcome = "error"
            f.error = f"page not ready ({state}: {st.get('title') or st.get('err') or st.get('href')})"

    def _browser_fetch(self, path: str) -> Fetched:
        t0 = time.monotonic()
        f = Fetched(path=path, transport="browser")
        why = self._open_view()
        if why:
            f.outcome = "needs_user" if why == "needs_user" else "error"
            f.error = "" if why == "needs_user" else why
        else:
            try:
                if path.startswith("/api/"):
                    status, text = self._view.fetch(path)
                    f.status, f.text = status, text
                    f.outcome = classify(status, text)
                    if f.outcome == "challenge":
                        f.outcome = "needs_user"
                        self.challenge_url = BASE + path
                else:
                    self._read_by_navigation(path, f)
            except Exception as exc:
                f.outcome, f.error = "error", str(exc)
        f.ms = int((time.monotonic() - t0) * 1000)
        return f

    async def _via_browser(self, path: str) -> Fetched:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._browser_fetch, path)

    # -- public --------------------------------------------------------------

    async def get(self, path: str, ttl: float) -> Fetched:
        f = self._from_cache(path, ttl)
        if f is None and self._use_direct and self._now() >= _direct_blocked_until:
            f = await self._via_direct(path)
            if not f.ok:
                self.fetches.append(f)
                f = None
        if f is None:
            f = await self._via_browser(path)
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
    except Exception as exc:
        out["success"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning(f"SteamDB probe {appid} failed: {exc}")
    finally:
        await reader.close()
    out["fetches"] = [f.summary() for f in reader.fetches]
    out["view"] = reader.view_state
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

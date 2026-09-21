"""Game versions: turn SteamDB's build history into per-depot manifest gids.

Steam installs a *version* only as "this manifest gid for this depot". Valve
publishes no build history, so "the build of 20 July" has to be translated
into gids by whoever wrote them down at the time. SteamDB did, and exposes two
things we read (through Steam's own browser — Cloudflare blocks the backend):

  1. The app's builds feed, ``steamdb.info/api/PatchnotesRSS/?appid=<app>``:
     one <item> per PUBLIC-branch build with its id (in the link), its publish
     time (<pubDate>, matches the depot history to the second) and the studio's
     version string when they set one (<description>).
  2. A depot's history, ``steamdb.info/depot/<depot>/manifests/``: one table
     row per manifest the depot ever had — ISO time (``data-time``), gid (in
     the ``changeid=M:<gid>`` link) and the branch when it is NOT public
     (``<code class="js-branch">``). ~50 rows without a SteamDB login.

The join (``resolve_build``): for every depot the user installs, the public row
at the build's time (±3 s) is that depot's gid in that build; if there is none
the depot did not change in that build and its gid is the newest public row
BEFORE the build; if the table has no such row either, the gid is unknown and
the caller keeps the installed one and says so. Nothing is guessed by "nearest
date" — a change AFTER the build can never be picked.

This module is pure (stdlib only, no network, no Steam); the fetch lives in the
frontend and ``pins.py`` does the pinning. Fixtures: tests/fixtures/steamdb/.
Measured 2026-09-21 on app 2545360: 9/10 feed builds match a public row to the
second (the 10th was cut from the capture).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

# A build's publish time and its depot rows differ by ~1 s in the captures.
MATCH_WINDOW_S = 3.0
PUBLIC = "public"

_BUILD_LINK_RE = re.compile(r"/patchnotes/(\d+)/?")
_BUILD_TITLE_RE = re.compile(r"\bBuild\s+#?(\d+)", re.IGNORECASE)
_DESC_SUFFIX_RE = re.compile(r"\s*\(SteamDB Build \d+\)\s*$")
_GID_RE = re.compile(r"^\d{1,20}$")
# The feed is read with regexes, not xml.etree, and dates/entities are decoded
# here, not with email.utils / html: Decky's bundled Python only carries the
# modules the loader itself pulls in ("No module named 'xml.etree'" on the
# Deck, 2026-09-21), so this module imports nothing beyond re/json/datetime.
_ITEM_RE = re.compile(r"<item\b[^>]*>(.*?)</item>", re.DOTALL | re.IGNORECASE)
_CDATA_RE = re.compile(r"^\s*<!\[CDATA\[(.*?)\]\]>\s*$", re.DOTALL)
_ENTITY_RE = re.compile(r"&(#x[0-9a-fA-F]+|#\d+|amp|lt|gt|quot|apos|nbsp);")
_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": "\xa0"}
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_RFC2822_RE = re.compile(
    r"(?:[A-Za-z]{3},\s*)?(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?"
    r"\s*(?:([+-])(\d{2})(\d{2})|UT|UTC|GMT|Z)?\s*$")
_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL)
_ROW_TIME_RE = re.compile(r'data-time="([^"]+)"')
_ROW_GID_RE = re.compile(r"/depot/(\d+)/history/\?changeid=M:(\d+)")
_ROW_BRANCH_RE = re.compile(r'<code class="js-branch">([^<]*)</code>')
_DEPOTS_JSON_RE = re.compile(r"const depots = (\[.*?\]);", re.DOTALL)
_BUILDS_TBODY_RE = re.compile(r'<tbody[^>]*id="js-builds"[^>]*>(.*?)</tbody>', re.DOTALL)
_BUILD_ROW_RE = re.compile(r'<tr\b[^>]*data-date="(\d+)"[^>]*>(.*?)</tr>', re.DOTALL)
_TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.DOTALL)
_SVG_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Build:
    buildid: int
    time: datetime                     # aware, UTC
    title: str                         # feed title ("<game> update for 8 September 2026")
    label: Optional[str] = None        # studio's version string, if any

    @property
    def date(self) -> str:
        return self.time.date().isoformat()


@dataclass(frozen=True)
class ManifestRow:
    depot: int
    gid: int
    time: datetime                     # aware, UTC
    branch: str = PUBLIC

    @property
    def public(self) -> bool:
        return self.branch == PUBLIC


@dataclass(frozen=True)
class Resolution:
    depot: int
    gid: Optional[int]                 # None when unconfirmed
    status: str                        # "changed" | "unchanged" | "unconfirmed"
    row_time: Optional[datetime] = None
    why: str = ""

    @property
    def confirmed(self) -> bool:
        return self.gid is not None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _unescape(text: str) -> str:
    def rep(m):
        e = m.group(1)
        if e.startswith("#x"):
            code = int(e[2:], 16)
        elif e.startswith("#"):
            code = int(e[1:])
        else:
            return _ENTITIES[e]
        try:
            return chr(code)
        except (ValueError, OverflowError):
            return m.group(0)
    return _ENTITY_RE.sub(rep, text)


def parse_rfc2822(text: str) -> Optional[datetime]:
    """RSS <pubDate> ("Tue, 08 Sep 2026 12:53:52 +0000") -> aware UTC
    datetime, or None when it does not parse."""
    m = _RFC2822_RE.match((text or "").strip())
    if not m:
        return None
    day, mon, year, hh, mm, ss, sign, oh, om = m.groups()
    month = _MONTHS.get(mon.lower())
    if not month:
        return None
    try:
        dt = datetime(int(year), month, int(day), int(hh), int(mm), int(ss or 0), tzinfo=timezone.utc)
    except ValueError:
        return None
    if sign:
        off = timedelta(hours=int(oh), minutes=int(om))
        dt = dt - off if sign == "+" else dt + off
    return dt


def _tag_text(block: str, tag: str) -> str:
    """Text of the first <tag>…</tag> in `block`, CDATA unwrapped and XML
    entities decoded; "" when absent."""
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    raw = m.group(1)
    c = _CDATA_RE.match(raw)
    if c:
        return c.group(1).strip()
    return _unescape(raw).strip()


def parse_builds_feed(xml_text: str) -> List[Build]:
    """The PatchnotesRSS feed -> builds, newest first (feed order kept).

    Tolerant: an <item> without a build id or a parseable date is skipped,
    never invented. Duplicated build ids keep the first occurrence."""
    out: List[Build] = []
    seen = set()
    for m_item in _ITEM_RE.finditer(xml_text or ""):
        item = m_item.group(1)
        link = _tag_text(item, "link")
        title = _tag_text(item, "title")
        desc = _tag_text(item, "description")
        m = _BUILD_LINK_RE.search(link) or _BUILD_TITLE_RE.search(title) or _BUILD_TITLE_RE.search(desc)
        if not m:
            continue
        buildid = int(m.group(1))
        if buildid in seen:
            continue
        when = parse_rfc2822(_tag_text(item, "pubDate"))
        if when is None:
            continue
        label = _DESC_SUFFIX_RE.sub("", desc).strip()
        if not label or _BUILD_TITLE_RE.fullmatch(label.replace("SteamDB ", "")):
            label = None
        seen.add(buildid)
        out.append(Build(buildid=buildid, time=when, title=title, label=label))
    return out


def parse_builds_page(html_text: str) -> List[Build]:
    """The app's builds table (``steamdb.info/app/<app>/patchnotes/``, the
    <tbody id="js-builds"> SteamDB fills when the Patches tab is active) ->
    builds, page order (newest first). Every build SteamDB ever saw for the
    app, not just the feed's 10, and not only the public branch — the
    caller tells branches apart with build_branch() against the depot rows.
    Row: <tr data-date="<epoch>"> date-link / day / time / title / two icon
    cells / build id. "No title" is no label. Measured 2026-09-21 on app
    2379780: 33 rows vs 10 in the feed."""
    m = _BUILDS_TBODY_RE.search(html_text or "")
    if not m:
        return []
    out: List[Build] = []
    seen = set()
    for row in _BUILD_ROW_RE.finditer(m.group(1)):
        epoch, cell_html = row.groups()
        mb = _BUILD_LINK_RE.search(cell_html)
        cells = [_TAG_RE.sub(" ", _SVG_RE.sub(" ", c)) for c in _TD_RE.findall(cell_html)]
        cells = [re.sub(r"\s+", " ", _unescape(c)).strip() for c in cells]
        buildid = None
        if mb:
            buildid = int(mb.group(1))
        else:
            for c in reversed(cells):
                if re.fullmatch(r"\d{6,}", c):
                    buildid = int(c)
                    break
        if buildid is None or buildid in seen:
            continue
        try:
            when = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            continue
        title = cells[3] if len(cells) > 3 else ""
        label = re.sub(r"^\s*MAJOR\b\s*", "", title).strip()
        if not label or label.lower() == "no title":
            label = None
        seen.add(buildid)
        out.append(Build(buildid=buildid, time=when, title=title, label=label))
    return out


def parse_depot_history(html_text: str, depot: Optional[int] = None) -> List[ManifestRow]:
    """The depot's "manifests" table (whole page or just its <tr> rows) ->
    rows, in page order (newest first). Parsed one <tr> at a time so a branch
    tag can never be read from a neighbouring row. Rows whose gid is not a
    plain integer or whose time does not parse are skipped. `depot`, when
    given, drops rows of any other depot (a page only lists one, but a
    fragment might not)."""
    out: List[ManifestRow] = []
    for tr in _TR_RE.finditer(html_text):
        cell = tr.group(1)
        mt, mg = _ROW_TIME_RE.search(cell), _ROW_GID_RE.search(cell)
        if not mt or not mg:
            continue
        dep, gid = int(mg.group(1)), mg.group(2)
        if depot is not None and dep != depot:
            continue
        if not _GID_RE.match(gid):
            continue
        try:
            when = _utc(datetime.fromisoformat(mt.group(1).replace("Z", "+00:00")))
        except ValueError:
            continue
        mb = _ROW_BRANCH_RE.search(cell)
        branch = (mb.group(1).strip() if mb else "") or PUBLIC
        out.append(ManifestRow(depot=dep, gid=int(gid), time=when, branch=branch))
    return out


def parse_build_depots(html_text: str) -> Dict[int, int]:
    """The depots a build's page says it changed, {depot: new gid}. Comes from
    the page's own inline JSON (``const depots = [{"DepotID":..,"ManifestID":..}]``);
    the old->new history under it is lazy-loaded by SteamDB's JS and is not in
    the static HTML, so this is all the page gives without a browser running
    scripts. Exact for the depots listed; says nothing about the rest."""
    m = _DEPOTS_JSON_RE.search(html_text)
    if not m:
        return {}
    try:
        items = json.loads(m.group(1))
    except ValueError:
        return {}
    out: Dict[int, int] = {}
    for it in items if isinstance(items, list) else []:
        try:
            d, g = int(it["DepotID"]), int(str(it["ManifestID"]))
        except (KeyError, TypeError, ValueError):
            continue
        out[d] = g
    return out


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------

def public_rows(rows: Iterable[ManifestRow]) -> List[ManifestRow]:
    return [r for r in rows if r.public]


def build_branch(build_time: datetime, rows: Iterable[ManifestRow]) -> Optional[str]:
    """Which branch a build published to, from the row at its time. None when
    no row is within the window (the depot did not change in that build)."""
    best = None
    for r in rows:
        dt = abs((r.time - build_time).total_seconds())
        if dt <= MATCH_WINDOW_S and (best is None or dt < best[0]):
            best = (dt, r.branch)
    return best[1] if best else None


def resolve_depot(depot: int, build_time: datetime, rows: Iterable[ManifestRow],
                  build_gid: Optional[int] = None) -> Resolution:
    """One depot's gid at `build_time`.

    Order: the build page's own gid for this depot (exact, no dates) → the
    public row within ±3 s of the build (the depot changed in this build) →
    the newest public row strictly before the build (it did not change) →
    unconfirmed. Rows on other branches never count."""
    depot = int(depot)
    if build_gid is not None:
        return Resolution(depot=depot, gid=int(build_gid), status="changed",
                          why="listed on the build's page")
    pub = [r for r in rows if r.public and r.depot == depot]
    hit = None
    for r in pub:
        dt = abs((r.time - build_time).total_seconds())
        if dt <= MATCH_WINDOW_S and (hit is None or dt < hit[0]):
            hit = (dt, r)
    if hit:
        r = hit[1]
        return Resolution(depot=depot, gid=r.gid, status="changed", row_time=r.time,
                          why=f"public row at {r.time.isoformat()}")
    before = [r for r in pub if r.time < build_time]
    if before:
        r = max(before, key=lambda x: x.time)
        return Resolution(depot=depot, gid=r.gid, status="unchanged", row_time=r.time,
                          why=f"newest public row before the build, {r.time.isoformat()}")
    return Resolution(depot=depot, gid=None, status="unconfirmed",
                      why="no public row at or before the build in the visible history")


def resolve_build(build: Build, wanted_depots: Iterable[int],
                  history: Dict[int, List[ManifestRow]],
                  build_depots: Optional[Dict[int, int]] = None) -> Dict[int, Resolution]:
    """{depot: Resolution} for every depot in `wanted_depots` (the ones the user
    installs), from each depot's history and, when available, the build page's
    list. A depot with no history at all is unconfirmed, never guessed."""
    build_depots = build_depots or {}
    out: Dict[int, Resolution] = {}
    for d in wanted_depots:
        d = int(d)
        out[d] = resolve_depot(d, build.time, history.get(d) or [], build_depots.get(d))
    return out


def pins_from(resolutions: Dict[int, Resolution]) -> Dict[int, int]:
    """Only the confirmed depots, {depot: gid} — what goes into ManifestIds."""
    return {d: r.gid for d, r in resolutions.items() if r.gid is not None}


def unconfirmed(resolutions: Dict[int, Resolution]) -> List[int]:
    return sorted(d for d, r in resolutions.items() if r.gid is None)

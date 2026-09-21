"""Game versions for the UI: list the builds a game can be set to, and set one.

list_versions(appid): every public-branch build SteamDB knows for the app
(its builds table — see versions.parse_builds_page — read through
steamdb_reader), newest first, with date and the studio's label, and which
one is installed. Builds whose time matches a depot row of another branch
are dropped (betas), the rest kept.

install_version(appid, buildid): the build's page gives the gid of every
depot it changed; depots it did not change get the newest public row before
it from their history; a depot with neither stays as it is (logged, reported
as `unconfirmed`). The confirmed gids go into SLSsteam's ManifestIds
(pins.set_pin), the game is frozen with the version recorded
(pins.set_frozen) and its .acf flagged so Steam re-plans at its next start
(pins.mark_update_required). Steam then downloads the build with a manifest
request code from lumalinux's provider — the flow measured 2026-09-21
(Balatro, Dec-2024 gid). The user restarts Steam; we never do.

No fix is applied here; LuaTools fixes are a separate tab. The LuaTools
catalogue's build tags are matched to builds by the frontend (it already
holds the catalogue), not here.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

import versions
from versions import Build, ManifestRow

MAX_DEPOTS = 8


def public_builds(builds: List[Build], rows: List[ManifestRow]) -> List[Build]:
    """Drop builds that sit on a non-public depot row (a beta pushed at that
    time). A build with no row at all is kept: the depot did not change in
    it, or its history is off the visible window."""
    out = []
    for b in builds:
        br = versions.build_branch(b.time, rows)
        if br is not None and br != versions.PUBLIC:
            continue
        out.append(b)
    return out


def current_build(appid: int) -> Optional[int]:
    """The build the game is on: the one we pinned it to when frozen with a
    known build, else the .acf's (right only while Steam updates it)."""
    import pins
    v = pins.version_info(appid)
    if v and v.get("buildid"):
        try:
            return int(v["buildid"])
        except (TypeError, ValueError):
            pass
    if pins.is_frozen(appid):
        return None
    return pins.installed_buildid(appid)


async def _histories(reader, depots: List[int]) -> Dict[int, List[ManifestRow]]:
    from steamdb_reader import TTL_DEPOT, depot_path
    out: Dict[int, List[ManifestRow]] = {}
    for d in depots[:MAX_DEPOTS]:
        page = await reader.get(depot_path(d), TTL_DEPOT)
        out[d] = versions.parse_depot_history(page.text, d) if page.ok else []
    return out


def _needs_user(reader) -> dict:
    return {"success": False, "error": "steamdb_challenge", "needsUser": True,
            "challengeUrl": reader.challenge_url}


async def list_versions(appid: int) -> dict:
    import pins
    from steamdb_reader import Reader

    appid = int(appid)
    depots = sorted(pins.installed_depots(appid))
    if not depots:
        return {"success": False, "error": "not_installed"}
    t0 = time.monotonic()
    reader = Reader(appid)
    try:
        page = await reader.builds_page()
        if reader.needs_user:
            return _needs_user(reader)
        if not page.ok:
            return {"success": False, "error": f"steamdb: {page.outcome} {page.error}".strip()}
        builds = versions.parse_builds_page(page.text)
        if not builds:
            return {"success": False, "error": "no_builds"}
        history = await _histories(reader, depots)
        if reader.needs_user:
            return _needs_user(reader)
        rows = [r for rs in history.values() for r in rs]
        builds = public_builds(builds, rows)
        cur = current_build(appid)
        out = {
            "success": True,
            "builds": [{"buildid": b.buildid, "date": b.time.isoformat(), "label": b.label,
                        "installed": cur is not None and b.buildid == cur} for b in builds],
            "installedBuild": cur,
            "frozen": pins.is_frozen(appid),
            "depots": depots,
            "elapsedMs": int((time.monotonic() - t0) * 1000),
        }
        logger.info(f"Versions: {appid}: {len(builds)} builds, current {cur}, "
                    f"{out['elapsedMs']} ms, {[f.transport for f in reader.fetches]}")
        return out
    except Exception as exc:
        logger.warning(f"Versions: list for {appid} failed: {exc}")
        return {"success": False, "error": str(exc)}
    finally:
        await reader.close()


async def install_version(appid: int, buildid: int) -> dict:
    import pins
    from steamdb_reader import Reader, TTL_BUILD, build_path

    appid, buildid = int(appid), int(buildid)
    depots = sorted(pins.installed_depots(appid))
    if not depots:
        return {"success": False, "error": "not_installed"}
    reader = Reader(appid)
    try:
        page = await reader.builds_page()
        if reader.needs_user:
            return _needs_user(reader)
        build = next((b for b in versions.parse_builds_page(page.text) if b.buildid == buildid), None) \
            if page.ok else None
        if build is None:
            return {"success": False, "error": f"unknown build {buildid}"}
        bpage = await reader.get(build_path(buildid), TTL_BUILD)
        if reader.needs_user:
            return _needs_user(reader)
        build_depots = versions.parse_build_depots(bpage.text) if bpage.ok else {}
        history = await _histories(reader, depots)
        res = versions.resolve_build(build, depots, history, build_depots)
        confirmed = versions.pins_from(res)
        unconfirmed = versions.unconfirmed(res)
        if not confirmed:
            return {"success": False, "error": "no depot of this game can be resolved for that build",
                    "unconfirmed": unconfirmed}
        if unconfirmed:
            logger.info(f"Versions: {appid} build {buildid}: depots {unconfirmed} left as they are "
                        f"(no gid on the build's page nor a public row before it)")
        if not await pins.set_pin(appid, confirmed):
            return {"success": False, "error": "pin failed (see log)"}
        pins.set_frozen(appid, True, None, version={
            "buildid": str(buildid), "date": build.date, "label": build.label, "gids": confirmed})
        installed = pins.installed_depots(appid)
        flagged = False
        if any(installed.get(d) != g for d, g in confirmed.items()):
            flagged = pins.mark_update_required(appid)
        logger.info(f"Versions: {appid} pinned to build {buildid} ({build.date}, {build.label!r}): "
                    f"{sorted(confirmed.items())}; update flagged={flagged}; "
                    f"why={ {d: r.why for d, r in res.items()} }")
        return {"success": True, "buildid": buildid, "date": build.date, "label": build.label,
                "pinned": {str(d): str(g) for d, g in confirmed.items()},
                "unconfirmed": unconfirmed, "needsRestart": True}
    except Exception as exc:
        logger.warning(f"Versions: install {buildid} for {appid} failed: {exc}")
        return {"success": False, "error": str(exc)}
    finally:
        await reader.close()

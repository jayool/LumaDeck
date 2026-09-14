"""Pins: keep every lumalinux-managed game frozen to a build we have the
manifests for, and move that pin forward when a newer build can be sourced.

Why. The manifest request-code providers died on 2026-09-09. Without a code
Steam cannot fetch a manifest from Valve for a game the account doesn't own,
so a game that "follows Valve" breaks at its first update ("No internet
connection", retry every 30 s). Pinning the game in SLSsteam's `ManifestIds`
(depot -> gid) makes Steam plan against gids whose manifests we have placed in
depotcache/, which is the only thing that still works. Verified on the
devcontainer (2026-09-11): Steam re-reads the pin when the game is launched,
when Steam starts, and on every retry while an update is pending; it does
NOT re-read it while idle, and nothing we push from outside makes it.

Two passes run from one background task started by main.py:

  local pass (every LOCAL_INTERVAL s, no network)
    - a managed game with content depots missing from ManifestIds is pinned to
      what it has: InstalledDepots from its .acf, else the single manifest in
      depotcache/ (or our archive) for that depot;
    - a pinned manifest missing from depotcache/ is put back from the archive
      (Steam purges depotcache on uninstall, after commits and on re-plans).

  update pass (every UPDATE_INTERVAL s, network; skipped for frozen games)
    - Valve's current gids come from api.steamcmd.net;
    - depots we hold keys for whose gid changed: manifests via manifests.py
      (repo branch, then Hubcap if it's the current build); the pin moves only
      once EVERY changed depot resolved;
    - depots Valve added that we have no key for (a new DLC, a restructure):
      the repo has no keys, so the Hubcap zip is fetched (once a day per app)
      and installed through the normal pinned install path, but only if the
      zip's gids are Valve's current ones (a stale zip would downgrade).
    Steam applies the new pin the next time the game is launched or Steam
    restarts, exactly like a native update. Nothing is shown to the user.

Frozen. `~/.config/lumadeck/pins.json` holds a per-app `frozen` flag (set by
the Auto-update toggle, or by installing a LuaTools version fix, which records
the fix id). A frozen game keeps its pin; the local pass still heals it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import zipfile
from typing import Dict, List, Optional

from paths import get_depotcache_dir, get_lumalinux_keys_path, real_home
from steam_utils import _library_entries, detect_steam_install_path

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


LOCAL_INTERVAL = 60
UPDATE_INTERVAL = 30 * 60

_STATE_PATH = os.path.join(real_home(), ".config", "lumadeck", "pins.json")

# Steamworks shared redistributables (app 228980). Public depots Valve still
# serves request codes for; they must follow Valve and are never pinned. Same
# set as steamidra_lite._KNOWN_REDIST_DEPOTS.
REDIST_DEPOTS = {
    228981, 228982, 228983, 228984, 228985, 228986, 228987, 228988, 228989, 228990,
    229000, 229001, 229002, 229003, 229004, 229005, 229006, 229007,
    229010, 229011, 229012, 229020, 229030, 229031, 229032, 229033,
}

_MANIFEST_RE = re.compile(r"^(\d+)_(\d+)\.manifest$")
_reported_unpinnable: set = set()


# ---------------------------------------------------------------------------
# Frozen state
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("apps"), dict):
            return data
    except Exception:
        pass
    return {"apps": {}}


def _save_state(data: dict) -> None:
    from manifests import _write_atomic
    _write_atomic(_STATE_PATH, json.dumps(data, indent=2).encode("utf-8"))


def is_frozen(appid: int) -> bool:
    return bool(_load_state()["apps"].get(str(int(appid)), {}).get("frozen"))


def frozen_info(appid: int) -> dict:
    return dict(_load_state()["apps"].get(str(int(appid)), {}))


def set_frozen(appid: int, frozen: bool, fix_id: Optional[str] = None) -> None:
    data = _load_state()
    entry = data["apps"].get(str(int(appid)), {})
    entry["frozen"] = bool(frozen)
    entry["fix_id"] = fix_id if frozen else None
    entry["updated_at"] = int(time.time())
    data["apps"][str(int(appid))] = entry
    _save_state(data)


# ---------------------------------------------------------------------------
# What we know about a game
# ---------------------------------------------------------------------------

def read_manifest_ids() -> Dict[int, int]:
    """SLSsteam's ManifestIds section, {depot: gid}. Same line-based reading
    as steamidra_lite._read_manifest_ids (SteamOS python has no pyyaml)."""
    path = os.path.join(real_home(), ".config", "SLSsteam", "config.yaml")
    out: Dict[int, int] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return out
    inside = False
    for line in lines:
        if not inside:
            if line.strip().startswith("ManifestIds:"):
                inside = True
            continue
        if line[:1] not in (" ", "\t"):
            break
        m = re.match(r"^\s*(\d+)\s*:\s*(\d+)", line)
        if m:
            out[int(m.group(1))] = int(m.group(2))
    return out


def _keys_lines() -> List[List[str]]:
    path = get_lumalinux_keys_path()
    rows: List[List[str]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    rows.append(line.split(";"))
    except Exception:
        pass
    return rows


def keyed_depots(appid: int) -> Dict[int, str]:
    """Content depots we hold a key for, {depot: hexkey}: keys.txt EXTENDED
    lines (depot;parent;gid;size;key) with parent == appid, minus redists."""
    out: Dict[int, str] = {}
    for parts in _keys_lines():
        if len(parts) == 5 and parts[1] == str(int(appid)):
            try:
                did = int(parts[0])
            except ValueError:
                continue
            if did not in REDIST_DEPOTS and len(parts[4]) == 64:
                out[did] = parts[4]
    return out


def managed_apps() -> List[int]:
    """Apps with at least one keyed content depot in keys.txt."""
    apps = set()
    for parts in _keys_lines():
        if len(parts) == 5 and parts[1].isdigit():
            try:
                if int(parts[0]) not in REDIST_DEPOTS:
                    apps.add(int(parts[1]))
            except ValueError:
                pass
    return sorted(apps)


def find_acf(appid: int) -> Optional[str]:
    for entry in _library_entries():
        p = os.path.join(entry["path"], "steamapps", f"appmanifest_{int(appid)}.acf")
        if os.path.isfile(p):
            return p
    root = detect_steam_install_path()
    if root:
        p = os.path.join(root, "steamapps", f"appmanifest_{int(appid)}.acf")
        if os.path.isfile(p):
            return p
    return None


def installed_depots(appid: int) -> Dict[int, int]:
    """{depot: gid} from the .acf's InstalledDepots block ({} if none)."""
    path = find_acf(appid)
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except Exception:
        return {}
    m = re.search(r'"InstalledDepots"\s*\{', txt)
    if not m:
        return {}
    # Walk to the matching brace of the InstalledDepots block.
    i, depth = m.end(), 1
    while i < len(txt) and depth:
        if txt[i] == "{":
            depth += 1
        elif txt[i] == "}":
            depth -= 1
        i += 1
    block = txt[m.end():i]
    out: Dict[int, int] = {}
    for dm in re.finditer(r'"(\d+)"\s*\{\s*"manifest"\s*"(\d+)"', block):
        out[int(dm.group(1))] = int(dm.group(2))
    return out


def depotcache_gids(depot: int) -> List[int]:
    d = get_depotcache_dir()
    if not d or not os.path.isdir(d):
        return []
    out = []
    for name in os.listdir(d):
        m = _MANIFEST_RE.match(name)
        if m and int(m.group(1)) == int(depot):
            out.append(int(m.group(2)))
    return out


def _download_busy(appid: int) -> bool:
    try:
        from downloads import DOWNLOAD_STATE
        st = (DOWNLOAD_STATE.get(int(appid)) or {}).get("status")
        return bool(st) and st not in ("done", "failed", "cancelled")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Writing the pin
# ---------------------------------------------------------------------------

async def set_pin(appid: int, gids: Dict[int, int]) -> bool:
    """steamidra_lite --set-pin: merge {depot: gid} into ManifestIds. Refuses
    depots without a key, so a bad call can't leave Steam with an undecryptable
    target."""
    from downloads import _run_steamidra_mode
    if not gids:
        return False
    args = ["--set-pin", str(int(appid))] + [f"{int(d)}:{int(g)}" for d, g in sorted(gids.items())]
    ok, out = await _run_steamidra_mode(args)
    if not ok:
        logger.warning(f"LumaDeck: set-pin failed for {appid}: {out[-600:]}")
    return ok


# ---------------------------------------------------------------------------
# Local pass
# ---------------------------------------------------------------------------

async def ensure_pinned(appid: int) -> Dict[int, int]:
    """Pin any unpinned content depot to what the game already has, and put
    back pinned manifests missing from depotcache/. Returns the pin."""
    from manifests import (archive_dir, archive_manifest, archived_manifests, manifest_name,
                           place_in_depotcache, validate_manifest)

    keyed = keyed_depots(appid)
    if not keyed:
        return {}
    mids = read_manifest_ids()
    pin = {d: mids[d] for d in keyed if d in mids}
    unpinned = [d for d in keyed if d not in mids]

    if unpinned:
        inst = installed_depots(appid)
        arch = archived_manifests(appid)
        target: Dict[int, int] = {}
        for d in unpinned:
            if inst.get(d):
                target[d] = inst[d]
                continue
            gids = sorted(set(depotcache_gids(d)) | set(arch.get(d, [])))
            if len(gids) == 1:
                target[d] = gids[0]
        if target:
            if await set_pin(appid, target):
                logger.info(f"LumaDeck: pinned {appid} to {sorted(target.items())} "
                            f"({'installed build' if inst else 'seeded manifests'})")
                pin.update(target)
        left = [d for d in unpinned if d not in target]
        if left and appid not in _reported_unpinnable:
            # Usually the other platforms' depots (Windows/macOS on a native
            # Linux install): keyed, never downloaded, nothing to pin to. The
            # update pass only cares about the platform Steam runs the game as.
            _reported_unpinnable.add(appid)
            logger.info(f"LumaDeck: {appid}: no build to pin depots {left} to (not installed, no manifest)")

    dc = get_depotcache_dir()
    if dc:
        for d, g in pin.items():
            present = os.path.join(dc, manifest_name(d, g))
            if os.path.isfile(present):
                # Keep our own copy of what Steam has, so a later purge (Steam
                # uninstall, post-commit, re-plan) can be healed offline. This
                # is also how games installed before the archive existed get one.
                if not os.path.isfile(os.path.join(archive_dir(appid), manifest_name(d, g))):
                    try:
                        with open(present, "rb") as f:
                            data = f.read()
                        if validate_manifest(data, d, g) is not None:
                            archive_manifest(appid, d, g, data)
                    except Exception as exc:
                        logger.warning(f"LumaDeck: could not archive {manifest_name(d, g)}: {exc}")
                continue
            src = os.path.join(archive_dir(appid), manifest_name(d, g))
            if not os.path.isfile(src):
                logger.info(f"LumaDeck: {appid}: pinned manifest {manifest_name(d, g)} missing "
                            f"from depotcache and archive; the update pass will look online")
                continue
            try:
                with open(src, "rb") as f:
                    data = f.read()
                if validate_manifest(data, d, g) is None:
                    os.remove(src)
                    continue
                place_in_depotcache(d, g, data)
                logger.info(f"LumaDeck: restored {manifest_name(d, g)} for {appid} from the archive")
            except Exception as exc:
                logger.warning(f"LumaDeck: restore of {manifest_name(d, g)} failed: {exc}")

        # The INSTALLED build's manifests too, when the pin already points at a
        # newer one. Steam computes an update as the difference between the
        # installed manifest and the target, so it asks for the installed one
        # as well; without it the update dies on "Failed to get manifest request
        # code, 'Access Denied'" and the game sits on "Update" (Balatro,
        # 2026-09-13: old manifest removed -> stuck; put back -> the 30 s retry
        # finished the update). Offline heal from the archive only; the update
        # pass resolves them online before it moves a pin.
        for d, g in installed_depots(appid).items():
            if d not in keyed or pin.get(d) == g:
                continue
            if os.path.isfile(os.path.join(dc, manifest_name(d, g))):
                continue
            src = os.path.join(archive_dir(appid), manifest_name(d, g))
            if not os.path.isfile(src):
                continue
            try:
                with open(src, "rb") as f:
                    data = f.read()
                if validate_manifest(data, d, g) is None:
                    os.remove(src)
                    continue
                place_in_depotcache(d, g, data)
                logger.info(f"LumaDeck: restored installed-build {manifest_name(d, g)} for {appid} "
                            f"from the archive (Steam needs it to compute the update)")
            except Exception as exc:
                logger.warning(f"LumaDeck: restore of {manifest_name(d, g)} failed: {exc}")
    return pin


async def local_pass() -> None:
    for appid in managed_apps():
        if _download_busy(appid):
            continue
        try:
            await ensure_pinned(appid)
        except Exception as exc:
            logger.warning(f"LumaDeck: local pin pass failed for {appid}: {exc}")


# ---------------------------------------------------------------------------
# Update pass
# ---------------------------------------------------------------------------

def _platform_for(keyed: Dict[int, str], valve: Dict[int, dict]) -> str:
    """Steam installs the depots of the platform it runs the game as: the
    native Linux build when we hold a Linux depot key (the install enriched
    the lua with it), otherwise Windows under Proton."""
    for d in keyed:
        if valve.get(d, {}).get("oslist") == "linux":
            return "linux"
    return "windows"


def _zip_gids(zip_path: str) -> Dict[int, int]:
    out: Dict[int, int] = {}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                m = _MANIFEST_RE.match(os.path.basename(member))
                if m:
                    out[int(m.group(1))] = int(m.group(2))
    except Exception:
        pass
    return out


async def check_update(appid: int) -> str:
    """One game, one update check. Returns a short outcome for the log."""
    from manifests import fetch_game_zip, hubcap_budget_ok, resolve_all, steamcmd_app_info

    keyed = keyed_depots(appid)
    if not keyed:
        return "no keyed depots"
    pin = await ensure_pinned(appid)

    info = await steamcmd_app_info(appid)
    if not info:
        return "steamcmd.net unavailable"
    valve = info["depots"]
    platform = _platform_for(keyed, valve)
    # The depots Steam would actually download for this game: its platform's
    # (plus platform-neutral ones such as DLC data), never the shared redists.
    relevant = {
        d: v for d, v in valve.items()
        if d not in REDIST_DEPOTS and not v["sharedinstall"]
        and v["oslist"] in ("", platform) and v["osarch"] in ("", "64")
    }
    unpinned = [d for d in keyed if d in relevant and d not in pin]
    if unpinned:
        return f"not fully pinned yet (depots {unpinned})"
    changed = {d: v["gid"] for d, v in relevant.items() if d in keyed and v["gid"] != pin.get(d)}
    new_depots = sorted(d for d in relevant if d not in keyed)
    if not changed and not new_depots:
        return "up to date"

    current = {d: v["gid"] for d, v in relevant.items()}

    if new_depots:
        # No key for these: only a fresh game zip (lua + keys + manifests)
        # can add them. Once a day per app.
        if not hubcap_budget_ok(appid):
            return f"new depots {new_depots} need a zip; Hubcap already tried today"
        zip_path = await fetch_game_zip(appid)
        if not zip_path:
            return f"new depots {new_depots} need a zip; no source returned one"
        try:
            zg = _zip_gids(zip_path)
            stale = {d: (g, current.get(d)) for d, g in zg.items()
                     if d in current and current[d] != g}
            if stale or not any(d in zg for d in new_depots):
                return (f"zip is stale or lacks the new depots (stale={stale}, "
                        f"has={sorted(zg)}); retry tomorrow")
            from downloads import DOWNLOAD_STATE, _process_and_install_lua
            await _process_and_install_lua(appid, zip_path, pin=True)
            DOWNLOAD_STATE.pop(int(appid), None)
            return f"reinstalled from zip: new depots {new_depots}, build {info.get('buildid')}"
        finally:
            shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)

    found, missing = await resolve_all(appid, changed, allow_hubcap=True, current_gids=current)
    if missing:
        return f"build {info.get('buildid')} not fully available: {missing}"
    # Steam diffs the installed manifest against the new one, so the installed
    # build's manifests must be on disk too (archive, then the online sources;
    # never Hubcap, which only has the current build). Moving the pin without
    # them leaves the game stuck on "Update" with 'Access Denied' on the old gid.
    installed = {d: g for d, g in installed_depots(appid).items()
                 if d in changed and g != changed[d]}
    if installed:
        _, old_missing = await resolve_all(appid, installed, allow_hubcap=False)
        if old_missing:
            return (f"build {info.get('buildid')} ready but the installed build's manifests "
                    f"are missing ({old_missing}); Steam needs them to update, not moving the pin")
    new_pin = dict(pin)
    new_pin.update(changed)
    if await set_pin(appid, new_pin):
        return f"pin moved to build {info.get('buildid')}: {sorted(changed.items())}"
    return "set-pin failed"


async def update_pass() -> None:
    for appid in managed_apps():
        if _download_busy(appid):
            continue
        if is_frozen(appid):
            continue
        try:
            outcome = await check_update(appid)
            logger.info(f"LumaDeck: update check {appid}: {outcome}")
        except Exception as exc:
            logger.warning(f"LumaDeck: update check failed for {appid}: {exc}")


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

_task: Optional[asyncio.Task] = None


async def run_forever() -> None:
    """Started from main.py. Local pass every LOCAL_INTERVAL, update pass every
    UPDATE_INTERVAL, both once at start."""
    last_update = 0.0
    while True:
        try:
            await local_pass()
            if time.time() - last_update >= UPDATE_INTERVAL:
                await update_pass()
                last_update = time.time()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"LumaDeck: pins loop error: {exc}")
        await asyncio.sleep(LOCAL_INTERVAL)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(run_forever())


def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None

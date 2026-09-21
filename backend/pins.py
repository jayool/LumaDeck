"""Pins: native updates while a request-code provider is alive, pins as the
fallback when none is.

Two models, chosen by lumalinux's `gmrc.json` (v0.21.0+, written next to
status.json after every manifest-request-code lookup):

  "up"   — NATIVE. A managed game carries no pin: Steam sees Valve's current
           build, asks for a manifest code, lumalinux's GMRC hook gets one from
           a provider (checked against Valve's CDN first) and Steam installs or
           updates exactly like an owned game. LumaDeck only archives the
           manifests Steam downloads. Games the user froze (Auto-update off) or
           a LuaTools version fix froze keep their pin.
  "down" — no provider answered. Every unfrozen game is pinned to its INSTALLED
           build (manifests archived, so Steam needs no code) and marked
           `reason: "providers"` in pins.json; Steam sees "installed == target"
           and clears any pending update. The window is one local pass (60 s)
           for the games that happened to publish an update meanwhile.
  absent — older lumalinux or no lookup yet this session: the pre-0.9 model,
           every game pinned and moved by the update pass below.

Release: `gmrc.json` only changes when Steam asks for a code, so while any game
is frozen by us the 30-minute pass probes a provider itself (one code for one
of our depots, validated against the CDN like tools/gmrc_probe.py) and, on
success, unpins the games it froze. Detection of an outage is ~1 min;
detection of the recovery is ≤ 30 min. Nothing is shown to the user.

Why pins exist at all: the providers died on 2026-09-09. Without a code Steam
cannot fetch a manifest for a game the account doesn't own, so a game that
"follows Valve" breaks at its first update ("No internet connection", retry
every 30 s). Pinning it in SLSsteam's `ManifestIds` (depot -> gid) makes Steam
plan against gids whose manifests we placed in depotcache/. Verified on the
devcontainer (2026-09-11): Steam re-reads the pin when the game is launched,
when Steam starts, and on every retry while an update is pending; it does
NOT re-read it while idle. Providers with licensed accounts came back on
2026-09-15/16 (lumalinux RESEARCH §20), hence the native model.

Two passes run from one background task started by main.py:

  local pass (every LOCAL_INTERVAL s, no network)
    - reads gmrc.json and applies the model above: "down" freezes unfrozen
      games to their installed build, "up" releases the games we froze and any
      leftover pin of an unfrozen game (the 0.8.x migration), absent pins any
      unpinned game to what it has (InstalledDepots from its .acf, else the
      single manifest in depotcache/ or our archive);
    - a pinned manifest missing from depotcache/ is put back from the archive
      (Steam purges depotcache on uninstall, after commits and on re-plans);
      the installed build's manifests are archived and healed the same way.

  update pass (every UPDATE_INTERVAL s, network; skipped for frozen games)
    - Valve's current gids come from api.steamcmd.net;
    - depots Valve added that we have no key for (a new DLC, a restructure):
      keys only come in a Hubcap zip, so one is fetched (once a day per app)
      and installed through the normal install path, but only if the zip's
      gids are Valve's current ones (a stale zip would downgrade). Both models.
    - pinned model only: depots we hold keys for whose gid changed get their
      manifests via manifests.py (archive, luastools, Hubcap if current) and
      the pin moves once EVERY changed depot resolved. Native games are left
      to Steam.
    - while any game is frozen by us: the provider probe described above.

Frozen. `~/.config/lumadeck/pins.json` holds a per-app `frozen` flag (set by
the Auto-update toggle, by installing a LuaTools version fix, which records
the fix id, or by this module with `reason: "providers"`). A frozen game keeps
its pin; the local pass still heals it.
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

# pins.json `reason` for a freeze this module applied because no provider
# answered; the only freeze it will undo by itself.
FREEZE_REASON_PROVIDERS = "providers"
# Valve's CDN, for the recovery probe (same hosts lumalinux checks codes on).
_CDN_HOSTS = ("https://steampipe.akamaized.net",
              "https://fastly.cdn.steampipe.steamcontent.com")
_PROBE_UA = "LumaDeck/pins"

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


def set_frozen(appid: int, frozen: bool, fix_id: Optional[str] = None,
               reason: Optional[str] = None,
               version: Optional[dict] = None) -> None:
    """`version` describes the build the game is pinned to, for display only:
    {"buildid": str|None, "date": "YYYY-MM-DD"|None, "label": str|None,
     "gids": {depot: gid}}. The .acf's own `buildid` is NOT the source of that
    label: Steam stamps it with Valve's current build even on a pinned older
    one (measured 2026-09-21: Balatro on the Dec-2024 manifest still reads
    buildid 17459173). Cleared on unfreeze."""
    data = _load_state()
    entry = data["apps"].get(str(int(appid)), {})
    entry["frozen"] = bool(frozen)
    entry["fix_id"] = fix_id if frozen else None
    entry["reason"] = reason if frozen else None
    if frozen:
        if version is not None:
            entry["version"] = {
                "buildid": (str(version.get("buildid")).strip() or None)
                           if version.get("buildid") is not None else None,
                "date": version.get("date") or None,
                "label": version.get("label") or None,
                "gids": {str(int(d)): str(int(g))
                         for d, g in (version.get("gids") or {}).items()},
            }
    else:
        entry["version"] = None
    entry["updated_at"] = int(time.time())
    data["apps"][str(int(appid))] = entry
    _save_state(data)


def version_info(appid: int) -> Optional[dict]:
    """The version a frozen game was pinned to (see set_frozen), or None when
    unknown / not frozen. The gids are the ones written at pin time; if the
    .acf's InstalledDepots no longer match them the label is stale."""
    info = frozen_info(appid)
    if not info.get("frozen"):
        return None
    v = info.get("version")
    return dict(v) if isinstance(v, dict) else None


# Steam's EAppState bits, as written in appmanifest_<app>.acf "StateFlags".
_STATE_UPDATE_REQUIRED = 2
_STATE_FULLY_INSTALLED = 4


def mark_update_required(appid: int) -> bool:
    """Flag the installed game as "update required" (StateFlags |= 2) in its
    .acf so Steam re-plans its depots on the NEXT time it loads the manifest,
    i.e. its next start.

    Why this exists: Steam only re-plans a game's depots when it believes
    something is pending. Moving the pin in SLSsteam's ManifestIds tells
    SLSsteam, not Steam; Steam's own check (installed buildid == Valve's) says
    "up to date" and it never asks. Verified 2026-09-21 on a Codespace: pin to
    an older gid + Steam restart -> nothing; pin + "verify files" -> nothing
    (validation compares against the manifest already installed); pin +
    StateFlags 4->6 + restart -> Steam re-plans, SLSsteam substitutes the gid,
    lumalinux's GMRC hook fetches the request code, Steam downloads the old
    build (7 chunks, .acf manifest = the pinned gid).

    Only the StateFlags value changes; nothing else in the .acf is touched and
    the buildid is never written (writing an old one is the same trigger with
    no way to clear it). Steam keeps its own in-memory copy while running, so
    the edit takes effect at its next start — the caller reports needsRestart.
    Returns True when the flag is set (or already was), False when there is no
    .acf or no StateFlags line to edit."""
    path = find_acf(appid)
    if not path:
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except Exception as exc:
        logger.warning(f"LumaDeck: mark_update_required {appid}: cannot read .acf: {exc}")
        return False
    m = re.search(r'("StateFlags"\s+")(\d+)(")', txt)
    if not m:
        return False
    flags = int(m.group(2))
    if flags & _STATE_UPDATE_REQUIRED:
        return True
    new_flags = flags | _STATE_UPDATE_REQUIRED
    new_txt = txt[:m.start(2)] + str(new_flags) + txt[m.end(2):]
    try:
        from manifests import _write_atomic
        _write_atomic(path, new_txt.encode("utf-8"))
    except Exception as exc:
        logger.warning(f"LumaDeck: mark_update_required {appid}: cannot write .acf: {exc}")
        return False
    logger.info(f"LumaDeck: {appid} StateFlags {flags} -> {new_flags} (update required on next Steam start)")
    return True


def frozen_by_providers(appid: int) -> bool:
    info = frozen_info(appid)
    return bool(info.get("frozen")) and info.get("reason") == FREEZE_REASON_PROVIDERS


def user_frozen(appid: int) -> bool:
    """Frozen by the user (Auto-update off) or by a version fix — never by us."""
    info = frozen_info(appid)
    return bool(info.get("frozen")) and info.get("reason") != FREEZE_REASON_PROVIDERS


# ---------------------------------------------------------------------------
# Provider state (lumalinux's gmrc.json + our own recovery probe)
# ---------------------------------------------------------------------------

_probe_ok_at = 0.0   # epoch of the last successful recovery probe


def _read_gmrc_json() -> Optional[dict]:
    from paths import find_lumalinux_gmrc_path
    p = find_lumalinux_gmrc_path()
    if not p:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("providers") in ("up", "down"):
            return d
    except Exception:
        pass
    return None


def _iso_epoch(s: str) -> float:
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except Exception:
        return 0.0


def gmrc_state() -> Optional[str]:
    """'up' | 'down' | None. lumalinux's word, unless our own probe succeeded
    more recently than lumalinux last wrote (the file only changes when Steam
    asks for a code, so a recovery would otherwise never be seen)."""
    d = _read_gmrc_json()
    if d is None:
        return None
    if d["providers"] == "down" and _probe_ok_at > _iso_epoch(str(d.get("at", ""))):
        return "up"
    return d["providers"]


def pin_new_installs() -> bool:
    """What Add Game passes as `pin`: no pin while a provider is up (Steam
    installs the current build natively), a pin to the zip's build otherwise."""
    return gmrc_state() != "up"


async def probe_providers() -> bool:
    """One request code for one of our depots (or the free redistributables),
    validated against Valve's CDN with a one-byte fetch — the same test
    tools/gmrc_probe.py runs. True = a provider is serving codes again."""
    global _probe_ok_at
    from manifests import steamcmd_app_info
    from http_client import ensure_http_client
    client = await ensure_http_client("manifests")

    target = None  # (depot, gid)
    for appid in managed_apps():
        keyed = keyed_depots(appid)
        if not keyed:
            continue
        info = await steamcmd_app_info(appid)
        if not info:
            continue
        for d in sorted(keyed):
            g = (info["depots"].get(d) or {}).get("gid")
            if g:
                target = (d, int(g))
                break
        if target:
            break
    if not target:
        info = await steamcmd_app_info(228980)
        g = ((info or {}).get("depots", {}).get(228989) or {}).get("gid")
        if not g:
            return False
        target = (228989, int(g))
    depot, gid = target

    providers = (
        (f"https://20770407.xyz/manifest/{depot}/{gid}", _PROBE_UA),
        (f"https://manifest.manifestdex.com/{gid}", "ManifestDeX/1.0"),
    )
    for url, ua in providers:
        try:
            resp = await client.get(url, headers={"User-Agent": ua}, timeout=10)
            body = (resp.text or "").strip()
        except Exception:
            continue
        if resp.status_code != 200 or not body.isdigit() or body == "0":
            continue
        for host in _CDN_HOSTS:
            try:
                cdn = await client.get(f"{host}/depot/{depot}/manifest/{gid}/5/{body}",
                                       headers={"User-Agent": _PROBE_UA, "Range": "bytes=0-0"},
                                       timeout=10)
            except Exception:
                continue
            if cdn.status_code in (200, 206):
                _probe_ok_at = time.time()
                logger.info(f"LumaDeck: provider probe ok ({url.split('/')[2]}, depot {depot})")
                return True
            break  # a definite answer from the CDN: this code is no good
    logger.info("LumaDeck: provider probe: no provider served a valid code")
    return False


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


def installed_buildid(appid: int) -> Optional[int]:
    """The .acf's `buildid`. Right for a game Steam updates itself (it stamps
    it when an update completes); WRONG for a pinned game (Steam keeps
    Valve's current build there) — use version_info() for those."""
    path = find_acf(appid)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            m = re.search(r'"buildid"\s+"(\d+)"', f.read())
        return int(m.group(1)) if m else None
    except Exception:
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

async def unpin_game_depots(appid: int) -> bool:
    """steamidra_lite --unpin: drop the game's content depots from ManifestIds.
    Manifests on disk are untouched (Steam needs the installed one to compute
    an update). Steam follows Valve again on its next plan."""
    from downloads import _run_steamidra_mode
    ok, out = await _run_steamidra_mode(["--unpin", str(int(appid))])
    if not ok:
        logger.warning(f"LumaDeck: unpin failed for {appid}: {out[-600:]}")
    return ok


async def ensure_pinned(appid: int, allow_pin: bool = True) -> Dict[int, int]:
    """Put back pinned manifests missing from depotcache/ and archive what
    Steam downloaded; with allow_pin, also pin any unpinned content depot to
    what the game already has. Returns the pin."""
    from manifests import (archive_dir, archive_manifest, archived_manifests, manifest_name,
                           place_in_depotcache, validate_manifest)

    keyed = keyed_depots(appid)
    if not keyed:
        return {}
    mids = read_manifest_ids()
    pin = {d: mids[d] for d in keyed if d in mids}
    unpinned = [d for d in keyed if d not in mids] if allow_pin else []

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

        # A native (unpinned) game: keep a copy of the installed build's manifest
        # as Steam wrote it, so a later freeze has something to pin to and heal
        # from. Nothing else to do for it here.
        for d, g in installed_depots(appid).items():
            if d not in keyed or d in pin:
                continue
            present = os.path.join(dc, manifest_name(d, g))
            if not os.path.isfile(present):
                continue
            if os.path.isfile(os.path.join(archive_dir(appid), manifest_name(d, g))):
                continue
            try:
                with open(present, "rb") as f:
                    data = f.read()
                if validate_manifest(data, d, g) is not None:
                    archive_manifest(appid, d, g, data)
            except Exception as exc:
                logger.warning(f"LumaDeck: could not archive {manifest_name(d, g)}: {exc}")

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
    state = gmrc_state()
    for appid in managed_apps():
        if _download_busy(appid):
            continue
        try:
            await _apply_model(appid, state)
        except Exception as exc:
            logger.warning(f"LumaDeck: local pin pass failed for {appid}: {exc}")


async def _apply_model(appid: int, state: Optional[str]) -> None:
    """One game, one local pass, per the module docstring."""
    if user_frozen(appid):
        await ensure_pinned(appid, allow_pin=True)      # theirs: keep and heal
        return
    if state == "down":
        if not frozen_by_providers(appid):
            pin = await ensure_pinned(appid, allow_pin=True)
            if pin:
                set_frozen(appid, True, reason=FREEZE_REASON_PROVIDERS)
                logger.info(f"LumaDeck: no provider answers — {appid} frozen to its "
                            f"installed build {sorted(pin.items())}")
        else:
            await ensure_pinned(appid, allow_pin=True)
        return
    if state == "up":
        keyed = keyed_depots(appid)
        mids = read_manifest_ids()
        if any(d in mids for d in keyed):
            # Ours (a providers freeze) or a leftover of the 0.8.x always-pin
            # model: release, Steam follows Valve from here.
            if await unpin_game_depots(appid):
                if frozen_by_providers(appid):
                    set_frozen(appid, False)
                logger.info(f"LumaDeck: provider up — {appid} released to native updates")
        await ensure_pinned(appid, allow_pin=False)     # archive/heal only
        return
    # No gmrc.json: the pre-0.9 model, everything pinned.
    await ensure_pinned(appid, allow_pin=True)


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


async def check_update(appid: int, native: bool = False) -> str:
    """One game, one update check. Returns a short outcome for the log.
    `native`: the game carries no pin and Steam updates it itself; only the
    new-depot (keys) part applies."""
    from manifests import fetch_game_zip, hubcap_budget_ok, resolve_all, steamcmd_app_info

    keyed = keyed_depots(appid)
    if not keyed:
        return "no keyed depots"
    pin = await ensure_pinned(appid, allow_pin=not native)

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
    new_depots = sorted(d for d in relevant if d not in keyed)
    if native:
        changed = {}
        if not new_depots:
            return "native (Steam updates it)"
    else:
        unpinned = [d for d in keyed if d in relevant and d not in pin]
        if unpinned:
            return f"not fully pinned yet (depots {unpinned})"
        changed = {d: v["gid"] for d, v in relevant.items() if d in keyed and v["gid"] != pin.get(d)}
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
            await _process_and_install_lua(appid, zip_path, pin=not native)
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
    apps = managed_apps()
    state = gmrc_state()
    # Recovery: lumalinux only rewrites gmrc.json when Steam asks for a code,
    # so while we hold games frozen for lack of providers, ask one ourselves.
    if state != "up" and any(frozen_by_providers(a) for a in apps):
        try:
            if await probe_providers():
                state = "up"
                for appid in apps:
                    if not _download_busy(appid):
                        await _apply_model(appid, state)
        except Exception as exc:
            logger.warning(f"LumaDeck: provider probe failed: {exc}")
    native = (state == "up")
    for appid in apps:
        if _download_busy(appid):
            continue
        if is_frozen(appid):
            continue
        try:
            outcome = await check_update(appid, native=native)
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

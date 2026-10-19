"""Is it safe to let Steam update? The soft gate behind "Let Steam update".

After a break-recovery downgrade (lumalinux's downgrade.sh) Steam is pinned at an
older build. The user needs to know WHEN lifting the pin is safe, and only the
plugin can know: headcrab's pin says nothing reliable (nosotros.md §4.1-29), so
this asks the three sources that actually decide it, with no headcrab anywhere:

  1. Valve's public client manifest for the Deck stable branch — the build Steam
     will update to the moment the pin is lifted (the bootstrapper fetches this
     very file).
  2. lumalinux's res/updates.yaml — maps that build to its steamclient.so hash
     (the daily cron annotates every new stable build) and says whether the
     latest lumalinux release hooks it.
  3. SLSsteam's res/updates.yaml — lists, per release tag, the hashes that
     release hooks. The hash under a tag = that SLSsteam supports the build; the
     tag also says whether the INSTALLED SLSsteam is new enough.

The result is advice, never a lock: the button stays available in every state,
the description changes. A network failure or a format change on Ace's side
reads as "unknown", so a user is never left without a way back up.

States: ready | not_yet | unknown (see evaluate()); ready carries slssteam_update_pending.

Support rule (2026-10-14, learned the hard way): an SLSsteam release hooks a
client hash iff the hash is listed under the NEWEST SafeModeHashes group whose
tag is <= that release's tag. Groups are pattern sets; a release re-derives its
patterns and DROPS older clients. 20261014151919 lists only 0d01ab4f: it does
not hook bc54101b any more, and installing it on a Deck pinned at bc54101b
crash-looped Steam until SteamOS re-bootstrapped the client from its image. So
"a newer SLSsteam supports everything the older one did" is false, and nothing
here assumes it: see slssteam_supports() and plan_setup().
"""
from __future__ import annotations

import hashlib
import json
import asyncio
import os
import re
import time
from typing import Optional

from feed_cache import fresh
from http_client import ensure_http_client
from paths import find_steam_root, real_home

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

# The bootstrapper's own manifest URLs (see any Steam logs/bootstrap_log.txt).
_DECK_MANIFEST_URL = "https://client-update.fastly.steamstatic.com/steam_client_steamdeck_stable_ubuntu12"
_LINUX_MANIFEST_URL = "https://client-update.fastly.steamstatic.com/steam_client_ubuntu12"
_SLSSTEAM_UPDATES_URL = "https://raw.githubusercontent.com/AceSLS/SLSsteam/refs/heads/main/res/updates.yaml"
_CACHE_DIR = os.path.join(real_home(), ".cache", "lumadeck")
_STABLE_CACHE = os.path.join(_CACHE_DIR, "steam_stable_build.json")
_SLS_CACHE = os.path.join(_CACHE_DIR, "slssteam_updates.yaml")
_STABLE_TTL = 30 * 60      # Valve's manifest changes a few times a month
_FETCH_TIMEOUT = 5.0

_VERSION_RE = re.compile(r'^\s*"version"\s+"(\d+)"', re.MULTILINE)
_SLS_GROUP_RE = re.compile(r"^  (\d{14}):")
_SLS_HASH_RE = re.compile(r"^\s*-\s*([0-9a-f]{64})\b")


def _branch() -> str:
    """The Steam client branch this install follows: package/beta (steam-jupiter
    writes `steamdeck_stable` on a Deck), empty on generic Linux."""
    root = find_steam_root()
    if not root:
        return "steamdeck_stable"
    try:
        with open(os.path.join(root, "package", "beta"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def parse_manifest_version(text: str | None) -> Optional[int]:
    if not text:
        return None
    m = _VERSION_RE.search(text)
    return int(m.group(1)) if m else None


async def latest_stable_build(force: bool = False) -> Optional[int]:
    """The build Valve currently serves on this install's branch, cached 30 min.
    None when unreachable and no cache."""
    if not force:
        try:
            with open(_STABLE_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if time.time() - float(cached.get("at", 0)) < _STABLE_TTL and cached.get("build"):
                return int(cached["build"])
        except Exception:
            pass
    url = _DECK_MANIFEST_URL if _branch().startswith("steamdeck") else _LINUX_MANIFEST_URL
    build = None
    try:
        client = await ensure_http_client(context="steam_update_gate")
        resp = await client.get(url, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200:
            build = parse_manifest_version(resp.text)
        else:
            logger.info(f"steam_update_gate: HTTP {resp.status_code} for the stable manifest")
    except Exception as exc:
        logger.info(f"steam_update_gate: stable manifest fetch failed ({exc})")
    if build:
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            with open(_STABLE_CACHE, "w", encoding="utf-8") as f:
                json.dump({"build": build, "at": time.time()}, f)
        except Exception:
            pass
        return build
    try:
        with open(_STABLE_CACHE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("build") or 0) or None
    except Exception:
        return None


async def slssteam_updates_text(force: bool = False) -> Optional[str]:
    """SLSsteam's res/updates.yaml from upstream (a release that adds a hash
    must show up without waiting for a Steam restart to refresh SLSsteam's own
    cached copy), falling back to our cache, then to SLSsteam's copy. Our copy
    is served without a fetch while younger than feed_cache.FEED_TTL unless
    `force` (manual refresh, install decisions)."""
    if not force and fresh(_SLS_CACHE):
        try:
            with open(_SLS_CACHE, "r", encoding="utf-8") as f:
                text = f.read()
            if "SafeModeHashes" in text:
                return text
        except Exception:
            pass
    try:
        client = await ensure_http_client(context="steam_update_gate")
        resp = await client.get(_SLSSTEAM_UPDATES_URL, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200 and "SafeModeHashes" in resp.text:
            try:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                with open(_SLS_CACHE, "w", encoding="utf-8") as f:
                    f.write(resp.text)
            except Exception:
                pass
            return resp.text
    except Exception as exc:
        logger.info(f"steam_update_gate: SLSsteam updates.yaml fetch failed ({exc})")
    for path in (_SLS_CACHE, os.path.join(real_home(), ".config", "SLSsteam", ".updates.yaml")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            if "SafeModeHashes" in text:
                return text
        except Exception:
            continue
    return None


def slssteam_groups(text: str | None) -> list:
    """SLSsteam's SafeModeHashes as [(tag, [hashes...]), ...] in file order.
    The file is `  <tag>:` groups of `    - <hash> #comment`."""
    groups: list = []
    if not text:
        return groups
    for line in text.splitlines():
        g = _SLS_GROUP_RE.match(line)
        if g:
            groups.append((g.group(1), []))
            continue
        h = _SLS_HASH_RE.match(line)
        if h and groups:
            groups[-1][1].append(h.group(1))
    return groups


def slssteam_tag_for_hash(text: str | None, sha: str | None) -> Optional[str]:
    """The NEWEST SafeModeHashes group tag that lists `sha`: the newest SLSsteam
    release known to hook that client (a release's active group is the newest
    group tagged at or before it, so this is also the tag a downgrade must pin
    SLSsteam to). None when unlisted."""
    if not sha:
        return None
    newest = None
    for tag, hashes in slssteam_groups(text):
        if sha in hashes and (newest is None or tag > newest):
            newest = tag
    return newest


def slssteam_group_for_release(text: str | None, release_tag: str | None) -> Optional[str]:
    """The SafeModeHashes group a release runs with: the newest group tag <= the
    release tag (AceSLS opens a new group only when a release re-derives its
    patterns; releases in between keep the previous group). None when the file
    has no group that old, or no release tag is given."""
    if not release_tag:
        return None
    best = None
    for tag, _hashes in slssteam_groups(text):
        if tag <= release_tag and (best is None or tag > best):
            best = tag
    return best


def slssteam_supports(text: str | None, release_tag: str | None, sha: str | None) -> Optional[bool]:
    """Does SLSsteam release `release_tag` hook client `sha`? True/False when the
    file can answer, None when it can't (no file, no hash, no group that old)."""
    if not sha:
        return None
    group = slssteam_group_for_release(text, release_tag)
    if group is None:
        return None
    for tag, hashes in slssteam_groups(text):
        if tag == group:
            return sha in hashes
    return None


def slssteam_latest_group(text: str | None) -> Optional[str]:
    """The newest group tag in the file: what the latest SLSsteam release runs
    with (and what setup.sh installs when nothing pins it)."""
    tags = [tag for tag, _h in slssteam_groups(text)]
    return max(tags) if tags else None


def slssteam_latest_supports(text: str | None, sha: str | None) -> Optional[bool]:
    """Would the LATEST SLSsteam release hook client `sha`? The question every
    setup.sh run has to ask before installing it on a pinned client."""
    return slssteam_supports(text, "99999999999999", sha)


_HASH_CACHE: dict = {}


def current_client_hash() -> Optional[str]:
    """SHA-256 of the installed ubuntu12_32/steamclient.so — the binary that is
    actually hooked, as opposed to the label in package/*.manifest (which lied
    twice on 2026-10-14: after an interrupted downgrade, and after SteamOS
    re-bootstrapped the client). Cached per (path, size, mtime)."""
    root = find_steam_root()
    if not root:
        return None
    path = os.path.join(root, "ubuntu12_32", "steamclient.so")
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_size, int(st.st_mtime))
    hit = _HASH_CACHE.get(key)
    if hit:
        return hit
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    _HASH_CACHE.clear()
    _HASH_CACHE[key] = h.hexdigest()
    return _HASH_CACHE[key]


def evaluate(stable_build: Optional[int], ll_text: Optional[str], ll_group: Optional[str],
             sls_text: Optional[str], sls_installed: Optional[str]) -> dict:
    """Pure decision. Returns {"state", "blocker", "stable_build", "hash",
    "slssteam_required", "slssteam_installed", "lumalinux_ready"}.

    ready           — lumalinux's latest release and a RELEASED SLSsteam both
                      hook the build Steam would update to. When the installed
                      SLSsteam is older than that release, lifting the pin is
                      still the right first step: Steam updates, the old SLSsteam
                      aborts cleanly on the new build, and the QAM then offers
                      Update (SystemStatus.updateFixesBreak). The other order
                      (update SLSsteam while pinned) was today's crash loop, so
                      "update first" is never advised; slssteam_update_pending
                      records that an update will follow.
    not_yet         — the build is not hooked by SLSsteam's releases (blocker
                      "slssteam"), or lumalinux's feed does not cover it yet
                      (blocker "lumalinux": no hash to check, or latest release
                      does not hook it).
    unknown         — could not find out (no manifest, no feeds)."""
    from headcrab_compat import _build_in_group, _hash_for_build

    out = {"state": "unknown", "blocker": None, "stable_build": stable_build, "hash": None,
           "slssteam_required": None, "slssteam_installed": sls_installed, "lumalinux_ready": None,
           "slssteam_update_pending": False}
    if stable_build is None or ll_text is None:
        return out
    sha = _hash_for_build(ll_text, stable_build)
    out["hash"] = sha
    if sha is None:
        # The cron has not seen this build: no hash to ask SLSsteam about, and
        # lumalinux itself is unverified on it.
        out.update(state="not_yet", blocker="lumalinux")
        return out
    ll_ready = _build_in_group(ll_text, ll_group, stable_build) if ll_group else True
    out["lumalinux_ready"] = ll_ready
    if sls_text is None:
        return out
    required = slssteam_tag_for_hash(sls_text, sha)
    out["slssteam_required"] = required
    if required is None:
        out.update(state="not_yet", blocker="slssteam")
        return out
    if not ll_ready:
        out.update(state="not_yet", blocker="lumalinux")
        return out
    # The installed release's own group decides, never "installed >= required":
    # a newer release can drop a hash an older one carried. Unknown installed
    # (no recorded tag) stays "ready": we can't tell, and the user can update
    # by hand.
    out["slssteam_update_pending"] = bool(
        sls_installed and slssteam_supports(sls_text, sls_installed, sha) is False)
    out.update(state="ready", blocker=None)
    return out


def plan_setup(frozen: bool, sls_text: Optional[str], current_hash: Optional[str],
               gate_for_latest: Optional[dict]) -> dict:
    """What a setup.sh run must do so SLSsteam and the Steam client it runs on
    never end up mismatched. Pure; see install_via_setup for the live wiring.

    setup.sh installs the LATEST SLSsteam. While a pin (ours or headcrab's)
    holds Steam at an older client, that can be the one combination that
    crash-loops Steam (2026-10-14: SLSsteam 20261014151919 on bc54101b; three
    startup crashes and SteamOS re-bootstrapped the client from its image). So,
    with a pin on:

      latest hooks the pinned client      -> install latest, keep the pin.
      latest doesn't, but latest + lumalinux
        hook Valve's current build         -> refuse: press Let Steam update
                                             first. Steam updates, the old
                                             SLSsteam aborts cleanly on the new
                                             build, the QAM offers Update. The
                                             other order (install, then hope the
                                             restart updates Steam before
                                             steamclient.so loads) has a window
                                             that ends in today's crash loop.
      latest doesn't, current build not
        ready either                       -> refuse: wait for the components.
      can't tell (no feed / no hash)       -> install latest as before.

    `gate_for_latest` is evaluate() run with sls_installed = the latest group
    (i.e. "would the latest SLSsteam be ready for Valve's build?").
    Returns {"refuse", "reason"}; the pin is never lifted by an install."""
    plan = {"refuse": None, "reason": "no pin"}
    if not frozen:
        return plan
    supports = slssteam_latest_supports(sls_text, current_hash)
    if supports is True:
        plan["reason"] = "latest SLSsteam hooks the pinned client"
        return plan
    if supports is None:
        plan["reason"] = "feed inconclusive; installing latest"
        return plan
    # Latest SLSsteam has dropped the pinned client.
    if gate_for_latest and gate_for_latest.get("state") == "ready":
        plan.update(refuse="The latest SLSsteam no longer supports the Steam client this device is held at. "
                           "Press Let Steam update first, then Update.",
                    reason="latest SLSsteam dropped the pinned client; Valve's build is ready: lift first")
        return plan
    plan.update(refuse="The latest SLSsteam no longer supports the Steam client this device is held at, "
                       "and the newer Steam build is not supported yet. Installing it would break Steam; wait for the components.",
                reason="latest SLSsteam dropped the pinned client and Valve's build is not ready")
    return plan


async def steam_update_gate(force: bool = False) -> dict:
    """Gather the three sources and evaluate. Network failures degrade to
    "unknown", never raise."""
    from headcrab_compat import _lumalinux_updates_text, latest_release_group
    from slssteam_version import resolve_installed_version

    stable, ll_text, ll_group, sls_text = await asyncio.gather(
        latest_stable_build(force=force),
        _lumalinux_updates_text(force=force),
        latest_release_group(force=force),
        slssteam_updates_text(force=force),
    )
    try:
        sls_installed, _src = await resolve_installed_version()
    except Exception:
        sls_installed = None
    result = evaluate(stable, ll_text, ll_group, sls_text, sls_installed)
    logger.info(
        "steam_update_gate: state=%s blocker=%s stable=%s hash=%s sls_required=%s sls_installed=%s ll_ready=%s",
        result["state"], result["blocker"], result["stable_build"],
        (result["hash"] or "")[:12], result["slssteam_required"], result["slssteam_installed"],
        result["lumalinux_ready"],
    )
    return result

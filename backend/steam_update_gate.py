"""Is it safe to let Steam update? The soft gate behind "Let Steam update".

After a break-recovery downgrade (lumalinux's downgrade.sh) Steam is pinned at an
older build. The user needs to know WHEN lifting the pin is safe, and only the
plugin can know: headcrab's pin says nothing reliable (nosotros.md §4.1-38), so
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

States: ready | update_slssteam | not_yet | unknown (see evaluate()).

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
import os
import re
import time
from typing import Optional

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


async def slssteam_updates_text() -> Optional[str]:
    """SLSsteam's res/updates.yaml from upstream (fresh: a release that adds a
    hash must show up without waiting for a Steam restart to refresh SLSsteam's
    own cached copy), falling back to our cache, then to SLSsteam's copy."""
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

    ready           — lumalinux's latest release and the INSTALLED SLSsteam both
                      hook the build Steam would update to.
    update_slssteam — a released SLSsteam hooks it, but the installed one's
                      pattern group does not (slssteam_supports): update
                      SLSsteam. Whether that update may run on the pinned client
                      is plan_setup()'s question, not this one's.
    not_yet         — the build is not hooked by SLSsteam's releases (blocker
                      "slssteam"), or lumalinux's feed does not cover it yet
                      (blocker "lumalinux": no hash to check, or latest release
                      does not hook it).
    unknown         — could not find out (no manifest, no feeds)."""
    from headcrab_compat import _build_in_group, _hash_for_build

    out = {"state": "unknown", "blocker": None, "stable_build": stable_build, "hash": None,
           "slssteam_required": None, "slssteam_installed": sls_installed, "lumalinux_ready": None}
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
    if sls_installed and slssteam_supports(sls_text, sls_installed, sha) is False:
        out.update(state="update_slssteam", blocker="slssteam")
        return out
    out.update(state="ready", blocker=None)
    return out


def plan_setup(freeze_mine: bool, sls_text: Optional[str], current_hash: Optional[str],
               gate_for_latest: Optional[dict]) -> dict:
    """What a setup.sh run must do so SLSsteam and the Steam client it runs on
    never end up mismatched. Pure; see install_via_setup for the live wiring.

    setup.sh installs the LATEST SLSsteam. While OUR pin holds Steam at an older
    client, that can be the one combination that crash-loops Steam (2026-10-14:
    SLSsteam 20261014151919 on bc54101b; three startup crashes and SteamOS
    re-bootstrapped the client from its image). So, with our pin on:

      latest hooks the pinned client      -> install latest, keep the pin.
      latest doesn't, but latest + lumalinux
        hook Valve's current build         -> install latest and LIFT the pin:
                                             on the restart Steam updates itself
                                             before loading steamclient.so, and
                                             SLSsteam attaches to the new build.
                                             (The step the user did by hand today.)
      latest doesn't, current build not
        ready either                       -> install the newest release that
                                             still hooks the pinned client
                                             (SLSSTEAM_7Z_URL), keep the pin.
      no release hooks the pinned client   -> refuse: any install breaks Steam.
      can't tell (no feed / no hash)       -> pin SLSsteam to a release known to
                                             hook the client when one is known,
                                             else install latest as before.

    `gate_for_latest` is evaluate() run with sls_installed = the latest group
    (i.e. "would the latest SLSsteam be ready for Valve's build?").
    Returns {"override_tag", "lift_after", "refuse", "reason"}."""
    plan = {"override_tag": None, "lift_after": False, "refuse": None, "reason": "no pin"}
    if not freeze_mine:
        return plan
    supports = slssteam_latest_supports(sls_text, current_hash)
    if supports is True:
        plan["reason"] = "latest SLSsteam hooks the pinned client"
        return plan
    fallback = slssteam_tag_for_hash(sls_text, current_hash)
    if supports is None:
        if fallback:
            plan.update(override_tag=fallback, reason="feed inconclusive; pinning SLSsteam to a release known to hook this client")
        else:
            plan["reason"] = "feed inconclusive and no release known for this client; installing latest"
        return plan
    # Latest SLSsteam has dropped the pinned client.
    if gate_for_latest and gate_for_latest.get("state") == "ready":
        plan.update(lift_after=True,
                    reason=f"latest SLSsteam dropped the pinned client; it and lumalinux hook build "
                           f"{gate_for_latest.get('stable_build')}, so the pin is lifted with this install")
        return plan
    if fallback:
        plan.update(override_tag=fallback,
                    reason=f"latest SLSsteam dropped the pinned client and Valve's build is not ready; "
                           f"installing SLSsteam {fallback}, which still hooks it")
        return plan
    plan.update(refuse="No SLSsteam release hooks the Steam client this device is held at, "
                       "and the newer Steam build is not supported yet. Installing would break Steam.",
                reason="no safe SLSsteam for the pinned client")
    return plan


async def steam_update_gate(force: bool = False) -> dict:
    """Gather the three sources and evaluate. Network failures degrade to
    "unknown", never raise."""
    from headcrab_compat import _lumalinux_updates_text, latest_release_group
    from slssteam_version import resolve_installed_version

    stable = await latest_stable_build(force=force)
    ll_text = await _lumalinux_updates_text()
    ll_group = await latest_release_group()
    sls_text = await slssteam_updates_text()
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

"""Is it safe to let Steam update? The soft gate behind "Let Steam update".

After a break-recovery downgrade (lumalinux's downgrade.sh) Steam is pinned at an
older build. The user needs to know WHEN lifting the pin is safe, and only the
plugin can know: headcrab's pin says nothing reliable (nosotros.md §4.1-29), so
this asks the three sources that actually decide it, with no headcrab anywhere:

  1. Valve's public client manifest for this install's branch and the LINE the
     running client is on (ubuntu12 for the 32-bit client, steamrt64 for the
     64-bit one; manifest_url) — the build Steam will update to the moment
     the pin is lifted (the bootstrapper fetches this very file). Each line
     has its own build.
  2. lumalinux's res/updates.yaml — maps that build to its steamclient.so hash
     for that client arch (the cron annotates every new build; the 64-bit
     entries carry `# arch: steamrt64`) and says whether the latest lumalinux
     release hooks it.
  3. SLSsteam's res/updates.yaml — lists, per release tag, the hashes that
     release hooks. The hash under a tag = that SLSsteam supports the build; the
     tag also says whether the INSTALLED SLSsteam is new enough.

The result is advice, never a lock: the button stays available in every state,
the description changes. A network failure or a format change on Ace's side
reads as "unknown", so a user is never left without a way back up.

States: ready | not_yet | current | unknown (see evaluate()); ready carries slssteam_update_pending.

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
from paths import STEAM_CLIENT_32, STEAM_CLIENT_64, find_steam_root, real_home

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

# The bootstrapper's own manifest host (see any Steam logs/bootstrap_log.txt):
# it asks for `steam_client_<branch>_<line>` (`steam_client_<line>` with no
# branch), where <line> is the client that runs — ubuntu12 for the 32-bit one,
# steamrt64 for the 64-bit one. Each line has its own current build (the
# 32-bit one stopped at 1792618285; the 64-bit one moves), so the gate must
# ask for the line that runs: on a 64-bit install pinned at 1794536281 the
# 32-bit manifest read "1792618285, supported, update ready" while the 64-bit
# line's 1795048523 was not (a codespace, 2026-11-19).
_MANIFEST_HOST = "https://client-update.fastly.steamstatic.com/"
_SLSSTEAM_UPDATES_URL = "https://raw.githubusercontent.com/AceSLS/SLSsteam/refs/heads/main/res/updates.yaml"
_CACHE_DIR = os.path.join(real_home(), ".cache", "lumadeck")
_STABLE_CACHE = os.path.join(_CACHE_DIR, "steam_stable_build.json")
_SLS_CACHE = os.path.join(_CACHE_DIR, "slssteam_updates.yaml")
_STABLE_TTL = 30 * 60      # Valve's manifest changes a few times a month
_FETCH_TIMEOUT = 5.0

_VERSION_RE = re.compile(r'^\s*"version"\s+"(\d+)"', re.MULTILINE)
_SLS_GROUP_RE = re.compile(r"^  (\d{14}):")
_SLS_HASH_RE = re.compile(r"^\s*-\s*([0-9a-f]{64})\b")


def _client_line(arch: str) -> str:
    """The manifest line of client `arch`: steamrt64 for the 64-bit client,
    ubuntu12 for the 32-bit one."""
    return "steamrt64" if arch == STEAM_CLIENT_64 else "ubuntu12"


def manifest_url(arch: str, branch: Optional[str] = None) -> str:
    """Valve's manifest for the line client `arch` runs on this install's
    branch (package/beta: `steamdeck_stable` on a Deck, `publicbeta` on the
    desktop beta, empty on plain desktop stable)."""
    b = _branch() if branch is None else branch
    line = _client_line(arch)
    name = f"steam_client_{b}_{line}" if b else f"steam_client_{line}"
    return _MANIFEST_HOST + name


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


async def latest_stable_build(force: bool = False, arch: Optional[str] = None) -> Optional[int]:
    """The build Valve currently serves on this install's branch for the line
    client `arch` runs (default: the client that runs), cached 30 min per
    line. None when unreachable and no cache."""
    from paths import steam_client_arch
    arch = arch or steam_client_arch()
    line = _client_line(arch)
    if not force:
        try:
            with open(_STABLE_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if (time.time() - float(cached.get("at", 0)) < _STABLE_TTL and cached.get("build")
                    and cached.get("line") == line):
                return int(cached["build"])
        except Exception:
            pass
    url = manifest_url(arch)
    build = None
    try:
        client = await ensure_http_client(context="steam_update_gate")
        resp = await client.get(url, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200:
            build = parse_manifest_version(resp.text)
        else:
            logger.info(f"steam_update_gate: HTTP {resp.status_code} for {url}")
    except Exception as exc:
        logger.info(f"steam_update_gate: manifest fetch failed for {url} ({exc})")
    if build:
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            with open(_STABLE_CACHE, "w", encoding="utf-8") as f:
                json.dump({"build": build, "line": line, "at": time.time()}, f)
        except Exception:
            pass
        return build
    try:
        with open(_STABLE_CACHE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("line") == line:
            return int(cached.get("build") or 0) or None
    except Exception:
        pass
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


def slssteam_latest_supports(text: str | None, sha: str | None,
                             arch: str = STEAM_CLIENT_32) -> Optional[bool]:
    """Would the latest SLSsteam build FOR CLIENT `arch` hook client `sha`? The
    question every setup.sh run has to ask before installing it on a pinned
    client. "Latest" depends on the architecture since 2026-10-22:

      32-bit (ubuntu12_32): upstream dropped 32-bit support after
        slssteam_version.LAST_32BIT_TAG, so the latest 32-bit build is that
        release, for good, and its group is the one that decides. A 32-bit
        client listed nowhere reads False, as before: no newer 32-bit build will
        ever list it.
      64-bit (steamrt64): the newest group, as the plain rule always said — but
        only once the file lists `sha` somewhere. Upstream has not published a
        64-bit hash yet (its first x86_64 build is a prerelease), so a 64-bit
        client listed nowhere reads None (unknown), never False: "not
        supported" would be a false alarm on every 64-bit Deck, and None lets
        setup.sh install latest as before.
    """
    if arch == STEAM_CLIENT_64:
        if slssteam_tag_for_hash(text, sha) is None:
            return None
        return slssteam_supports(text, "99999999999999", sha)
    from slssteam_version import LAST_32BIT_TAG
    return slssteam_supports(text, LAST_32BIT_TAG, sha)


_HASH_CACHE: dict = {}
_HASH_CACHE_FILE = os.path.join(_CACHE_DIR, "client_hash.json")


def _read_hash_file(key: tuple) -> Optional[str]:
    """The on-disk copy of the last hash, valid only for the same
    (path, size, mtime) — a Steam update changes size and mtime, so a stale
    entry can't be mistaken for the new binary."""
    try:
        with open(_HASH_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if (data.get("path"), data.get("size"), data.get("mtime")) == key \
                and re.fullmatch(r"[0-9a-f]{64}", str(data.get("sha256", ""))):
            return data["sha256"]
    except Exception:
        pass
    return None


def _write_hash_file(key: tuple, sha: str) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_HASH_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"path": key[0], "size": key[1], "mtime": key[2], "sha256": sha}, f)
    except Exception as exc:
        logger.info(f"steam_update_gate: could not write the client hash cache ({exc})")


def current_client_hash() -> Optional[str]:
    """SHA-256 of the installed steamclient.so of the client that RUNS
    (ubuntu12_32/, or steamrt64/ on the 64-bit client — paths.steam_client_arch;
    both trees are on disk, only one is hooked) — the binary that is
    actually hooked, as opposed to the label in package/*.manifest (which lied
    twice on 2026-10-14: after an interrupted downgrade, and after SteamOS
    re-bootstrapped the client). Cached per (path, size, mtime), in memory and
    on disk: hashing the 40 MB file again on every backend start cost seconds
    on a cold disk, and the file only changes when Steam updates."""
    root = find_steam_root()
    if not root:
        return None
    from paths import steam_client_arch
    path = os.path.join(root, steam_client_arch(), "steamclient.so")
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_size, int(st.st_mtime))
    hit = _HASH_CACHE.get(key)
    if hit:
        return hit
    hit = _read_hash_file(key)
    if hit:
        _HASH_CACHE.clear()
        _HASH_CACHE[key] = hit
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
    _write_hash_file(key, _HASH_CACHE[key])
    return _HASH_CACHE[key]


def evaluate(stable_build: Optional[int], ll_text: Optional[str], ll_group: Optional[str],
             sls_text: Optional[str], sls_installed: Optional[str],
             arch: str = STEAM_CLIENT_32, current_build: Optional[int] = None) -> dict:
    """Pure decision for the line client `arch` runs (`stable_build` is Valve's
    build on that line; `current_build` the installed one when known).
    Returns {"state", "blocker", "stable_build", "hash", "slssteam_required",
    "slssteam_installed", "lumalinux_ready"}.

    current         — Valve serves the build already installed (or an older
                      one): nothing to update to, the pin holds nothing back.

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
    if stable_build is None:
        return out
    if current_build is not None and stable_build <= current_build:
        out.update(state="current", blocker=None)
        return out
    if ll_text is None:
        return out
    sha = _hash_for_build(ll_text, stable_build, arch)
    out["hash"] = sha
    if sha is None:
        # The cron has not seen this build: no hash to ask SLSsteam about, and
        # lumalinux itself is unverified on it.
        out.update(state="not_yet", blocker="lumalinux")
        return out
    ll_ready = _build_in_group(ll_text, ll_group, stable_build, arch) if ll_group else True
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
               gate_for_latest: Optional[dict], arch: str = STEAM_CLIENT_32) -> dict:
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
    `arch` is the client that runs (paths.steam_client_arch): "latest" is the
    latest build for that client (slssteam_latest_supports).
    Returns {"refuse", "reason"}; the pin is never lifted by an install."""
    plan = {"refuse": None, "reason": "no pin"}
    if not frozen:
        return plan
    supports = slssteam_latest_supports(sls_text, current_hash, arch)
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
    from headcrab_compat import _lumalinux_updates_text, current_steam_build, latest_release_group
    from paths import steam_client_arch
    from slssteam_version import resolve_installed_version

    # Everything about the line the running client is on: Valve's build for
    # it, the whitelist entries of its arch, the SLSsteam installed for it.
    arch = steam_client_arch()
    stable, ll_text, ll_group, sls_text = await asyncio.gather(
        latest_stable_build(force=force, arch=arch),
        _lumalinux_updates_text(force=force),
        latest_release_group(force=force),
        slssteam_updates_text(force=force),
    )
    try:
        sls_installed, _src = await resolve_installed_version(arch)
    except Exception:
        sls_installed = None
    result = evaluate(stable, ll_text, ll_group, sls_text, sls_installed, arch, current_steam_build())
    logger.info(
        "steam_update_gate: line=%s state=%s blocker=%s stable=%s hash=%s sls_required=%s sls_installed=%s ll_ready=%s",
        _client_line(arch), result["state"], result["blocker"], result["stable_build"],
        (result["hash"] or "")[:12], result["slssteam_required"], result["slssteam_installed"],
        result["lumalinux_ready"],
    )
    return result

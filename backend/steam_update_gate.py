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
"""
from __future__ import annotations

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


def slssteam_tag_for_hash(text: str | None, sha: str | None) -> Optional[str]:
    """The NEWEST SLSsteam release tag whose SafeModeHashes group lists `sha`.
    SLSsteam's file is `  <tag>:` groups of `    - <hash> #comment`; a hash
    carried by several tags means every one of them hooks it, and the newest is
    what "update SLSsteam" would install. None when unlisted."""
    if not text or not sha:
        return None
    group = None
    newest = None
    for line in text.splitlines():
        g = _SLS_GROUP_RE.match(line)
        if g:
            group = g.group(1)
            continue
        h = _SLS_HASH_RE.match(line)
        if h and group and h.group(1) == sha:
            if newest is None or group > newest:
                newest = group
    return newest


def evaluate(stable_build: Optional[int], ll_text: Optional[str], ll_group: Optional[str],
             sls_text: Optional[str], sls_installed: Optional[str]) -> dict:
    """Pure decision. Returns {"state", "blocker", "stable_build", "hash",
    "slssteam_required", "slssteam_installed", "lumalinux_ready"}.

    ready           — lumalinux's latest release and the INSTALLED SLSsteam both
                      hook the build Steam would update to.
    update_slssteam — a released SLSsteam hooks it, but the installed one is
                      older: update SLSsteam first (Components already offers it).
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
    if sls_installed and sls_installed < required:
        out.update(state="update_slssteam", blocker="slssteam")
        return out
    out.update(state="ready", blocker=None)
    return out


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

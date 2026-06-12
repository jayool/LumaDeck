"""Headcrab build-ID compatibility check.

Headcrab pins Steam to a single client build (see `HeadcrabCompatibleClientVer`
in https://raw.githubusercontent.com/Deadboy666/h3adcr-b/main/headcrab.sh).
Deadboy666 bumps that pin whenever Valve ships a new client he has tested
against, which means hardcoding the value in the plugin goes stale within
weeks. We fetch the current pin dynamically from the live script on every
mount of the Settings page, cache the last seen value to disk, and fail
closed if neither network nor cache yields a number.

If the current Steam build differs from the pinned target, running
`headcrab.sh` from Game Mode triggers its downgrade flow, which races
with gamescope's short-session detection and ends up wiping the Steam
dir. The check feeds the gate on every UI surface that invokes Headcrab
(Install Dependencies, Repair SLSsteam Headcrab) so the user is pushed
at Desktop Mode in that case.
"""

from __future__ import annotations

import glob
import os
import re

from http_client import ensure_http_client
from paths import find_steam_root

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


_HEADCRAB_URL = "https://raw.githubusercontent.com/Deadboy666/h3adcr-b/main/headcrab.sh"
_CACHE_DIR = "/home/deck/.cache/lumadeck"
_CACHE_FILE = os.path.join(_CACHE_DIR, "headcrab_target")
_FETCH_TIMEOUT = 5.0


def _manifest_path() -> str | None:
    """Find Steam's installed-client manifest.

    Filename varies by branch — SteamOS Stable writes
    `steam_client_steamdeck_stable_ubuntu12.manifest`, generic Linux Steam
    writes `steam_client_ubuntu12.manifest`, Beta writes
    `steam_client_steamdeck_beta_ubuntu12.manifest`. We glob for any
    `steam_client_*.manifest` in the package dir and pick the most recently
    modified — that's the active channel.
    """
    root = find_steam_root()
    if not root:
        return None
    pkg_dir = os.path.join(root, "package")
    if not os.path.isdir(pkg_dir):
        return None
    candidates = glob.glob(os.path.join(pkg_dir, "steam_client_*.manifest"))
    if not candidates:
        return None
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def current_steam_build() -> int | None:
    """Read the active Steam client build from the manifest.

    The manifest uses Valve's KeyValues format; the line we want looks like:
        "version"               "1781041600"
    """
    path = _manifest_path()
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'^\s*"version"\s+"(\d+)"', line)
                if m:
                    return int(m.group(1))
    except Exception as exc:
        logger.warning(f"headcrab_compat: failed to read manifest at {path}: {exc}")
    return None


def _parse_target(content: str) -> int | None:
    m = re.search(r'^\s*HeadcrabCompatibleClientVer\s*=\s*(\d+)', content, re.MULTILINE)
    return int(m.group(1)) if m else None


def _save_cache(target: int) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(str(target))
    except Exception as exc:
        logger.warning(f"headcrab_compat: failed to write cache: {exc}")


def _load_cache() -> int | None:
    try:
        if not os.path.isfile(_CACHE_FILE):
            return None
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception as exc:
        logger.warning(f"headcrab_compat: failed to read cache: {exc}")
        return None


async def headcrab_target() -> int | None:
    """Fetch the current Headcrab-pinned client version from upstream.

    Live read of `HeadcrabCompatibleClientVer` in Deadboy666/h3adcr-b's
    main branch via LumaDeck's shared HTTP client (handles SSL/CA bundle
    on the PyInstaller-bundled Python that Decky ships). Cached on disk
    after a successful fetch so the check keeps working offline. Fails
    closed (returns None) if neither network nor cache yields a value.
    """
    try:
        client = await ensure_http_client(context="headcrab_compat")
        resp = await client.get(_HEADCRAB_URL, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200:
            target = _parse_target(resp.text)
            if target is not None:
                _save_cache(target)
                return target
            logger.warning("headcrab_compat: fetched script but no HeadcrabCompatibleClientVer line")
        else:
            logger.info(f"headcrab_compat: HTTP {resp.status_code} from upstream, falling back to cache")
    except Exception as exc:
        logger.info(f"headcrab_compat: live fetch failed ({exc}), falling back to cache")

    return _load_cache()


async def check_headcrab_compat() -> dict:
    """Return whether the current Steam build matches Headcrab's pinned target."""
    build = current_steam_build()
    target = await headcrab_target()
    return {
        "success": True,
        "current_build": build,
        "target": target,
        "compatible": (
            build is not None
            and target is not None
            and build == target
        ),
    }

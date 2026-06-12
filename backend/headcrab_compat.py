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

import os
import re
import urllib.request

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
    root = find_steam_root()
    if not root:
        return None
    path = os.path.join(root, "package", "steam_client_ubuntu12.manifest")
    return path if os.path.isfile(path) else None


def current_steam_build() -> int | None:
    """Read the active Steam client build from steam_client_ubuntu12.manifest.

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
        logger.warning(f"headcrab_compat: failed to read manifest: {exc}")
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


def headcrab_target() -> int | None:
    """Fetch the current Headcrab-pinned client version from upstream.

    Live read of `HeadcrabCompatibleClientVer` in Deadboy666/h3adcr-b's
    main branch. Cached on disk after a successful fetch so the check
    keeps working offline. Fails closed (returns None) if neither
    network nor cache yields a value — the UI then treats compatibility
    as unknown and disables the Headcrab-invoking buttons.
    """
    try:
        req = urllib.request.Request(_HEADCRAB_URL, headers={"User-Agent": "lumadeck"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        target = _parse_target(content)
        if target is not None:
            _save_cache(target)
            return target
        logger.warning("headcrab_compat: fetched script but no HeadcrabCompatibleClientVer line")
    except Exception as exc:
        logger.info(f"headcrab_compat: live fetch failed ({exc}), falling back to cache")

    return _load_cache()


def check_headcrab_compat() -> dict:
    """Return whether the current Steam build matches Headcrab's pinned target."""
    build = current_steam_build()
    target = headcrab_target()
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

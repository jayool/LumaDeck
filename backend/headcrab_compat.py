"""Headcrab build-ID compatibility check.

Headcrab pins Steam to a single client build (`HEADCRAB_TARGET`). If the
current installed Steam client is at any other build, running `headcrab.sh`
will trigger its downgrade flow, which in Game Mode races with gamescope's
short-session detection and ends up wiping the Steam dir.

We gate every Headcrab-invoking button in the UI on this check: if the
current build differs from the target, the button is disabled and the user
is pointed at Desktop Mode.
"""

from __future__ import annotations

import os
import re

from paths import find_steam_root

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


HEADCRAB_TARGET = 1780352834


def _manifest_path() -> str | None:
    root = find_steam_root()
    if not root:
        return None
    path = os.path.join(root, "package", "steam_client_ubuntu12.manifest")
    return path if os.path.isfile(path) else None


def current_steam_build() -> int | None:
    """Read the active Steam client build from steam_client_ubuntu12.manifest.

    The manifest uses Valve's KeyValues format; the line we want looks like:
        "version"               "1780352834"
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


def check_headcrab_compat() -> dict:
    """Return whether the current Steam build matches Headcrab's pinned target."""
    build = current_steam_build()
    return {
        "success": True,
        "current_build": build,
        "target": HEADCRAB_TARGET,
        "compatible": build == HEADCRAB_TARGET,
    }

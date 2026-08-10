"""Steam client-update freeze (steam.cfg / BootStrapperInhibitAll) — LumaDeck side.

Headcrab writes a `steam.cfg` in the Steam root with

    BootStrapperInhibitAll=enable
    BootStrapperForceSelfUpdate=disable

to stop Steam's bootstrapper from self-updating — i.e. to pin the client to the
build headcrab just downgraded to. Upstream's `createsteamcfg` is non-overwriting
and NEVER removes the file, so once written the user is frozen on that build
forever until something deletes it.

LumaDeck's model: the freeze exists ONLY during break recovery. The pin is written
by our own downgrade.sh (in shell) during the break-recovery desktop hand-off; the
normal installer (setup.sh) never writes steam.cfg. So:

    steam.cfg present  ⟺  we are held back after a Steam update broke the stack.

The file's presence IS the recovery marker — no separate state. This module only
READS the freeze (read_freeze) and LIFTS it (lift_freeze / maybe_lift_freeze) once
the ecosystem has caught up (the pinned target advanced past our build AND the
latest lumalinux release supports it) — the "update available" signal
check_headcrab_compat() already computes. Lifting = Steam self-updates back up to
the now-supported latest on next launch; the fresh components installed by the same
catch-up run hook it. Lift touches ONLY the two BootStrapper* lines and keeps any
user content, verified.
"""

from __future__ import annotations

import os
import re
import shutil

from paths import find_steam_root

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# The two keys headcrab's createsteamcfg writes. We strip exactly these on lift
# and leave anything the user may have added to steam.cfg untouched.
_FREEZE_LINE_RE = re.compile(
    r"^\s*BootStrapper(?:InhibitAll|ForceSelfUpdate)\s*=", re.IGNORECASE
)
# "frozen" = BootStrapperInhibitAll present and not explicitly turned off.
_INHIBIT_RE = re.compile(
    r"^\s*BootStrapperInhibitAll\s*=\s*(\S+)", re.IGNORECASE | re.MULTILINE
)
_OFF_VALUES = {"disable", "disabled", "0", "no", "false", "off"}


def _steam_cfg_path() -> str | None:
    root = find_steam_root()
    if not root:
        return None
    return os.path.join(root, "steam.cfg")


def read_freeze() -> dict:
    """Whether Steam updates are currently frozen (steam.cfg inhibits bootstrap).

    Returns {"frozen": bool, "path": str|None}. In LumaDeck's model frozen==True
    means "held back after a break" (see module docstring)."""
    path = _steam_cfg_path()
    if not path or not os.path.isfile(path):
        return {"frozen": False, "path": path}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:
        logger.warning("steam_freeze: failed to read %s: %s", path, exc)
        return {"frozen": False, "path": path, "error": str(exc)}
    m = _INHIBIT_RE.search(content)
    frozen = bool(m) and m.group(1).strip().lower() not in _OFF_VALUES
    return {"frozen": frozen, "path": path}


def lift_freeze() -> dict:
    """Remove the Steam-update freeze so Steam can self-update again.

    Strips only headcrab's BootStrapper* lines (keeps any other content). If
    nothing meaningful remains, deletes the file. Backs up to steam.cfg.lumadeck.bak
    first. Verifies the freeze is actually gone before reporting success."""
    path = _steam_cfg_path()
    if not path or not os.path.isfile(path):
        return {"success": True, "lifted": False, "reason": "no steam.cfg"}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        logger.error("steam_freeze: read failed on lift: %s", exc)
        return {"success": False, "error": f"read failed: {exc}"}

    kept = [ln for ln in lines if not _FREEZE_LINE_RE.match(ln)]

    try:
        shutil.copy2(path, path + ".lumadeck.bak")
    except Exception as exc:
        logger.warning("steam_freeze: backup failed (continuing): %s", exc)

    try:
        if any(ln.strip() for ln in kept):
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(kept)
        else:
            # File was only headcrab's freeze — drop it entirely.
            os.remove(path)
    except Exception as exc:
        logger.error("steam_freeze: write/remove failed on lift: %s", exc)
        return {"success": False, "error": f"write/remove failed: {exc}"}

    st = read_freeze()
    if st.get("frozen"):
        return {"success": False, "error": "steam.cfg still frozen after lift"}
    logger.info("steam_freeze: lifted Steam-update freeze at %s", path)
    return {"success": True, "lifted": True, "path": path}


def maybe_lift_freeze(compat: dict) -> dict:
    """Lift the freeze iff we're frozen AND the ecosystem has caught up.

    `compat` is a check_headcrab_compat() result. Caught up ==
        target > current_build  AND  lumalinux_ready is True
    i.e. Headcrab's pin has advanced past the build we're pinned to and the
    latest lumalinux release supports that pin — the same "update available"
    signal the QAM already surfaces. Called as the closing step of a catch-up
    install (installer.install_via_setup), AFTER the fresh components are in
    place, so when Steam self-updates up they hook the new build.

    No-op (lifted=False) when not frozen, when the build/target are unknown, or
    when the ecosystem hasn't caught up yet (e.g. right after a break downgrade,
    where current == pin)."""
    st = read_freeze()
    if not st.get("frozen"):
        return {"success": True, "lifted": False, "reason": "not frozen"}

    current = compat.get("current_build")
    target = compat.get("target")
    ready = compat.get("lumalinux_ready")
    if current is None or target is None:
        return {"success": True, "lifted": False, "reason": "build/target unknown"}
    if not (target > current and ready is True):
        return {"success": True, "lifted": False, "reason": "ecosystem not caught up yet"}

    return lift_freeze()

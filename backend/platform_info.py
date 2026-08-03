"""Platform detection for LumaDeck — the single source of truth for environment
facts that used to be hardcoded to SteamOS / Steam Deck.

**SteamOS is the DEFAULT identity.** When the distro can't be positively
identified as something else, every getter resolves to the value it would have
had before this module existed, so the tested Steam Deck path is unchanged. See
`docs/porting-cachyos.md` for the non-regression contract.

Phase 0 is **detection only**: nothing in the plugin calls this module yet.
Phase 1 routes path / user / session consumers through it one at a time, behind
the characterization tests in `tests/test_platform_info.py`.

All decision logic lives in pure `_*` helpers that take their inputs as
arguments, so they can be tested hermetically with fixtures — no real hardware,
no SteamOS, no CachyOS. The public wrappers only gather real-system inputs and
delegate to those helpers.

NOTE: this file is deliberately NOT named `platform.py` — that would shadow the
Python stdlib `platform` module for everything importing from `backend/`.
"""
from __future__ import annotations

import os
import pwd
from typing import Iterable, Optional

try:
    import dev  # dev-override harness; when the file is absent, get() -> None
except Exception:  # pragma: no cover - dev.py is always present in-tree
    dev = None  # type: ignore


# ---------------------------------------------------------------------------
# os-release / distro
# ---------------------------------------------------------------------------

_OS_RELEASE_PATHS = ("/etc/os-release", "/usr/lib/os-release")

# Fallback identity: an unreadable/empty os-release => behave as SteamOS, so a
# stripped-down or unexpected environment never diverges from the tested path.
DEFAULT_DISTRO = "steamos"


def _parse_os_release(text: str) -> dict:
    """Parse os-release KEY=VALUE lines (quotes stripped, comments/blanks
    skipped). Pure."""
    out: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _distro_id(osr: dict) -> str:
    return (osr.get("ID") or "").strip().lower() or DEFAULT_DISTRO


def _id_like(osr: dict) -> list:
    return [t for t in (osr.get("ID_LIKE") or "").lower().split() if t]


def _is_arch_like(osr: dict) -> bool:
    """True for arch-based distros. Mirrors headcrab's `archcheck` (matches
    `arch`/`cachyos` in ID or ID_LIKE); steamos is arch-based too."""
    return _distro_id(osr) in {"arch", "cachyos", "steamos"} or "arch" in _id_like(osr)


def _read_os_release(paths: Iterable[str] = _OS_RELEASE_PATHS) -> dict:
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                return _parse_os_release(f.read())
        except Exception:
            continue
    return {}


# ---------------------------------------------------------------------------
# real invoking user / home
# ---------------------------------------------------------------------------
# Decky runs the backend as root, so os.path.expanduser("~") is /root. The real
# login user owns the Steam install we read/write. On SteamOS that user is
# `deck`; elsewhere it's whatever the login user is called.

DEFAULT_USER = "deck"


def _resolve_real_user(environ: dict, uid1000_name: Optional[str], euid: int) -> str:
    """Resolve the real desktop user. Pure (all system state is injected).

    On SteamOS (root backend, no SUDO_USER, uid 1000 == deck) this returns
    "deck", reproducing today's hardcoded value."""
    sudo_user = environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        return sudo_user
    if euid != 0:  # not running as root: trust the login env
        for var in ("LOGNAME", "USER"):
            v = environ.get(var)
            if v and v != "root":
                return v
    if uid1000_name and uid1000_name != "root":  # the Decky-as-root case
        return uid1000_name
    return DEFAULT_USER  # last resort: preserve SteamOS behavior


def _resolve_real_home(user: str, pw_home: Optional[str], environ: dict) -> str:
    """Resolve the real user's home dir. Pure. Prefer the passwd entry; ignore
    $HOME when it's root's (Decky-as-root gives /root)."""
    if pw_home:
        return pw_home
    home = environ.get("HOME")
    if home and home != "/root":
        return home
    return f"/home/{user}"


def _uid1000_name() -> Optional[str]:
    try:
        return pwd.getpwuid(1000).pw_name
    except Exception:
        return None


def real_user(environ: Optional[dict] = None) -> str:
    env = os.environ if environ is None else environ
    return _resolve_real_user(env, _uid1000_name(), os.geteuid())


def real_home(user: Optional[str] = None, environ: Optional[dict] = None) -> str:
    env = os.environ if environ is None else environ
    user = user or real_user(env)
    pw_home = None
    try:
        pw_home = pwd.getpwnam(user).pw_dir
    except Exception:
        pass
    return _resolve_real_home(user, pw_home, env)


# ---------------------------------------------------------------------------
# Steam flavor (native vs flatpak)
# ---------------------------------------------------------------------------

FLATPAK_STEAM_ID = "com.valvesoftware.Steam"


def _detect_steam_flavor(native_exists: bool, flatpak_exists: bool) -> str:
    """Native wins (SteamOS/CachyOS ship native Steam); flatpak only when no
    native install is present. Unknown => native, matching today's assumption.
    Pure."""
    if native_exists:
        return "native"
    if flatpak_exists:
        return "flatpak"
    return "native"


def steam_flavor(home: Optional[str] = None) -> str:
    home = home or real_home()
    native = (
        os.path.isdir(os.path.join(home, ".local/share/Steam"))
        or os.path.isdir(os.path.join(home, ".steam/steam"))
    )
    flatpak = os.path.isdir(os.path.join(home, ".var/app", FLATPAK_STEAM_ID))
    return _detect_steam_flavor(native, flatpak)


# ---------------------------------------------------------------------------
# session / game mode  (best-effort — see docs/porting-cachyos.md open questions)
# ---------------------------------------------------------------------------
# `family` is distro-driven and reliable; `game_mode` is a live check for a
# running gamescope compositor, a best-effort proxy for "currently in Game Mode".

def _session_family(distro: str) -> str:
    """Which gamescope-session lineage this distro belongs to. steamos is its
    own; cachyos/bazzite/chimeraos share the ChimeraOS `gamescope-session`
    lineage (different crash-loop + session-select semantics than SteamOS)."""
    if distro == "steamos":
        return "steamos"
    if distro in ("cachyos", "bazzite", "chimeraos"):
        return distro
    return "unknown"


def _gamescope_running(comms: Iterable[str]) -> bool:
    """True if any process comm is exactly `gamescope`. Pure."""
    return any(c.strip() == "gamescope" for c in comms)


def _iter_proc_comms() -> Iterable[str]:
    import glob
    for comm_path in glob.glob("/proc/[0-9]*/comm"):
        try:
            with open(comm_path, "r", errors="replace") as f:
                yield f.read()
        except Exception:
            continue


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def summary(environ: Optional[dict] = None) -> dict:
    """One dict with every resolved platform fact. SteamOS-default throughout.

    A dev override (`data/dev_overrides.json` -> {"platform": {...}}) is merged
    on top, so any field can be forced to preview another distro without
    hardware — same harness the health readers already use.
    """
    env = os.environ if environ is None else environ
    osr = _read_os_release()
    distro = _distro_id(osr)
    user = real_user(env)
    home = real_home(user, env)
    data = {
        "distro": distro,
        "id_like": _id_like(osr),
        "arch_like": _is_arch_like(osr),
        "is_steamos": distro == "steamos",
        "user": user,
        "home": home,
        "steam_flavor": steam_flavor(home),
        "session_family": _session_family(distro),
        "game_mode": _gamescope_running(_iter_proc_comms()),
    }
    try:
        ov = dev.get("platform") if dev is not None else None
    except Exception:
        ov = None
    if isinstance(ov, dict):
        data.update(ov)
    return data

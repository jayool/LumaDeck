"""
Platform detection and path resolution for LumaDeck (Linux/SteamOS).

Centralises all platform-specific logic. On Steam Deck, Decky runs as root
so ~ expands to /root/. We include explicit /home/deck/ paths to handle this.
"""

from __future__ import annotations

import os
from typing import Optional

try:
    import decky  # type: ignore
    _DECKY_AVAILABLE = True
except ImportError:
    _DECKY_AVAILABLE = False

try:
    import platform_info as _platform  # SteamOS-default platform detection
except Exception:  # pragma: no cover - present in-tree; guarded so import can't break
    _platform = None  # type: ignore


# ---------------------------------------------------------------------------
# Plugin directory helpers
# ---------------------------------------------------------------------------

def get_plugin_dir() -> str:
    if _DECKY_AVAILABLE:
        return decky.DECKY_PLUGIN_DIR
    return os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))


def get_backend_dir() -> str:
    return os.path.join(get_plugin_dir(), "backend")


def backend_path(filename: str) -> str:
    return os.path.join(get_backend_dir(), filename)


def data_dir() -> str:
    d = os.path.join(get_backend_dir(), "data")
    os.makedirs(d, exist_ok=True)
    return d


def data_path(filename: str) -> str:
    return os.path.join(data_dir(), filename)


def settings_dir() -> str:
    if _DECKY_AVAILABLE:
        return decky.DECKY_PLUGIN_SETTINGS_DIR
    d = os.path.join(get_plugin_dir(), "defaults")
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Steam path resolution
# ---------------------------------------------------------------------------

# On Steam Deck (Decky runs as root), ~ is /root/ — the real user's home had to
# be listed explicitly, historically hardcoded to /home/deck. It now comes from
# platform_info.real_home(); on SteamOS that resolves to /home/deck, so the list
# below is byte-identical to the previous hardcoded one (pinned by
# tests/test_paths_characterization.py). Any failure resolving it falls back to
# /home/deck, so this can neither break paths.py import nor change the Deck path.


def _real_home() -> str:
    try:
        if _platform is not None:
            h = _platform.real_home()
            if h:
                return h
    except Exception:
        pass
    return "/home/deck"


def _build_steam_paths(home: str, expanded_home: str) -> list:
    """Candidate Steam roots, most-specific first. `home` is the real-user home
    (from platform_info); `expanded_home` is os.path.expanduser("~") (i.e. /root
    when Decky runs as root). With home=/home/deck this reproduces the exact
    historical list. Pure — tested with fixtures."""
    return [
        os.path.join(home, ".local/share/Steam"),
        os.path.join(home, ".steam/steam"),
        os.path.join(expanded_home, ".steam/steam"),
        os.path.join(expanded_home, ".local/share/Steam"),
        "/opt/steam/steam",
        "/usr/local/steam",
    ]


# Resolved once at import. On SteamOS _REAL_HOME == /home/deck, so every list
# built from it below is byte-identical to the previous hardcoded ones.
_REAL_HOME = _real_home()
_EXPANDED_HOME = os.path.expanduser("~")


def _resolve_real_user_safe() -> str:
    try:
        if _platform is not None:
            u = _platform.real_user()
            if u:
                return u
    except Exception:
        pass
    return "deck"


def _resolve_real_uid_safe() -> int:
    try:
        if _platform is not None:
            u = _platform.real_uid()
            if isinstance(u, int) and u >= 0:
                return u
    except Exception:
        pass
    return 1000


_REAL_USER = _resolve_real_user_safe()
_REAL_UID = _resolve_real_uid_safe()


# Public identity façades: backend modules import these from paths (the path/
# identity hub) instead of platform_info directly. Cached at import; every one
# resolves to the SteamOS values (deck / 1000 / /home/deck) on a Steam Deck, and
# is guarded so any resolution failure falls back to them.
def real_user() -> str:
    return _REAL_USER


def real_home() -> str:
    return _REAL_HOME


def real_uid() -> int:
    return _REAL_UID


_STEAM_PATHS = _build_steam_paths(_REAL_HOME, _EXPANDED_HOME)


def _home_candidates(home, expanded, home_rels, expanded_rels=None, extras=()):
    """Generic 'deck-first' candidate list builder: the real-user home entries,
    then the expanded-home (~) entries, then any fixed extras (/opt/...). With
    home=/home/deck this reproduces the historical hardcoded lists exactly.
    Pure — tested with fixtures. `expanded_rels` defaults to `home_rels`."""
    rels_e = home_rels if expanded_rels is None else expanded_rels
    out = [os.path.join(home, r) for r in home_rels]
    out += [os.path.join(expanded, r) for r in rels_e]
    out += list(extras)
    return out


def steam_root_candidates() -> list:
    """Canonical Steam-root candidate list (a fresh copy). The single source of
    truth other modules must use instead of keeping their own hardcoded copy."""
    return list(_STEAM_PATHS)


def home_candidates(home_rels, expanded_rels=None, extras=()) -> list:
    """Public 'deck-first' candidate builder rooted at the resolved real-user
    home (see _home_candidates). Consumers pass only their own relative
    subpaths, so the /home/deck -> real-user generalization lives in ONE place
    (here) rather than being re-hardcoded per module."""
    return _home_candidates(_REAL_HOME, _EXPANDED_HOME, home_rels, expanded_rels, extras)


def find_steam_root() -> Optional[str]:
    """Search well-known locations for the Steam installation."""
    for path in _STEAM_PATHS:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "steam.sh")):
            return path
    for path in _STEAM_PATHS:
        if os.path.isdir(path):
            return path
    return None


def get_stplugin_dir(steam_root: Optional[str] = None) -> Optional[str]:
    root = steam_root or find_steam_root()
    if root is None:
        return None
    return os.path.join(root, "config", "stplug-in")


def get_depotcache_dir(steam_root: Optional[str] = None) -> Optional[str]:
    root = steam_root or find_steam_root()
    if root is None:
        return None
    return os.path.join(root, "depotcache")


# ---------------------------------------------------------------------------
# SLSsteam paths
# ---------------------------------------------------------------------------

_SLSSTEAM_CANDIDATES = _home_candidates(
    _REAL_HOME, _EXPANDED_HOME,
    [".local/share/SLSsteam", "SLSsteam"],
    extras=["/opt/SLSsteam"],
)


def find_slssteam_root() -> str:
    for path in _SLSSTEAM_CANDIDATES:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "SLSsteam.so")):
            return path
    return os.path.expanduser("~/.local/share/SLSsteam")


def get_slssteam_config_dir() -> str:
    # Try the real user's home first since Decky runs as root (on SteamOS this
    # is /home/deck, unchanged).
    deck_path = os.path.join(_REAL_HOME, ".config/SLSsteam")
    if os.path.isdir(deck_path):
        return deck_path
    return os.path.expanduser("~/.config/SLSsteam")


def get_slssteam_config_path() -> str:
    return os.path.join(get_slssteam_config_dir(), "config.yaml")


def check_slssteam_installed() -> bool:
    for path in _SLSSTEAM_CANDIDATES:
        if os.path.isfile(os.path.join(path, "SLSsteam.so")):
            return True
    return False


# ---------------------------------------------------------------------------
# ACCELA paths
# ---------------------------------------------------------------------------

_ACCELA_CANDIDATES = _home_candidates(
    _REAL_HOME, _EXPANDED_HOME,
    [".local/share/ACCELA", "accela"],
)


def find_accela_root() -> Optional[str]:
    for path in _ACCELA_CANDIDATES:
        if os.path.isdir(path):
            return path
    return None


def check_accela_installed() -> bool:
    return find_accela_root() is not None


def get_accela_run_script() -> Optional[str]:
    accela_dir = find_accela_root()
    if not accela_dir:
        return None
    for name in ("launch_debug.sh", "run.sh"):
        script = os.path.join(accela_dir, name)
        if os.path.isfile(script):
            return script
    return None


# ---------------------------------------------------------------------------
# Steam appcache
# ---------------------------------------------------------------------------

def get_steam_appcache_stats_dir() -> Optional[str]:
    """Return path to Steam/appcache/stats/ directory."""
    root = find_steam_root()
    if root:
        return os.path.join(root, "appcache", "stats")
    return None


# ---------------------------------------------------------------------------
# lumalinux paths (32-bit hook library injected via LD_PRELOAD)
# ---------------------------------------------------------------------------

_LUMALINUX_CANDIDATES = _home_candidates(
    _REAL_HOME, _EXPANDED_HOME,
    [".local/share/lumalinux"],
)


def find_lumalinux_root() -> Optional[str]:
    """Return the directory containing liblumalinux.so, or None."""
    for path in _LUMALINUX_CANDIDATES:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "liblumalinux.so")):
            return path
    return None


def check_lumalinux_installed() -> bool:
    return find_lumalinux_root() is not None


def get_lumalinux_so_path() -> Optional[str]:
    root = find_lumalinux_root()
    return os.path.join(root, "liblumalinux.so") if root else None


def get_lumalinux_keys_path() -> str:
    """Path to lumalinux's keys.txt — config lives under ~/.config/, not the
    deploy directory. Returns the path even if the file doesn't exist yet so
    callers can use it as a target."""
    deck_path = os.path.join(_REAL_HOME, ".config/lumalinux/keys.txt")
    if os.path.isfile(deck_path) or os.path.isdir(os.path.dirname(deck_path)):
        return deck_path
    return os.path.expanduser("~/.config/lumalinux/keys.txt")


def get_steamidra_lite_script() -> Optional[str]:
    """Find the bundled steamidra_lite.py tool. Looks under tools/ inside the
    lumalinux deploy root (next to liblumalinux.so)."""
    root = find_lumalinux_root()
    if not root:
        return None
    candidate = os.path.join(root, "tools", "steamidra_lite.py")
    return candidate if os.path.isfile(candidate) else None


def check_lumalinux_active() -> bool:
    """True if liblumalinux.so is mapped into any running process (= the
    LD_PRELOAD inside Steam took effect). Mirrors _check_process_injected
    for SLSsteam."""
    try:
        import glob as _glob
        for maps_path in _glob.glob("/proc/*/maps"):
            try:
                with open(maps_path, "r", errors="replace") as f:
                    if "liblumalinux.so" in f.read():
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def find_lumalinux_status_path() -> Optional[str]:
    """Return the path to lumalinux's status.json if it exists.

    lumalinux writes this from inside the Steam process — XDG_RUNTIME_DIR is
    primary (tmpfs, cleared at logout, so its presence = "Steam ran with
    lumalinux in this session"), with $HOME/.cache as fallback. Decky runs as
    root so we have to look under the deck user's runtime dir explicitly, not
    just $XDG_RUNTIME_DIR (which under root is /run/user/0).
    """
    # The real user's runtime dir (on SteamOS uid 1000 == deck), with the uid
    # 1000 default kept as a belt fallback.
    candidates = [f"/run/user/{real_uid()}/lumalinux/status.json"]
    default_1000 = "/run/user/1000/lumalinux/status.json"
    if default_1000 not in candidates:
        candidates.append(default_1000)
    # Cache fallbacks (lumalinux falls back here if XDG_RUNTIME_DIR is unset).
    candidates += [
        os.path.join(_REAL_HOME, ".cache/lumalinux/status.json"),
        os.path.expanduser("~/.cache/lumalinux/status.json"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def read_lumalinux_status() -> Optional[dict]:
    """Parse status.json. Returns None if the file is missing or unreadable.

    The pid field is cross-checked against /proc — if the writing process is
    no longer running, the snapshot is stale (Steam exited) and we ignore it,
    so the Settings panel doesn't surface zombie health from a previous run.
    """
    path = find_lumalinux_status_path()
    if not path:
        return None
    try:
        import json as _json
        with open(path, "r") as f:
            data = _json.load(f)
        pid = data.get("pid")
        if isinstance(pid, int) and pid > 0 and not os.path.isdir(f"/proc/{pid}"):
            return None
        return data
    except Exception:
        return None


def read_lumalinux_hook(name: str) -> Optional[str]:
    """Outcome of a single lumalinux hook from the live status.json — one of
    "installed" / "failed" / "disabled", or None when we can't tell.

    This is the SHARED primitive behind Capa 2 (the graceful degradations for a
    build whose non-critical patterns moved): brick 3 reads "ShaderDepot", brick 4
    reads "Reconcile".

    None means UNKNOWN and callers MUST treat it as such — never as "failed":
      * Steam isn't running with lumalinux this session (no live snapshot, or the
        pid is stale), or
      * the running .so predates the hook being reported (an older build has no
        "Reconcile" field yet).
    Both Capa 2 actions therefore fire ONLY on a positive "failed" and never on
    unknown, so a degradation (global shader-cache disable / suppressing a game's
    library appearance) is never applied on a guess. The exact unknown-handling
    policy lives with each caller since it differs (see bricks 3 and 4)."""
    status = read_lumalinux_status()
    if not status:
        return None
    hooks = status.get("hooks") or {}
    outcome = hooks.get(name)
    return outcome if isinstance(outcome, str) else None


# ---------------------------------------------------------------------------
# Wrapper-coverage detection (the moon-model injection mechanism)
# ---------------------------------------------------------------------------
#
# setup.sh no longer patches steam.sh (Steam re-extracts steam.sh from its
# manifest whenever the size drifts, so a patch there is transient). Instead it
# interposes a wrapper that exports the injection env (LD_AUDIT for SLSsteam,
# LD_PRELOAD for CloudRedirect + lumalinux) and then execs the real Steam:
#
#   * the wrapper binary lives at ~/.local/share/SLSsteam/path/steam
#   * Desktop reaches it via *steam*.desktop Exec= lines carrying the
#     `X-LumaLinux-Wrapped=1` tag — patched in place (also under
#     /usr/share/applications on a writable-/usr distro), or written as an
#     override shadow under ~/.local/share/applications / ~/.config/autostart
#   * Game Mode reaches it via a systemd drop-in on steam-launcher.service:
#     ~/.config/systemd/user/steam-launcher.service.d/lumalinux.conf
#   * (a shell PATH drop-in also exists but only covers a terminal `steam` — it
#     is NOT counted as coverage; see _wrapper_coverage_present for why.)
#
# So the wrapper-model analogue of "steam.sh still carries the LD_PRELOAD block"
# is "the wrapper binary is on disk AND a STRONG interposition point (Desktop
# .desktop or the Game Mode drop-in) still routes a Steam launch through it".
# _wrapper_coverage_present() answers exactly that, and replaces the old
# steam.sh injection checks in the health fallbacks: when the stack isn't live
# this session, coverage-present means a plain restart re-injects (not_loaded),
# while coverage-absent means the interposition was lost — a Steam update
# regenerated its own .desktop, an uninstall, a half-run setup — so setup.sh
# must run again (not_injected).
#
# Decky runs as root (~ == /root) so every path is checked under BOTH the real
# user's home and the expanded ~; setup.sh writes them under the real user.

_WRAPPER_REL = ".local/share/SLSsteam/path/steam"
_WRAPPER_DESKTOP_TAG = "X-LumaLinux-Wrapped=1"
_GM_DROPIN_REL = ".config/systemd/user/steam-launcher.service.d/lumalinux.conf"
_GM_DROPIN_DIR_REL = ".config/systemd/user/steam-launcher.service.d"
_GM_LAUNCHER_REL = ".local/share/SLSsteam/lumalinux-steam-launcher"
_WRAPPER_DESKTOP_DIRS_REL = (".local/share/applications", ".config/autostart")

# Byte-identical to setup.sh's install_gamemode_dropin heredoc. `%h` is systemd's
# user-home specifier, so the file is home-agnostic (setup.sh writes the same).
_GM_DROPIN_CONTENT = (
    "# lumalinux Game Mode injection (managed by setup.sh — safe to delete)\n"
    "[Service]\n"
    "ExecStart=\n"
    "ExecStart=%h/.local/share/SLSsteam/lumalinux-steam-launcher\n"
)
# A present-but-healthy drop-in must route through OUR launcher. Anything else
# (missing file, or a file that doesn't name the launcher) is a broken state.
_GM_DROPIN_LAUNCHER_MARK = "lumalinux-steam-launcher"


def _wrapper_homes() -> tuple:
    """The homes setup.sh may have written under: the real user's (Decky runs as
    root, so this is where the artifacts actually land) and the expanded ~."""
    seen = []
    for home in (_REAL_HOME, _EXPANDED_HOME):
        if home and home not in seen:
            seen.append(home)
    return tuple(seen)


def _wrapper_binary_present() -> bool:
    """True if setup.sh's injection wrapper (~/.local/share/SLSsteam/path/steam)
    is on disk."""
    return any(os.path.isfile(os.path.join(h, _WRAPPER_REL)) for h in _wrapper_homes())


def _wrapper_desktop_coverage() -> bool:
    """True if any *steam*.desktop carries the wrapper tag (patched in place or
    written as an override shadow) — i.e. a Desktop launch routes through the
    wrapper. Scans the user's applications/autostart dirs AND the system
    /usr/share/applications: on a distro where /usr is writable setup.sh patches
    the system entry IN PLACE (no home shadow), so a home-only scan would
    false-negative there. On SteamOS /usr is read-only so a shadow lands in the
    home dir instead — both cases covered."""
    import glob as _glob
    dirs = [os.path.join(home, rel) for home in _wrapper_homes()
            for rel in _WRAPPER_DESKTOP_DIRS_REL]
    dirs.append("/usr/share/applications")
    for d in dirs:
        for f in _glob.glob(os.path.join(d, "*steam*.desktop")):
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    if _WRAPPER_DESKTOP_TAG in fh.read():
                        return True
            except Exception:
                continue
    return False


def _wrapper_gamemode_coverage() -> bool:
    """True if the Game Mode systemd drop-in is installed — i.e. a Game Mode
    launch (steam-launcher.service) routes through the wrapper."""
    return any(os.path.isfile(os.path.join(h, _GM_DROPIN_REL)) for h in _wrapper_homes())


def _gm_launcher_present() -> bool:
    """True if setup.sh's Game Mode launcher
    (~/.local/share/SLSsteam/lumalinux-steam-launcher) — the drop-in's ExecStart
    target — is on disk under any home setup.sh may have written to."""
    return any(os.path.isfile(os.path.join(h, _GM_LAUNCHER_REL)) for h in _wrapper_homes())


def _gm_dropin_routes_through_us(home: str) -> bool:
    """True if the drop-in under `home` exists AND names our launcher. A missing
    file, or one that doesn't route through the launcher, is a broken state."""
    try:
        with open(os.path.join(home, _GM_DROPIN_REL), "r",
                  encoding="utf-8", errors="replace") as fh:
            return _GM_DROPIN_LAUNCHER_MARK in fh.read()
    except FileNotFoundError:
        return False
    except Exception:
        # Unreadable — treat as broken so the heal rewrites it.
        return False


def _resolve_bin(name: str, fallbacks: tuple) -> str:
    """Resolve an executable by name, then by absolute-path fallbacks. Decky's
    system service runs with a MINIMAL PATH, so shutil.which() alone can miss
    /usr/bin or /usr/sbin binaries — the exact reason the first daemon-reload
    attempt failed silently (sudo/systemctl not found → FileNotFoundError →
    swallowed as a bare False). Returns `name` as a last resort so the failure is
    at least logged rather than hidden."""
    import shutil
    found = shutil.which(name)
    if found:
        return found
    for cand in fallbacks:
        if os.path.exists(cand):
            return cand
    return name


def _systemctl_user_daemon_reload() -> tuple:
    """Best-effort `systemctl --user daemon-reload` in the REAL user's session, so
    systemd re-reads the freshly-written drop-in without a full reboot (a plain
    Steam restart does NOT reload the --user manager; only this, a session switch,
    or a reboot does). Decky runs us as root in Game Mode, so when euid==0 we cross
    into the deck user's session; when already the real user, we still must inject
    the session env (Decky's spawn env lacks XDG_RUNTIME_DIR/DBUS, so a bare
    `systemctl --user` would fail).

    root→user uses `runuser`, NOT `sudo`: in a systemd-service context sudo can
    need a tty / a writable rootfs for its timestamp, whereas runuser needs
    neither (both return 0 when tested by hand as root, so runuser is the safer
    encoding). All binaries are resolved to absolute paths (see _resolve_bin)
    because the service PATH is minimal.

    Returns (ok, detail). `detail` (rc + stderr, or the exec error) is logged so a
    failure is diagnosable instead of a silent False. Non-fatal either way: the
    drop-in file still takes effect on the next Game Mode start / session reload."""
    import subprocess
    uid = real_uid()
    runtime = f"/run/user/{uid}"
    env_bin = _resolve_bin("env", ("/usr/bin/env", "/bin/env"))
    systemctl = _resolve_bin("systemctl", ("/usr/bin/systemctl", "/bin/systemctl"))
    session_env = [
        f"HOME={real_home()}",
        f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
    ]
    if os.geteuid() == 0 and uid != 0:
        runuser = _resolve_bin("runuser", ("/usr/sbin/runuser", "/sbin/runuser", "/usr/bin/runuser"))
        argv = [runuser, "-u", real_user(), "--", env_bin, *session_env, systemctl, "--user", "daemon-reload"]
    else:
        argv = [env_bin, *session_env, systemctl, "--user", "daemon-reload"]
    try:
        r = subprocess.run(argv, timeout=20, capture_output=True, text=True)
        detail = f"rc={r.returncode} via={os.path.basename(argv[0])}"
        if r.returncode != 0:
            detail += " err=" + ((r.stderr or r.stdout or "").strip()[:200] or "(no output)")
        return r.returncode == 0, detail
    except Exception as exc:
        return False, f"exec_error={exc}"


def heal_gamemode_dropin() -> dict:
    """Self-heal the Game Mode systemd drop-in on plugin startup.

    Repairs already-installed Decks whose steam-launcher.service drop-in was never
    written or was lost. The historical bug: setup.sh ran from the LumaDeck Desktop
    hand-off (an autostart konsole) before the user bus was up, so its
    `have_user_systemd` guard skipped writing the drop-in entirely — Game Mode then
    launched Steam un-injected and every component showed "Installed", never
    "Active", while Desktop (which uses the .desktop/PATH path, not systemd) worked.
    A Steam/SteamOS update wiping ~/.config/systemd has the same effect. This runs
    as the deck user's session is reachable (Decky backend, Game Mode) and rewrites
    the drop-in, exactly as setup.sh's install_gamemode_dropin would.

    HARD GUARD: only writes the drop-in when the launcher it points at
    (~/.local/share/SLSsteam/lumalinux-steam-launcher) actually exists. Pointing
    steam-launcher.service's ExecStart at a missing binary would break the Game
    Mode Steam launch outright — strictly worse than the un-injected state we heal.

    Idempotent: no-ops when the drop-in already routes through our launcher, and
    when lumalinux isn't installed (the launcher won't exist). Returns
    {"healed": bool, "reason": str, "reloaded": bool, "reload_detail": str}.
    """
    home = _REAL_HOME
    launcher = os.path.join(home, _GM_LAUNCHER_REL)
    dropin = os.path.join(home, _GM_DROPIN_REL)
    dropin_dir = os.path.join(home, _GM_DROPIN_DIR_REL)

    # Guard: never write a drop-in whose ExecStart target is missing — that would
    # brick the Game Mode Steam launch. No launcher ⇒ setup.sh hasn't installed
    # the Game Mode path here (or lumalinux isn't installed) ⇒ nothing to heal.
    if not os.path.isfile(launcher):
        return {"healed": False, "reason": "no_launcher", "reloaded": False}

    # Already routed through us under the real-user home — nothing to do.
    if _gm_dropin_routes_through_us(home):
        return {"healed": False, "reason": "already_ok", "reloaded": False}

    # Write the drop-in owned by the real user (Decky runs us as root; a
    # root-owned file under the deck user's ~/.config/systemd is fragile). Same
    # ownership discipline as desktop_handoff._write_as_deck.
    try:
        os.makedirs(dropin_dir, exist_ok=True)
        with open(dropin, "w", encoding="utf-8") as fh:
            fh.write(_GM_DROPIN_CONTENT)
        os.chmod(dropin, 0o644)
        try:
            import pwd
            pw = pwd.getpwnam(real_user())
            os.chown(dropin_dir, pw.pw_uid, pw.pw_gid)
            os.chown(dropin, pw.pw_uid, pw.pw_gid)
        except Exception:
            pass
    except Exception as exc:
        return {"healed": False, "reason": f"write_failed: {exc}", "reloaded": False}

    reloaded, reload_detail = _systemctl_user_daemon_reload()
    return {"healed": True, "reason": "written", "reloaded": reloaded,
            "reload_detail": reload_detail}


def _wrapper_coverage_present() -> bool:
    """True if setup.sh's injection wrapper is installed AND a STRONG interposition
    point still routes a real Steam launch through it — a patched/shadow .desktop
    (Desktop icon) or the Game Mode systemd drop-in.

    This is the wrapper-model replacement for the old steam.sh injection checks:
    it answers "will the next Steam launch inject the stack?" without a live
    process, to split not_loaded (restart works) from not_injected (re-run setup).

    The shell PATH drop-in is DELIBERATELY NOT a qualifying signal here: it is
    sticky (written to ~/.bashrc on every setup AND every guardian run, removed
    only by --uninstall, and never touched by a Steam update), and it only covers
    a *terminal* `steam` launch — never Game Mode (the Deck's primary surface) or
    the Desktop icon. Counting it would make _wrapper_coverage_present ≈
    _wrapper_binary_present: a Deck whose Game Mode drop-in was lost (systemd
    unavailable at setup, or ~/.config/systemd wiped) would forever report
    not_loaded/"restart" — the injection can't happen, yet the user is never
    routed to the not_injected → re-run-setup path this split exists for."""
    if not _wrapper_binary_present():
        return False
    return _wrapper_desktop_coverage() or _wrapper_gamemode_coverage()


# The load-bearing lumalinux hooks: if one of THESE reports "failed", downloads
# are genuinely broken (a real Steam-build mismatch). DepotKey serves the AES
# keys, GMRC serves the manifest request code, the package-0 finder surfaces the
# content depots. Everything else (BuildDep, ShaderDepot, the Sls* patches) is
# non-critical: BuildDep is pin-only AND disabled outright since SLSsteam 20260714
# owns BuildDepotDependency, so a BuildDep "failed" must NOT trip "Steam build not
# supported". See lumalinux docs/RESEARCH.md §11.6.
_CRITICAL_LUMALINUX_HOOKS = {"DepotKey", "GMRC", "PackageZeroFinder"}


def read_lumalinux_health() -> dict:
    """Resolve lumalinux into a single UI state. Symmetric to read_slssteam_health.

    Shape: {"state": str, "cause": str|None, "version": str|None, "action": str|None}.
    Canonical states (shared with SLSsteam / CloudRedirect):
        not_installed  — .so not on disk                  → install
        not_loaded     — installed, steam.sh still injects it, no live
                         status.json                       → restart Steam
        not_injected   — installed, but the wrapper interposition was lost
                         (e.g. a Steam update regenerated its .desktop, or the
                         wrapper binary is gone)             → re-run setup.sh
        not_supported  — status blocked=hash_unverified (cause "version"), or a
                         hook reported "failed" (cause "hooks") — both mean Steam
                         moved off a build we hook           → fix in Desktop
        healthy        — status present, no block, all hooks installed
    """
    try:
        import dev
        _ov = dev.get("lumalinux_health")
    except Exception:
        _ov = None
    if _ov:
        return dev.health("lumalinux", _ov)
    if not check_lumalinux_installed():
        return {"state": "not_installed", "cause": None, "version": None, "action": "install"}

    status = read_lumalinux_status()
    if status is None:
        # On disk but no live snapshot — Steam not running with lumalinux this
        # session. Mirror SLSsteam's not_loaded vs not_injected split: a plain
        # restart only re-injects if the wrapper interposition is STILL in place
        # (wrapper binary + a patched .desktop / Game Mode drop-in / PATH
        # drop-in). If that coverage was lost — a Steam update regenerated its
        # own .desktop, an uninstall, a half-run setup — a restart won't reload
        # the .so; setup.sh must run again to re-establish the wrapper first.
        if _wrapper_coverage_present():
            return {"state": "not_loaded", "cause": None, "version": None, "action": "restart"}
        return {"state": "not_injected", "cause": "wrapper", "version": None, "action": "install"}

    version = status.get("version")
    blocked = status.get("blocked")
    if blocked:
        # Steam is a build lumalinux can't verify → align Steam in Desktop.
        return {"state": "not_supported", "cause": "version", "version": version, "action": "downgrade"}

    hooks = status.get("hooks") or {}
    critical_failed = [
        name for name, outcome in hooks.items()
        if outcome == "failed" and name in _CRITICAL_LUMALINUX_HOOKS
    ]
    if critical_failed:
        # A load-bearing hook didn't install — in practice the byte patterns
        # moved under a Steam update → not_supported (cause "hooks"), fixed in
        # Desktop. Non-critical misses (BuildDep, ShaderDepot) are ignored: the
        # download pipeline still works, so we stay healthy.
        return {"state": "not_supported", "cause": "hooks", "version": version, "action": "downgrade"}

    return {"state": "healthy", "cause": None, "version": version, "action": None}


# ---------------------------------------------------------------------------
# CloudRedirect paths (32-bit cloud-save RPC hook library, also via LD_PRELOAD)
# ---------------------------------------------------------------------------

_CLOUDREDIRECT_CANDIDATES = _home_candidates(
    _REAL_HOME, _EXPANDED_HOME,
    [".local/share/CloudRedirect"],
)


def find_cloudredirect_root() -> Optional[str]:
    """Return the directory containing cloud_redirect.so, or None."""
    for path in _CLOUDREDIRECT_CANDIDATES:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "cloud_redirect.so")):
            return path
    return None


def check_cloudredirect_installed() -> bool:
    return find_cloudredirect_root() is not None


def get_cloudredirect_so_path() -> Optional[str]:
    root = find_cloudredirect_root()
    return os.path.join(root, "cloud_redirect.so") if root else None


def check_cloudredirect_active() -> bool:
    """True if cloud_redirect.so is mapped into any running process."""
    try:
        import glob as _glob
        for maps_path in _glob.glob("/proc/*/maps"):
            try:
                with open(maps_path, "r", errors="replace") as f:
                    if "cloud_redirect.so" in f.read():
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


_CLOUDREDIRECT_TOKEN_DIRS = [
    os.path.join(_REAL_HOME, ".config/CloudRedirect"),
    os.path.expanduser("~/.config/CloudRedirect"),
]


def check_cloudredirect_authed() -> bool:
    """True if a CloudRedirect provider token file exists. The CR Flatpak ships
    --filesystem=home and its realHomePath() escapes the sandbox, so tokens land
    on the host home as ~/.config/CloudRedirect/tokens_<provider>.json (gdrive,
    onedrive, ...), not under ~/.var/app/. We only check for presence — token
    contents are CR's business."""
    for path in _CLOUDREDIRECT_TOKEN_DIRS:
        if not os.path.isdir(path):
            continue
        try:
            for entry in os.listdir(path):
                if entry.startswith("tokens_") and entry.endswith(".json"):
                    return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# CloudRedirect health — same shape as read_slssteam_health / read_lumalinux_health.
# ---------------------------------------------------------------------------
#
# CR loads via LD_PRELOAD and hooks Steam's transport vtable for cloud RPCs. It
# does NOT unmap on failure either, so /proc alone can't separate "loaded and
# working" from "loaded but vtable hook failed". Its own log
# (~/.config/CloudRedirect/cr_debug.log) is the honest discriminator:
#
#   - "CloudRedirect build X.Y.Z transport=external-curl"     → version (init OK so far)
#   - "Init failed: steamclient.so not found"                  → broken/no_steam
#   - "Init failed: transport vtable not found"                → broken/incompatible
#   - "Init failed: slot N (...) outside steamclient range, incompatible client"
#                                                              → broken/incompatible
#   - "Init failed: transport hook installation failed"        → broken/hook
#
# Kill-switch (~/.config/CloudRedirect/disable) is a deliberate user opt-out,
# not a failure — we surface it but don't nag.


_CR_LOG_PATHS = (
    os.path.join(_REAL_HOME, ".config/CloudRedirect/cr_debug.log"),
    os.path.expanduser("~/.config/CloudRedirect/cr_debug.log"),
)
_CR_DISABLE_PATHS = (
    os.path.join(_REAL_HOME, ".config/CloudRedirect/disable"),
    os.path.expanduser("~/.config/CloudRedirect/disable"),
)


def _cloudredirect_log_path() -> Optional[str]:
    for p in _CR_LOG_PATHS:
        if os.path.isfile(p):
            return p
    return None


def _cloudredirect_kill_switched() -> bool:
    return any(os.path.isfile(p) for p in _CR_DISABLE_PATHS)


def _cloudredirect_log_inspect() -> tuple[Optional[str], Optional[str]]:
    """Return (version, abort_cause) from the live log, or (None, None) if the
    file isn't there. abort_cause is "incompatible" when the vtable couldn't be
    found or its slots are out of range, "no_steam" when steamclient.so wasn't
    found, "hook" when the trampoline install failed. None = no abort line."""
    log = _cloudredirect_log_path()
    if not log:
        return None, None
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None, None

    import re as _re
    version: Optional[str] = None
    m = _re.search(r"CloudRedirect build (\S+)", content)
    if m:
        version = m.group(1)

    cause: Optional[str] = None
    if "Init failed: steamclient.so not found" in content:
        cause = "no_steam"
    elif "Init failed: transport vtable not found" in content:
        cause = "incompatible"
    elif _re.search(r"Init failed: slot \d+ \([^)]+\) outside steamclient range", content):
        cause = "incompatible"
    elif "Init failed: transport hook installation failed" in content:
        cause = "hook"

    return version, cause


def read_cloudredirect_health() -> dict:
    """Resolve CloudRedirect into one UI state. Read-only.

    Canonical states (action in parens):
        not_installed  — .so not on disk                    (install)
        disabled       — ~/.config/CloudRedirect/disable    (none — user choice)
        not_loaded     — not mapped, wrapper coverage present (restart Steam)
        not_injected   — not mapped, wrapper coverage lost (re-run setup.sh)
        not_supported  — mapped + log "Init failed: ..."    (fix in Desktop)
                         (cause "version" for vtable/steam issues, "hooks" for a
                         failed trampoline install)
        not_authed     — healthy hooks + no provider tokens (sign in, desktop)
        healthy        — mapped + clean log + tokens present
    """
    try:
        import dev
        _ov = dev.get("cloudredirect_health")
    except Exception:
        _ov = None
    if _ov:
        return dev.health("cloudredirect", _ov)
    if not check_cloudredirect_installed():
        return {"state": "not_installed", "cause": None, "version": None, "action": "install"}

    if _cloudredirect_kill_switched():
        return {"state": "disabled", "cause": None, "version": None, "action": None}

    mapped = check_cloudredirect_active()
    version, cause = _cloudredirect_log_inspect()

    if not mapped:
        # Symmetric with SLSsteam / lumalinux: CR rides the same wrapper env
        # (LD_PRELOAD). A plain restart only re-injects if the wrapper
        # interposition is STILL in place; if it was lost, setup.sh must run
        # again to re-establish the wrapper first.
        if _wrapper_coverage_present():
            return {"state": "not_loaded", "cause": None, "version": version, "action": "restart"}
        return {"state": "not_injected", "cause": "wrapper", "version": version, "action": "install"}

    if cause:
        # no_steam / incompatible = Steam-side (cause "version"); hook = a failed
        # trampoline install (cause "hooks"). Both → fix in Desktop.
        canon = "hooks" if cause == "hook" else "version"
        return {"state": "not_supported", "cause": canon, "version": version, "action": "downgrade"}

    if not check_cloudredirect_authed():
        return {"state": "not_authed", "cause": None, "version": version, "action": "configure_desktop"}

    return {"state": "healthy", "cause": None, "version": version, "action": None}


# ---------------------------------------------------------------------------
# SLSsteam injection verification
# ---------------------------------------------------------------------------
#
# LumaDeck's actual architecture: setup.sh interposes a launch wrapper
# (~/.local/share/SLSsteam/path/steam) that exports LD_AUDIT before exec-ing
# the real Steam. Desktop reaches it via patched *steam*.desktop entries + a
# PATH drop-in; Game Mode reaches it via a systemd drop-in on
# steam-launcher.service. We do NOT patch steam.sh (Steam re-extracts it from
# its manifest on size drift) and do NOT write /usr/bin/steam (read-only
# rootfs). setup.sh owns the wrapper; the plugin only reads state.
#
# So `verify_slssteam_injected` is purely a status check now:
#   1. Process check: SLSsteam.so mapped in any running process → active.
#   2. Otherwise check wrapper coverage (_wrapper_coverage_present) → the
#      wrapper is installed and a launcher routes through it, so the next
#      Steam launch will inject; needs a restart.
#   3. Otherwise error → wrapper not installed / interposition lost; user
#      needs to re-run setup.sh (Install / Reinject).
#
# No writes. No /usr/bin/steam, no steam.sh rewriting from the plugin.


def _check_process_injected() -> bool:
    """Return True if SLSsteam.so is actually mapped into any running process."""
    try:
        import glob as _glob
        for maps_path in _glob.glob("/proc/*/maps"):
            try:
                with open(maps_path, "r", errors="replace") as _f:
                    if "SLSsteam.so" in _f.read():
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def verify_slssteam_injected() -> dict:
    """Verify SLSsteam injection state. Read-only: never writes anywhere.

    setup.sh owns the launch wrapper (~/.local/share/SLSsteam/path/steam) that
    exports LD_AUDIT before exec-ing Steam, so the plugin has no business
    patching steam.sh (Steam re-extracts it on size drift) or /usr/bin/steam
    (read-only rootfs — the DeckTools-heritage write there surfaced a spurious
    `[Errno 30] Read-only file system` even when SLSsteam was fully functional).
    """
    if not check_slssteam_installed():
        return {"patched": False, "already_ok": False, "error": "SLSsteam not installed"}

    # 1. Ground truth: SLSsteam.so is mapped in a running process. If yes,
    #    injection is actively working — no further checks needed.
    if _check_process_injected():
        return {"patched": False, "already_ok": True, "method": "active", "error": None}

    # 2. Wrapper coverage: the wrapper binary is installed AND a launcher (a
    #    patched/shadow .desktop, the Game Mode systemd drop-in, or the PATH
    #    drop-in) still routes through it. Everything is configured and the next
    #    Steam launch will pick it up; no error, just needs a restart.
    if _wrapper_coverage_present():
        return {
            "patched": False,
            "already_ok": True,
            "method": "wrapper_configured",
            "error": None,
        }

    # 3. Wrapper installed but no launcher routes through it — the interposition
    #    was lost (a Steam update regenerated its .desktop, an uninstall, a
    #    half-run setup). A restart alone won't help; setup.sh must run again.
    if _wrapper_binary_present():
        return {
            "patched": False,
            "already_ok": False,
            "error": "The lumalinux launch wrapper is installed but no Steam launcher routes through it — the interposition was lost. Re-run setup (Reinject).",
        }
    return {
        "patched": False,
        "already_ok": False,
        "error": "The lumalinux launch wrapper is not installed. Re-run setup (Install).",
    }


# ---------------------------------------------------------------------------
# SLSsteam health — the single source of truth for the UI's SLSsteam state.
# ---------------------------------------------------------------------------
#
# SLSsteam does the ownership hook: without it working, no not-owned game
# launches even if it's perfectly downloaded. So the UI needs to tell apart
# "working" from "loaded but broken" — and that's not trivial, because:
#
#   - SLSsteam writes no status file we can read (unlike lumalinux).
#   - Its unload() does NOT unmap the .so (the munmap is commented out
#     upstream, main.cpp:66). So "SLSsteam.so is mapped in /proc" stays TRUE
#     even when SLSsteam aborted and installed zero hooks. The /proc scan
#     cannot, on its own, separate healthy from broken.
#
# The only reliable discriminator is SLSsteam's own log (~/.SLSsteam.log),
# which it truncates and rewrites on every Steam launch (std::ios::out), so
# its lines always describe the current session when the .so is mapped. The
# fatal outcomes each print a distinct "...Aborting..." line.
#
# Resulting states (canonical set, shared across all three components):
#   not_installed  — .so not on disk                         → install
#   not_loaded     — not mapped, wrapper coverage present    → restart Steam
#   not_injected   — not mapped, wrapper coverage lost       → re-run setup.sh
#   not_supported  — mapped + an "Aborting" line in the log  → fix in Desktop
#                    (cause: "version" for the hash abort, "hooks" for the
#                    pattern abort — both mean Steam moved off a build we hook)
#   healthy        — mapped + no abort line                  → nothing


def _slssteam_log_path() -> Optional[str]:
    """Path to SLSsteam's log (~/.SLSsteam.log). Decky runs as root, so the real
    user's home is checked explicitly first (on SteamOS that's /home/deck)."""
    for p in (os.path.join(_REAL_HOME, ".SLSsteam.log"), os.path.expanduser("~/.SLSsteam.log")):
        if os.path.isfile(p):
            return p
    return None


def _slssteam_log_abort_cause() -> Optional[str]:
    """Inspect the current-session log for a fatal abort line.

    Returns "patterns" (byte patterns no longer match — the common breakage
    after a Steam update, fatal regardless of config), "hash" (unknown
    steamclient.so hash with SafeMode on), or None (no fatal line). The soft
    "hash missmatch! Please update :)" warning is intentionally NOT treated as
    fatal — SLSsteam keeps loading after it, so it isn't a broken state.
    """
    log = _slssteam_log_path()
    if not log:
        return None
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None
    if "Failed to find all patterns! Aborting..." in content:
        return "patterns"
    if "Unknown steamclient.so hash! Aborting..." in content:
        return "hash"
    return None


def read_slssteam_health() -> dict:
    """Resolve SLSsteam into one of the UI states. Read-only.

    Shape: {"state": str, "cause": str|None, "action": str|None}. The frontend
    maps state→display string (i18n) and action→button.
    """
    try:
        import dev
        _ov = dev.get("slssteam_health")
    except Exception:
        _ov = None
    if _ov:
        return dev.health("slssteam", _ov)
    if not check_slssteam_installed():
        return {"state": "not_installed", "cause": None, "action": "install"}

    inj = verify_slssteam_injected()
    mapped = inj.get("method") == "active"  # .so present in a running process

    if not mapped:
        if inj.get("method") == "wrapper_configured":
            # Configured, just not loaded yet (Steam not running / not restarted).
            return {"state": "not_loaded", "cause": None, "action": "restart"}
        # Wrapper coverage lost (no launcher routes through it) — injection lost.
        return {"state": "not_injected", "cause": "wrapper", "action": "install"}

    # Mapped — but mapped != working. The log is the only honest discriminator.
    # Both aborts mean Steam moved off a build SLSsteam can hook (patterns after a
    # Steam update, unknown hash under SafeMode) → not_supported, fixed in Desktop.
    cause = _slssteam_log_abort_cause()
    if cause:
        canon = "version" if cause == "hash" else "hooks"
        return {"state": "not_supported", "cause": canon, "action": "downgrade"}
    return {"state": "healthy", "cause": None, "action": None}


def get_platform_summary() -> dict:
    summary = {
        "steam_root": find_steam_root(),
        "slssteam_installed": check_slssteam_installed(),
        "slssteam_root": find_slssteam_root(),
        "accela_installed": check_accela_installed(),
        "accela_dir": find_accela_root(),
        "lumalinux_installed": check_lumalinux_installed(),
        "lumalinux_root": find_lumalinux_root(),
        "lumalinux_active": check_lumalinux_active(),
        "cloudredirect_installed": check_cloudredirect_installed(),
        "cloudredirect_root": find_cloudredirect_root(),
        "cloudredirect_active": check_cloudredirect_active(),
    }
    if summary["slssteam_installed"]:
        summary["slssteam_injection"] = verify_slssteam_injected()
    return summary

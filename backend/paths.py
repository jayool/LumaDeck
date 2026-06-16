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

# On Steam Deck (Decky runs as root), ~ is /root/ — we must list /home/deck/ first.
_STEAM_PATHS = [
    "/home/deck/.local/share/Steam",
    "/home/deck/.steam/steam",
    os.path.expanduser("~/.steam/steam"),
    os.path.expanduser("~/.local/share/Steam"),
    "/opt/steam/steam",
    "/usr/local/steam",
]


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

_SLSSTEAM_CANDIDATES = [
    "/home/deck/.local/share/SLSsteam",
    "/home/deck/SLSsteam",
    os.path.expanduser("~/.local/share/SLSsteam"),
    os.path.expanduser("~/SLSsteam"),
    "/opt/SLSsteam",
]


def find_slssteam_root() -> str:
    for path in _SLSSTEAM_CANDIDATES:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "SLSsteam.so")):
            return path
    return os.path.expanduser("~/.local/share/SLSsteam")


def get_slssteam_config_dir() -> str:
    # Try deck user first since Decky runs as root
    deck_path = "/home/deck/.config/SLSsteam"
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

_ACCELA_CANDIDATES = [
    "/home/deck/.local/share/ACCELA",
    "/home/deck/accela",
    os.path.expanduser("~/.local/share/ACCELA"),
    os.path.expanduser("~/accela"),
]


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
# SLScheevo paths
# ---------------------------------------------------------------------------

_SLSCHEEVO_CANDIDATES = [
    "/home/deck/.local/share/SLScheevo/SLScheevo",
    os.path.expanduser("~/.local/share/SLScheevo/SLScheevo"),
]


def find_slscheevo_binary() -> Optional[str]:
    """Return path to SLScheevo binary, or None if not found."""
    for path in _SLSCHEEVO_CANDIDATES:
        if os.path.isfile(path):
            return path
    # Check plugin data dir with possible binary names
    scheevo_data = os.path.join(data_dir(), "SLScheevo")
    for name in ("SLScheevo", "SLScheevo-Linux"):
        candidate = os.path.join(scheevo_data, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def get_slscheevo_dir() -> str:
    """Return the directory where SLScheevo is (or should be) installed."""
    binary = find_slscheevo_binary()
    if binary:
        return os.path.dirname(binary)
    return os.path.join(data_dir(), "SLScheevo")


def get_slscheevo_login_token_path() -> Optional[str]:
    """Return path to SLScheevo's saved login token, or None."""
    scheevo_dir = get_slscheevo_dir()
    token_path = os.path.join(scheevo_dir, "data", "saved_logins.encrypted")
    if os.path.isfile(token_path):
        return token_path
    return None


def get_steam_appcache_stats_dir() -> Optional[str]:
    """Return path to Steam/appcache/stats/ directory."""
    root = find_steam_root()
    if root:
        return os.path.join(root, "appcache", "stats")
    return None


# ---------------------------------------------------------------------------
# lumalinux paths (32-bit hook library injected via LD_PRELOAD)
# ---------------------------------------------------------------------------

_LUMALINUX_CANDIDATES = [
    "/home/deck/.local/share/lumalinux",
    os.path.expanduser("~/.local/share/lumalinux"),
]


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
    deck_path = "/home/deck/.config/lumalinux/keys.txt"
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
    candidates = [
        # Steam Deck default: deck user is uid 1000.
        "/run/user/1000/lumalinux/status.json",
        # Generic: try pwd.getpwnam('deck') for non-default UIDs.
    ]
    try:
        import pwd as _pwd
        try:
            deck_uid = _pwd.getpwnam("deck").pw_uid
            candidates.append(f"/run/user/{deck_uid}/lumalinux/status.json")
        except KeyError:
            pass
    except Exception:
        pass
    # Cache fallbacks (lumalinux falls back here if XDG_RUNTIME_DIR is unset).
    candidates += [
        "/home/deck/.cache/lumalinux/status.json",
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


def read_lumalinux_health() -> dict:
    """Resolve lumalinux into a single UI state. Symmetric to read_slssteam_health.

    Shape: {"state": str, "cause": str|None, "version": str|None, "action": str|None}.
    States:
        not_installed  — .so not on disk                  → install
        not_active     — installed, no live status.json   → restart Steam (or open it)
        hash_blocked   — status: blocked=hash_unverified  → reinstall (newer lumalinux)
        hooks_failed   — status: any hook in "failed"     → reinstall
        healthy        — status present, no block, all hooks installed
    """
    if not check_lumalinux_installed():
        return {"state": "not_installed", "cause": None, "version": None, "action": "install"}

    status = read_lumalinux_status()
    if status is None:
        # On disk but no live snapshot — Steam not running with lumalinux this
        # session. Distinct from hash_blocked (which DOES write a snapshot).
        return {"state": "not_active", "cause": None, "version": None, "action": "restart"}

    version = status.get("version")
    blocked = status.get("blocked")
    if blocked:
        return {"state": "hash_blocked", "cause": blocked, "version": version, "action": "reinstall"}

    hooks = status.get("hooks") or {}
    failed = [name for name, outcome in hooks.items() if outcome == "failed"]
    if failed:
        return {"state": "hooks_failed", "cause": ",".join(failed), "version": version, "action": "reinstall"}

    return {"state": "healthy", "cause": None, "version": version, "action": None}


# ---------------------------------------------------------------------------
# CloudRedirect paths (32-bit cloud-save RPC hook library, also via LD_PRELOAD)
# ---------------------------------------------------------------------------

_CLOUDREDIRECT_CANDIDATES = [
    "/home/deck/.local/share/CloudRedirect",
    os.path.expanduser("~/.local/share/CloudRedirect"),
]


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
    "/home/deck/.config/CloudRedirect",
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
    "/home/deck/.config/CloudRedirect/cr_debug.log",
    os.path.expanduser("~/.config/CloudRedirect/cr_debug.log"),
)
_CR_DISABLE_PATHS = (
    "/home/deck/.config/CloudRedirect/disable",
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

    States (action in parens):
        not_installed   — .so not on disk                    (install)
        kill_switched   — ~/.config/CloudRedirect/disable    (none — user choice)
        not_active      — installed, .so not in /proc        (restart Steam)
        broken          — mapped + log "Init failed: ..."    (reinstall)
        not_authed      — healthy hooks + no provider tokens (configure in desktop)
        healthy         — mapped + clean log + tokens present
    """
    if not check_cloudredirect_installed():
        return {"state": "not_installed", "cause": None, "version": None, "action": "install"}

    if _cloudredirect_kill_switched():
        return {"state": "kill_switched", "cause": None, "version": None, "action": None}

    mapped = check_cloudredirect_active()
    version, cause = _cloudredirect_log_inspect()

    if not mapped:
        return {"state": "not_active", "cause": None, "version": version, "action": "restart"}

    if cause:
        return {"state": "broken", "cause": cause, "version": version, "action": "reinstall"}

    if not check_cloudredirect_authed():
        return {"state": "not_authed", "cause": None, "version": version, "action": "configure_desktop"}

    return {"state": "healthy", "cause": None, "version": version, "action": None}


# ---------------------------------------------------------------------------
# SLSsteam injection verification
# ---------------------------------------------------------------------------
#
# LumaDeck's actual architecture: Headcrab manages
# ~/.local/share/Steam/steam.sh (lives under user home, survives Steam
# updates because Headcrab's updater reapplies it after each one). The
# SLSsteam injection lives there as an `INJECT_SLS=LD_AUDIT=...` variable
# defined near the top and `export $INJECT_SLS` inside GameLauncher().
# We do NOT write to /usr/bin/steam (the read-only rootfs target the
# old DeckTools fork used) — Headcrab is the source of truth for steam.sh
# and any plugin-side patching there would race with it on every Steam
# update.
#
# So `verify_slssteam_injected` is purely a status check now:
#   1. Process check: SLSsteam.so mapped in any running process → active.
#   2. Otherwise look for INJECT_SLS in ~/.local/share/Steam/steam.sh →
#      Headcrab-configured, will activate on next Steam launch.
#   3. Otherwise error → Headcrab not installed / steam.sh got blown away;
#      user needs to re-run Install Dependencies.
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

    Headcrab owns ~/.local/share/Steam/steam.sh and re-applies INJECT_SLS
    after Steam updates, so the plugin has no business patching it. The
    previous version of this function tried to write to /usr/bin/steam
    (DeckTools heritage) which fails on SteamOS' read-only rootfs and
    surfaces an `[Errno 30] Read-only file system` error in the Platform
    summary even when SLSsteam is fully functional.
    """
    if not check_slssteam_installed():
        return {"patched": False, "already_ok": False, "error": "SLSsteam not installed"}

    # 1. Ground truth: SLSsteam.so is mapped in a running process. If yes,
    #    injection is actively working — no further checks needed.
    if _check_process_injected():
        return {"patched": False, "already_ok": True, "method": "active", "error": None}

    # 2. Headcrab marker: INJECT_SLS variable in steam.sh referencing
    #    SLSsteam.so. Means everything is configured and the next Steam
    #    launch will pick it up; no error, just needs a restart.
    sls_dir = find_slssteam_root()
    sls_so = os.path.join(sls_dir or "", "SLSsteam.so") if sls_dir else None

    for candidate in _STEAM_PATHS:
        steam_sh = os.path.join(candidate, "steam.sh")
        if not os.path.isfile(steam_sh):
            continue
        try:
            with open(steam_sh, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        if "INJECT_SLS=" in content and (sls_so is None or sls_so in content):
            return {
                "patched": False,
                "already_ok": True,
                "method": "steam_sh_configured",
                "error": None,
            }
        # steam.sh exists but isn't Headcrab-patched.
        return {
            "patched": False,
            "already_ok": False,
            "error": "steam.sh has no INJECT_SLS line — Headcrab not installed or steam.sh was overwritten. Re-run Install Dependencies.",
        }

    return {"patched": False, "already_ok": False, "error": "steam.sh not found"}


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
# Resulting states (see also the design in this PR):
#   not_installed     — .so not on disk                         → install
#   not_active        — not mapped, steam.sh has INJECT_SLS     → restart Steam
#   injection_missing — not mapped, steam.sh lost INJECT_SLS    → repair
#   broken            — mapped + an "Aborting" line in the log  → repair
#                       (cause: "patterns" | "hash")
#   healthy           — mapped + no abort line                  → nothing


def _slssteam_log_path() -> Optional[str]:
    """Path to SLSsteam's log (~/.SLSsteam.log). Decky runs as root, so the
    deck user's home is checked explicitly first."""
    for p in ("/home/deck/.SLSsteam.log", os.path.expanduser("~/.SLSsteam.log")):
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
    if not check_slssteam_installed():
        return {"state": "not_installed", "cause": None, "action": "install"}

    inj = verify_slssteam_injected()
    mapped = inj.get("method") == "active"  # .so present in a running process

    if not mapped:
        if inj.get("method") == "steam_sh_configured":
            # Configured, just not loaded yet (Steam not running / not restarted).
            return {"state": "not_active", "cause": None, "action": "restart"}
        # steam.sh has no INJECT_SLS line, or wasn't found — injection is lost.
        return {"state": "injection_missing", "cause": None, "action": "repair"}

    # Mapped — but mapped != working. The log is the only honest discriminator.
    cause = _slssteam_log_abort_cause()
    if cause:
        return {"state": "broken", "cause": cause, "action": "repair"}
    return {"state": "healthy", "cause": None, "action": None}


def get_platform_summary() -> dict:
    summary = {
        "steam_root": find_steam_root(),
        "slssteam_installed": check_slssteam_installed(),
        "slssteam_root": find_slssteam_root(),
        "accela_installed": check_accela_installed(),
        "accela_dir": find_accela_root(),
        "slscheevo_installed": find_slscheevo_binary() is not None,
        "slscheevo_login_ready": get_slscheevo_login_token_path() is not None,
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

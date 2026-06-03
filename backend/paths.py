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


# ---------------------------------------------------------------------------
# SLSsteam injection verification
# ---------------------------------------------------------------------------
#
# On SteamOS/Steam Deck, the correct injection target is /usr/bin/steam
# (on the read-only rootfs — never overwritten by Steam updates).
# We add LD_AUDIT before the final `exec` line in that file.
# Requires steamos-readonly disable/enable around the write.
#
# steam.sh (~/.local/share/Steam/steam.sh) is overwritten by Steam client
# updates and is NOT a reliable injection target on SteamOS.
#
# DO NOT use:
#   - ~/.config/environment.d/ (applies to ALL user services — causes boot freeze)
#   - LD_PRELOAD (Steam bootstrap strips it before re-exec)


_USR_BIN_STEAM = "/usr/bin/steam"


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


def _ld_audit_line(sls_dir: str) -> str:
    lib_inject = os.path.join(sls_dir, "library-inject.so")
    sls_so = os.path.join(sls_dir, "SLSsteam.so")
    if os.path.isfile(lib_inject):
        return f"export LD_AUDIT={lib_inject}:{sls_so}"
    return f"export LD_AUDIT={sls_so}"


def _is_patched(content: str, sls_dir: str) -> bool:
    sls_so = os.path.join(sls_dir, "SLSsteam.so")
    return "export LD_AUDIT=" in content and sls_so in content


def _patch_usr_bin_steam(sls_dir: str) -> dict:
    """Patch /usr/bin/steam by inserting LD_AUDIT before the final exec line."""
    import subprocess
    target = _USR_BIN_STEAM
    try:
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return {"patched": False, "already_ok": False, "error": f"read {target}: {exc}"}

    if _is_patched(content, sls_dir):
        return {"patched": False, "already_ok": True, "method": "usr_bin_steam", "error": None}

    ld_audit = _ld_audit_line(sls_dir)
    lines = content.splitlines(keepends=True)

    # Find last exec line
    exec_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].lstrip().startswith("exec "):
            exec_idx = i
            break

    if exec_idx is None:
        return {"patched": False, "already_ok": False, "error": "exec line not found in /usr/bin/steam"}

    lines.insert(exec_idx, ld_audit + "\n")
    new_content = "".join(lines)

    try:
        subprocess.run(["steamos-readonly", "disable"], check=True, capture_output=True)
    except Exception:
        pass  # may already be disabled or not available

    try:
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp, target)
        result = {"patched": True, "already_ok": False, "method": "usr_bin_steam", "error": None}
    except Exception as exc:
        result = {"patched": False, "already_ok": False, "error": f"write {target}: {exc}"}

    try:
        subprocess.run(["steamos-readonly", "enable"], check=True, capture_output=True)
    except Exception:
        pass

    return result


def verify_slssteam_injected() -> dict:
    if not check_slssteam_installed():
        return {"patched": False, "already_ok": False, "error": "SLSsteam not installed"}

    # 1. Best check: SLSsteam.so actually loaded in a running process
    if _check_process_injected():
        return {"patched": False, "already_ok": True, "method": "active", "error": None}

    sls_dir = find_slssteam_root()

    # 2. Primary: patch /usr/bin/steam (survives Steam updates on SteamOS)
    if os.path.isfile(_USR_BIN_STEAM):
        try:
            with open(_USR_BIN_STEAM, "r", encoding="utf-8") as f:
                content = f.read()
            if _is_patched(content, sls_dir):
                return {"patched": False, "already_ok": True, "method": "usr_bin_steam", "error": None}
        except Exception:
            pass
        return _patch_usr_bin_steam(sls_dir)

    # 3. Fallback: patch steam.sh (desktop Linux)
    steam_sh = None
    for candidate in _STEAM_PATHS:
        path = os.path.join(candidate, "steam.sh")
        if os.path.isfile(path):
            steam_sh = path
            break

    if not steam_sh:
        return {"patched": False, "already_ok": False, "error": "steam.sh not found"}

    try:
        with open(steam_sh, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return {"patched": False, "already_ok": False, "error": f"read failed: {exc}"}

    if _is_patched(content, sls_dir):
        return {"patched": False, "already_ok": True, "method": "steam.sh_ld_audit", "error": None}

    try:
        ld_audit = _ld_audit_line(sls_dir)
        lines = content.splitlines(keepends=True)
        sls_so = os.path.join(sls_dir, "SLSsteam.so")

        # Drop stale SLSsteam LD_AUDIT lines before re-inserting.
        lines = [
            l for l in lines
            if not ("LD_AUDIT=" in l and sls_so in l)
        ]

        # Prefer insertion right before the real Steam client launch.
        insert_idx = None
        for i, line in enumerate(lines):
            if '"$STEAMROOT/$STEAMEXEPATH" "$@"' in line:
                insert_idx = i
                break

        # Fallback for unexpected script variants: before last non-steamcmd exec.
        if insert_idx is None:
            for i in range(len(lines) - 1, -1, -1):
                stripped = lines[i].lstrip()
                if stripped.startswith("exec ") and "steamcmd.sh" not in stripped:
                    insert_idx = i
                    break

        if insert_idx is None:
            insert_idx = len(lines)

        lines.insert(insert_idx, ld_audit + "\n")
        tmp = steam_sh + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("".join(lines))
        os.replace(tmp, steam_sh)
        return {"patched": True, "already_ok": False, "method": "steam.sh_ld_audit", "error": None}
    except Exception as exc:
        return {"patched": False, "already_ok": False, "error": f"write failed: {exc}"}


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

"""EOS proxy (yesyes0649/eos-proxy) — the Epic Online Services leg of the
Online toggle.

Games that run their multiplayer through Epic Online Services log into EOS
with a Steam session ticket (EOS_ECT_STEAM_SESSION_TICKET), which Epic checks
against Valve; an unowned game has no valid ticket and never reaches Epic. The
proxy is a drop-in `EOSSDK-Win64-Shipping.dll` that forwards everything to the
game's real SDK (renamed to `EOSSDK-Win64-Shipping.yes` — that exact name is
what the proxy loads) and rewrites the one call, `EOS_Connect_Login`, to the
device-id credential (EOS_ECT_DEVICEID_ACCESS_TOKEN), which needs nothing.

Mechanics mirror goldberg.py: the original is kept beside the proxy under a
different name, the proxy is verified by SHA-256 (so a game update that
overwrites it is detected as `stale`), and removal is a rename back. The
bundled binary lives in backend/deps/EosProxy/, fetched into the plugin zip by
release.yml from the pinned v1.0.0 release (only a 64-bit build exists).

Caveats the UI must carry (README of the proxy): most games first ask Steam for
a web-API ticket and only then call EOS, so FakeAppId 480 is applied alongside;
games that disabled device-id login in their Epic product cannot be helped; the
proxy writes `epic_proxy.log` next to the game exe.
"""

from __future__ import annotations

import hashlib
import os
import shutil

from paths import backend_path

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

EOS_DLL = "EOSSDK-Win64-Shipping.dll"
EOS_BACKUP = "EOSSDK-Win64-Shipping.yes"     # the proxy forwards to THIS name
# Unreal ships it at Engine/Binaries/ThirdParty/EOSSDK/Win64/ (5 levels) and
# often a copy beside the shipping exe; 6 leaves headroom, assets are pruned.
_MAX_DEPTH = 6
# Directories never worth descending into: fix backups (a copied EOS dll there
# is not a game location) and the usual asset trees.
_PRUNE_PREFIXES = ("luatools-backup-",)
_PRUNE_NAMES = {"content", "paks", "cookedpc", "streamingassets", "videos", "movies", "shadercache"}


def bundled_proxy_path() -> str | None:
    p = backend_path(os.path.join("deps", "EosProxy", EOS_DLL))
    return p if os.path.isfile(p) and os.path.getsize(p) > 0 else None


def _sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def find_eos_dirs(install_path: str) -> list[str]:
    """Directories under install_path holding the EOS SDK dll or our `.yes`
    backup of it, at most _MAX_DEPTH levels down. Sorted for stable output."""
    if not install_path or not os.path.isdir(install_path):
        return []
    base_depth = install_path.rstrip(os.sep).count(os.sep)
    found: list[str] = []
    for root, dirs, files in os.walk(install_path):
        low = {f.lower() for f in files}
        if EOS_DLL.lower() in low or EOS_BACKUP.lower() in low:
            found.append(root)
        if root.count(os.sep) - base_depth >= _MAX_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs
                   if not d.lower().startswith(_PRUNE_PREFIXES) and d.lower() not in _PRUNE_NAMES]
    return sorted(found)


def _dir_state(d: str, proxy_sha: str | None) -> str:
    """none | inactive | active | stale for one directory."""
    dll = os.path.join(d, EOS_DLL)
    bak = os.path.join(d, EOS_BACKUP)
    has_dll, has_bak = os.path.isfile(dll), os.path.isfile(bak)
    if not has_bak:
        return "inactive" if has_dll else "none"
    # Backup present → the proxy was applied here at some point.
    if has_dll and proxy_sha and _sha256(dll) == proxy_sha:
        return "active"
    # dll missing, or it is not our proxy (a game update put a new SDK there).
    return "stale"


def get_eos_proxy_status(install_path: str) -> dict:
    """{"success", "status": none|inactive|active|stale, "locations": [dir, ...],
    "bundled": bool}. Aggregate: any stale → stale; else any active → active;
    else any inactive → inactive; else none."""
    try:
        proxy = bundled_proxy_path()
        proxy_sha = _sha256(proxy) if proxy else None
        dirs = find_eos_dirs(install_path)
        states = [_dir_state(d, proxy_sha) for d in dirs]
        if "stale" in states:
            status = "stale"
        elif "active" in states:
            status = "active"
        elif "inactive" in states:
            status = "inactive"
        else:
            status = "none"
        return {"success": True, "status": status, "locations": dirs, "bundled": proxy is not None}
    except Exception as exc:
        return {"success": False, "error": str(exc), "status": "none", "locations": [], "bundled": False}


def apply_eos_proxy(install_path: str) -> dict:
    """Put the proxy in place of every EOS SDK dll under install_path.

    Per directory: a pristine dll (no `.yes`) is renamed to `.yes`; a `stale`
    location (a `.yes` exists but the dll is not our proxy — the game updated
    and shipped a new SDK) keeps the NEW SDK as the `.yes` (the proxy must
    forward to the SDK the game currently expects) and drops the old one; an
    `active` location is left alone. Then the proxy is copied in and verified.
    Returns {"success", "applied": n, "message"}."""
    try:
        if not install_path or not os.path.isdir(install_path):
            return {"success": False, "error": "Game directory not found"}
        proxy = bundled_proxy_path()
        if not proxy:
            return {"success": False, "error": "EOS proxy not bundled in this build."}
        proxy_sha = _sha256(proxy)
        dirs = find_eos_dirs(install_path)
        if not dirs:
            return {"success": False, "error": "This game does not ship the EOS SDK (no EOSSDK-Win64-Shipping.dll)."}

        applied = 0
        for d in dirs:
            dll = os.path.join(d, EOS_DLL)
            bak = os.path.join(d, EOS_BACKUP)
            state = _dir_state(d, proxy_sha)
            if state == "active":
                continue
            if state == "inactive":
                os.replace(dll, bak)                     # keep the pristine SDK
            elif state == "stale":
                if os.path.isfile(dll):
                    os.replace(dll, bak)                 # the game's NEW SDK wins
                # dll missing with a .yes present: the .yes is the SDK we have.
            shutil.copy2(proxy, dll)
            if _sha256(dll) != proxy_sha:
                return {"success": False, "error": f"Proxy copy failed verification in {d}"}
            applied += 1
        logger.info(f"LumaDeck/EOS: proxy applied in {applied} dir(s) under {install_path}")
        return {"success": True, "applied": applied,
                "message": f"EOS proxy applied to {applied} location(s)"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def remove_eos_proxy(install_path: str) -> dict:
    """Undo apply_eos_proxy: drop the proxy dll and rename `.yes` back. A
    directory with no `.yes` is untouched (nothing of ours there)."""
    try:
        if not install_path or not os.path.isdir(install_path):
            return {"success": False, "error": "Game directory not found"}
        removed = 0
        for d in find_eos_dirs(install_path):
            dll = os.path.join(d, EOS_DLL)
            bak = os.path.join(d, EOS_BACKUP)
            if not os.path.isfile(bak):
                continue
            if os.path.isfile(dll):
                os.remove(dll)
            os.replace(bak, dll)
            removed += 1
        logger.info(f"LumaDeck/EOS: proxy removed from {removed} dir(s) under {install_path}")
        return {"success": True, "removed": removed,
                "message": f"EOS proxy removed from {removed} location(s)"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

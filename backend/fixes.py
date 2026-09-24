"""Game fix lookup, application, and removal logic (async port)."""

from __future__ import annotations

import asyncio
import json
import os
import posixpath
import re
import shutil
import zipfile
from datetime import datetime
from typing import Any, Dict

from downloads import fetch_app_name
from http_client import ensure_http_client
from steam_utils import get_game_install_path_response, _parse_vdf_simple, detect_steam_install_path, get_app_launch_options
from subprocess_env import clean_env
from utils import ensure_temp_download_dir

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

FIX_DOWNLOAD_STATE: Dict[int, Dict[str, Any]] = {}
UNFIX_STATE: Dict[int, Dict[str, Any]] = {}


def _set_fix_download_state(appid: int, update: dict) -> None:
    state = FIX_DOWNLOAD_STATE.get(appid) or {}
    state.update(update)
    FIX_DOWNLOAD_STATE[appid] = state


def _get_fix_download_state(appid: int) -> dict:
    return FIX_DOWNLOAD_STATE.get(appid, {}).copy()


def _set_unfix_state(appid: int, update: dict) -> None:
    state = UNFIX_STATE.get(appid) or {}
    state.update(update)
    UNFIX_STATE[appid] = state


def _get_unfix_state(appid: int) -> dict:
    return UNFIX_STATE.get(appid, {}).copy()


async def check_for_fixes(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    client = await ensure_http_client("CheckForFixes")
    result: Dict[str, Any] = {
        "success": True,
        "appid": appid,
        "gameName": "",
        "genericFix": {"status": 0, "available": False},
        "onlineFix": {"status": 0, "available": False},
    }

    try:
        result["gameName"] = await fetch_app_name(appid) or f"Unknown Game ({appid})"
    except Exception:
        result["gameName"] = f"Unknown Game ({appid})"

    try:
        generic_url = f"https://files.luatools.work/GameBypasses/{appid}.zip"
        resp = await client.head(generic_url, follow_redirects=True, timeout=10)
        result["genericFix"]["status"] = resp.status_code
        result["genericFix"]["available"] = resp.status_code == 200
        if resp.status_code == 200:
            result["genericFix"]["url"] = generic_url
    except Exception:
        pass

    try:
        online_url = f"https://files.luatools.work/OnlineFix1/{appid}.zip"
        resp = await client.head(online_url, follow_redirects=True, timeout=10)
        result["onlineFix"]["status"] = resp.status_code
        result["onlineFix"]["available"] = resp.status_code == 200
        if resp.status_code == 200:
            result["onlineFix"]["url"] = online_url
    except Exception:
        pass

    return result


async def _download_and_extract_fix(appid: int, download_url: str, install_path: str, fix_type: str, game_name: str = "", online: bool = False, replace: bool = False) -> None:
    client = await ensure_http_client("fix download")
    dest_zip = ""
    try:
        if replace:
            # One LuaTools fix per game: the installed one(s) go first, through
            # the normal un-fix (originals restored, FakeAppId / netsock undone),
            # then the new one lands on a clean game. Phase shown as "replacing".
            _set_fix_download_state(appid, {"status": "replacing", "bytesRead": 0, "totalBytes": 0, "error": None})
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _unfix_game_worker, appid, install_path, "")
            st = _get_unfix_state(appid)
            if st.get("status") != "done":
                raise RuntimeError(f"could not remove the installed fix: {st.get('error') or 'unknown error'}")
        dest_root = ensure_temp_download_dir()
        dest_zip = os.path.join(dest_root, f"fix_{appid}.zip")
        _set_fix_download_state(appid, {"status": "downloading", "bytesRead": 0, "totalBytes": 0, "error": None})

        async with client.stream("GET", download_url, follow_redirects=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", "0") or "0")
            _set_fix_download_state(appid, {"totalBytes": total})

            with open(dest_zip, "wb") as output:
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    if _get_fix_download_state(appid).get("status") == "cancelled":
                        raise RuntimeError("cancelled")
                    output.write(chunk)
                    read = int(_get_fix_download_state(appid).get("bytesRead", 0)) + len(chunk)
                    _set_fix_download_state(appid, {"bytesRead": read})

        _set_fix_download_state(appid, {"status": "extracting"})

        # Run extraction in executor (blocking I/O)
        loop = asyncio.get_event_loop()
        written = await loop.run_in_executor(None, _extract_fix_sync, appid, dest_zip, install_path, fix_type, game_name, download_url, online)

        # Our files are in the game dir now: freeze the game so a Steam update
        # does not put Valve's back (pins.freeze_for_files). Before "done", so
        # the frontend's pin re-read on "done" sees the freeze.
        if written:
            try:
                import pins
                await pins.freeze_for_files(appid)
            except Exception as exc:
                logger.warning(f"LumaDeck: could not freeze {appid} after fix: {exc}")
        _set_fix_download_state(appid, {"status": "done", "success": True})

    except Exception as exc:
        if str(exc) == "cancelled":
            try:
                if dest_zip:
                    os.remove(dest_zip)
            except Exception:
                pass
            _set_fix_download_state(appid, {"status": "cancelled", "success": False, "error": "Cancelled by user"})
            return
        logger.warning(f"LumaDeck: Failed to apply fix: {exc}")
        _set_fix_download_state(appid, {"status": "failed", "error": str(exc)})


def _is_path_safe(base_dir: str, member_name: str) -> bool:
    """Check that a zip member path stays within base_dir (prevents Zip Slip).

    A leading '/' or '\\' is treated as archive-root-relative, not as an absolute
    write: some packers (FreeTP / online-fix) store paths like '/EpicFix.ini', and
    rejecting those outright made whole fixes extract nothing. We strip the leading
    separators, then still resolve and require the result to land INSIDE base_dir,
    so real '..' escapes are rejected exactly as before."""
    rel = member_name.lstrip("/\\")
    clean = posixpath.normpath(rel)
    if not clean or clean == "." or clean.startswith("/") or clean.startswith(".."):
        return False
    # Resolve the final destination and verify it's inside base_dir
    resolved = os.path.realpath(os.path.join(base_dir, clean))
    base_resolved = os.path.realpath(base_dir)
    return resolved.startswith(base_resolved + os.sep) or resolved == base_resolved


def _existing_case_rel(install_path: str, rel: str) -> str:
    """Resolve a zip member path against the on-disk spelling of the game dir.

    Fix archives are usually built on Windows, where ``game.exe`` and
    ``Game.exe`` are the same file. On Linux they are two: extracting with the
    archive's spelling dropped the crack BESIDE the original, and the game kept
    launching the untouched original. For every path component that does not
    exist exactly, use the single case-insensitive match on disk when there is
    exactly one; an ambiguous directory is left as the archive spelled it."""
    parts = [part for part in rel.replace("\\", "/").split("/") if part not in ("", ".")]
    resolved = []
    current = install_path
    for part in parts:
        chosen = part
        if not os.path.lexists(os.path.join(current, part)) and os.path.isdir(current):
            try:
                matches = [name for name in os.listdir(current)
                           if name.casefold() == part.casefold()]
            except OSError:
                matches = []
            if len(matches) == 1:
                chosen = matches[0]
        resolved.append(chosen)
        current = os.path.join(current, chosen)
    return "/".join(resolved)


# ---------------------------------------------------------------------------
# Original-file backups (so "unfix" can RESTORE, not just delete)
# ---------------------------------------------------------------------------
#
# A crack routinely OVERWRITES original game files (steam_api64.dll, the exe,
# …). The old flow extracted over them with no copy, and unfix only deleted the
# logged files — so removing a fix left the game missing whatever the crack had
# replaced. We now stash each about-to-be-overwritten original under a per-appid
# backup dir before writing, first-write-wins (keeps the pristine original even
# across layered fixes). unfix then restores from there instead of deleting.
# Files the fix purely ADDED have no backup → unfix deletes them, as before.

def _fix_backup_root(install_path: str, appid: int) -> str:
    return os.path.join(install_path, f"luatools-backup-{appid}")


def _backup_original_file(install_path: str, appid: int, rel_path: str) -> None:
    """Copy an original into the backup dir before a fix overwrites it. No-op if
    the target doesn't exist (a new file) or is already backed up (keep the
    pristine original from before the first fix)."""
    rel = rel_path.replace("\\", "/")
    target = os.path.join(install_path, rel.replace("/", os.sep))
    if not os.path.isfile(target):
        return
    backup_path = os.path.join(_fix_backup_root(install_path, appid), rel.replace("/", os.sep))
    if os.path.exists(backup_path):
        return
    try:
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        shutil.copy2(target, backup_path)
    except Exception:
        logger.warning(f"LumaDeck: could not back up original '{rel}' for {appid}")


def _parse_onlinefix_ini(ini_path: str) -> dict:
    """Read an OnlineFix.ini's [Main] section for the FakeAppId (and RealAppId).

    On Windows the shipped OnlineFix64.dll reads this ini itself at runtime and
    fakes ownership of FakeAppId (480 = Spacewar, the SDK sample everyone is
    authorized for) so multiplayer works. Under Proton there is no such runtime,
    so we mirror what the DLL would do by feeding FakeAppId into SLSsteam.

    Only the [Main] section is scanned: the [DLC] section is also `n=n` pairs and
    would false-positive a bare numeric scan. Returns {} if no FakeAppId is found
    so callers only ever act on what the fix explicitly declares (never a
    hardcoded 480)."""
    result: dict = {}
    try:
        with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return result

    in_main = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_main = stripped.lower() == "[main]"
            continue
        if not in_main:
            continue
        m = re.match(r"\s*RealAppId\s*=\s*(\d+)", line, re.IGNORECASE)
        if m:
            result["realAppId"] = int(m.group(1))
            continue
        m = re.match(r"\s*FakeAppId\s*=\s*(\d+)", line, re.IGNORECASE)
        if m:
            result["fakeAppId"] = int(m.group(1))
    return result


def _apply_onlinefix_fakeappid(appid: int, install_path: str, extracted_files: list) -> int:
    """If the fix dropped an OnlineFix.ini declaring a FakeAppId, register it in
    SLSsteam so Proton has the ownership fake the OnlineFix DLL would set up on
    Windows. Returns the FakeAppId written (0 if none). Best-effort: never raises.

    add_fake_app_id is idempotent and refuses to seed a missing config, so this
    is safe to call unconditionally after any fix extraction."""
    ini_rel = next(
        (r for r in extracted_files if os.path.basename(r).lower() == "onlinefix.ini"),
        None,
    )
    if not ini_rel:
        return 0
    ini_path = os.path.join(install_path, ini_rel.replace("/", os.sep))
    info = _parse_onlinefix_ini(ini_path)
    fake_id = info.get("fakeAppId")
    if not fake_id:
        return 0
    real_id = info.get("realAppId")
    if real_id and real_id != appid:
        logger.warning(
            f"LumaDeck: OnlineFix.ini RealAppId {real_id} != launch appid {appid}; "
            f"keying FakeAppId on {appid} (the id Steam launches)."
        )
    try:
        from slssteam_ops import add_fake_app_id
        res = add_fake_app_id(appid, fake_id)
        if not res.get("success"):
            logger.warning(f"LumaDeck: could not set FakeAppId {appid}->{fake_id}: {res.get('error')}")
            return 0
        logger.info(f"LumaDeck: OnlineFix FakeAppId {appid} -> {fake_id} registered in SLSsteam")
        return fake_id
    except Exception as exc:
        logger.warning(f"LumaDeck: FakeAppId injection failed for {appid}: {exc}")
        return 0


def _extract_fix_sync(appid: int, dest_zip: str, install_path: str, fix_type: str, game_name: str, download_url: str, online: bool = False) -> int:
    """Extract the zip into the game dir and log the [FIX] block. Returns the
    number of files written (0 = nothing landed)."""
    """Synchronous extraction of fix zip (runs in executor)."""
    if not zipfile.is_zipfile(dest_zip):
        # A LuaTools fix is always a real .zip. A non-zip here means the link
        # returned something else (an HTML error page / soft-404) — fail cleanly
        # before touching the game dir instead of crashing mid-extract.
        raise RuntimeError("The download wasn't a zip (the link likely returned an error page).")
    extracted_files = []
    with zipfile.ZipFile(dest_zip, "r") as archive:
        all_names = archive.namelist()
        appid_folder = f"{appid}/"

        top_level = set()
        for name in all_names:
            parts = name.split("/")
            if parts[0]:
                top_level.add(parts[0])

        if len(top_level) == 1 and appid_folder.rstrip("/") in top_level:
            for member in archive.namelist():
                if member.startswith(appid_folder) and member != appid_folder:
                    target_path = member[len(appid_folder):]
                    if not target_path:
                        continue
                    if not _is_path_safe(install_path, target_path):
                        logger.warning(f"Zip Slip blocked: {member}")
                        continue
                    if not member.endswith("/"):
                        target_path = _existing_case_rel(install_path, target_path)
                        if not _is_path_safe(install_path, target_path):
                            logger.warning(f"Zip Slip blocked: {member}")
                            continue
                    source = archive.open(member)
                    target = os.path.join(install_path, target_path)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    if not member.endswith("/"):
                        _backup_original_file(install_path, appid, target_path)
                        with open(target, "wb") as output:
                            output.write(source.read())
                        extracted_files.append(target_path.replace("\\", "/"))
                    source.close()
        else:
            for member in archive.namelist():
                if member.endswith("/"):
                    continue
                # Some packers (FreeTP / online-fix) store paths with a leading '/'
                # ('/EpicFix.ini'). Treat it as archive-root-relative so it lands in
                # the game dir; _is_path_safe still rejects real '..' escapes. Record
                # the CLEAN relative path so the override + un-fix can find it later.
                rel = member.lstrip("/\\")
                if not rel:
                    continue
                if not _is_path_safe(install_path, rel):
                    logger.warning(f"Zip Slip blocked: {member}")
                    continue
                rel = _existing_case_rel(install_path, rel)
                if not _is_path_safe(install_path, rel):
                    logger.warning(f"Zip Slip blocked: {member}")
                    continue
                target = os.path.join(install_path, rel.replace("/", os.sep))
                _backup_original_file(install_path, appid, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as output:
                    output.write(archive.read(member))
                extracted_files.append(rel.replace("\\", "/"))

    # Handle unsteam.ini placeholder replacement
    if fix_type.lower() == "online fix (unsteam)":
        for rel_path in extracted_files:
            if rel_path.lower().endswith("unsteam.ini"):
                ini_path = os.path.join(install_path, rel_path.replace("/", os.sep))
                if os.path.exists(ini_path):
                    try:
                        with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
                            contents = f.read()
                        updated = contents.replace("<appid>", str(appid))
                        if updated != contents:
                            with open(ini_path, "w", encoding="utf-8") as f:
                                f.write(updated)
                    except Exception:
                        pass
                break

    # OnlineFix crack: mirror the FakeAppId the shipped DLL would apply on Windows
    # into SLSsteam so the online fix actually works under Proton. Logged below so
    # the un-fix can undo it symmetrically. 0 when the fix declares none.
    applied_fake_id = _apply_onlinefix_fakeappid(appid, install_path, extracted_files)

    # An OnlineFix.ini with a FakeAppId is the definitive "this is an online fix"
    # signal — Denuvo / single-player / generic cracks have no such .ini, so they
    # get neither 480 nor netsock. For a real online fix we also drop the native
    # netsock primitive (non-destructive, inert if the game isn't SNS) so the two
    # routes are covered at once — EXCEPT on anti-cheat games (netsock scans memory
    # → ban). Rides the same signal/lifecycle as the FakeAppId above.
    if applied_fake_id and _netsock_so_installed() and not _has_anticheat(install_path):
        try:
            with open(_netsock_marker_path(install_path, appid), "w", encoding="utf-8") as f:
                f.write("netsock enabled\n")
            logger.info(f"LumaDeck: netsock enabled for online fix {appid}")
        except Exception as exc:
            logger.warning(f"LumaDeck: could not set netsock marker for {appid}: {exc}")

    # Write fix log
    log_file_path = os.path.join(install_path, f"luatools-fix-log-{appid}.log")
    try:
        existing = ""
        if os.path.exists(log_file_path):
            with open(log_file_path, "r", encoding="utf-8") as f:
                existing = f.read()
        with open(log_file_path, "w", encoding="utf-8") as f:
            if existing:
                f.write(existing)
                if not existing.endswith("\n"):
                    f.write("\n")
                f.write("\n---\n\n")
            f.write("[FIX]\n")
            f.write(f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write(f'Game: {game_name or f"Unknown Game ({appid})"}\n')
            f.write(f"Fix Type: {fix_type}\n")
            f.write(f"Download URL: {download_url}\n")
            if applied_fake_id:
                f.write(f"FakeAppId: {applied_fake_id}\n")
            # Explicit online marker from the catalogue's tag, independent of the
            # FakeAppId. Needed for EOS/EpicFix online fixes, which are self-contained
            # (no OnlineFix.ini, no 480) yet are still online fixes — without this they
            # would be misfiled under Fixes & Repairs instead of the Online tab.
            if online:
                f.write("Online: yes\n")
            f.write("Files:\n")
            for fp in extracted_files:
                f.write(f"{fp}\n")
            f.write("[/FIX]\n")
    except Exception:
        pass

    try:
        os.remove(dest_zip)
    except Exception:
        pass
    # "done" is written by the async caller, after the freeze below.
    return len(extracted_files)


# ---------------------------------------------------------------------------
# WINEDLLOVERRIDES support
# ---------------------------------------------------------------------------
#
# A fix that drops Windows DLLs (online fixes: OnlineFix64.dll + winmm/dxgi
# proxies; some generic cracks: a patched steam_api64.dll) only takes effect
# under Proton if Wine is told to load the native DLL instead of its builtin.
# The mechanism is a launch option:
#
#     WINEDLLOVERRIDES="OnlineFix64=n,b;winmm=n,b" %command%
#
# We derive the DLL list from the per-game fix log (the "Files:" entries inside
# each [FIX] block), so the override always reflects exactly the DLLs the
# currently-installed fixes dropped. Re-deriving after an apply OR a remove keeps
# it correct with zero extra bookkeeping: removing a fix deletes its [FIX] block,
# so its DLLs simply drop out of the recomputed set.
#
# Exe-only fixes (e.g. CoD4's iw3sp.exe) yield no DLLs -> no override, exactly as
# before. Goldberg is NOT logged here (separate flow), so it never contributes.


def _installed_fix_dll_stems(appid: int, install_path: str) -> list:
    """Basenames without extension of every .dll any installed fix dropped,
    read from the per-game fix log's [FIX] blocks. Deduped, order-stable."""
    if not install_path:
        return []
    log_file = os.path.join(install_path, f"luatools-fix-log-{appid}.log")
    try:
        if not os.path.isfile(log_file):
            return []
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return []

    stems: list = []
    seen: set = set()
    # Within each [FIX]..[/FIX] block only the "Files:" list holds paths; the
    # header lines (Date/Game/Fix Type/Download URL) never end in .dll, so a
    # plain ".dll line" test is enough.
    for block in content.split("[FIX]")[1:]:
        block = block.split("[/FIX]")[0]
        for line in block.splitlines():
            s = line.strip()
            if s.lower().endswith(".dll"):
                stem = os.path.splitext(os.path.basename(s))[0]
                key = stem.lower()
                if key and key not in seen:
                    seen.add(key)
                    stems.append(stem)
    return stems


def _build_winedll_value(stems: list) -> str:
    """'OnlineFix64=n,b;steam_api64=n,b' (no WINEDLLOVERRIDES= prefix). '' if empty."""
    return ";".join(f"{s}=n,b" for s in stems)


# ---------------------------------------------------------------------------
# netsock (native SteamNetworkingSockets online) support
# ---------------------------------------------------------------------------
#
# netsock (yesyes0649/steamnetsock-patch) is the NATIVE online route: no Windows
# DLLs, no crack. It's a Linux .so that patches the game's coldloaded steamclient
# so SteamNetworkingSockets stops rejecting the faked appid ("Cert is not
# authorized for appid X, only 480"). headcrab already installs it at
# ~/.config/SLSsteam/tools/netsock/netsock.so, so we only add its launch option.
#
# It's applied as a per-game LD_AUDIT launch option that COEXISTS with the
# fix's WINEDLLOVERRIDES on the same line — the two are independent managed
# components (see _merge_launch_options). The path is written literally with
# $HOME (not expanded here): the option is evaluated at launch in the deck
# user's context, and this backend runs as root where ~ would resolve wrong.
# Per-game "on" is a marker file so the launch-option recompute re-emits it.

_NETSOCK_LAUNCH_PATH = "$HOME/.config/SLSsteam/tools/netsock/netsock.so"

# Anti-cheat markers: netsock scans & modifies game memory, which any anti-cheat
# flags → ban. Presence of one of these is a hard stop (never enable netsock).
_ANTICHEAT_MARKERS = ("easyanticheat", "beservice", "battleye", "eac_launcher", "eaclauncher")


def _netsock_marker_path(install_path: str, appid: int) -> str:
    """The online-fix automatism's netsock marker (written when a LuaTools
    online fix declaring a FakeAppId is applied; removed with that fix)."""
    return os.path.join(install_path, f"luatools-netsock-{appid}.on")


# ---------------------------------------------------------------------------
# The Online toggle (per game): FakeAppId 480 + netsock + the EOS proxy when
# the game ships the Epic SDK — the three known doors, applied by detection.
# Its state lives in ONE marker in the game dir, `lumadeck-online-<appid>.json`:
#   {"netsock": bool, "eos": bool, "fakeAppId": bool}
# `fakeAppId` records that the TOGGLE registered the 480 (not a fix, not the
# user), so disable removes exactly what enable added. The online-fix
# automatism keeps its own legacy marker above; the two are independent, and
# netsock is on for a game if either says so.
# ---------------------------------------------------------------------------

def _online_marker_path(install_path: str, appid: int) -> str:
    return os.path.join(install_path, f"lumadeck-online-{appid}.json")


def _read_online_marker(install_path: str, appid: int):
    """The toggle's marker as a dict, or None if the toggle is off."""
    if not install_path:
        return None
    try:
        with open(_online_marker_path(install_path, appid), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return {"netsock": bool(data.get("netsock")), "eos": bool(data.get("eos")),
                "fakeAppId": bool(data.get("fakeAppId"))}
    except Exception:
        return None


def _netsock_enabled(install_path: str, appid: int) -> bool:
    """True if netsock is on for this game: the Online toggle says so, or an
    applied online fix's automatism does (legacy marker)."""
    if not install_path:
        return False
    m = _read_online_marker(install_path, appid)
    if m and m["netsock"]:
        return True
    return os.path.isfile(_netsock_marker_path(install_path, appid))


def _netsock_ld_audit_value(install_path: str, appid: int) -> str:
    """The LD_AUDIT value to inject when netsock is on for this game, else ''."""
    return _NETSOCK_LAUNCH_PATH if _netsock_enabled(install_path, appid) else ""


def _netsock_so_installed() -> bool:
    """True if headcrab's netsock.so is actually on disk (deck home, not root ~)."""
    try:
        from paths import get_slssteam_config_dir
        so = os.path.join(get_slssteam_config_dir(), "tools", "netsock", "netsock.so")
        return os.path.isfile(so) and os.path.getsize(so) > 0
    except Exception:
        return False


def _has_anticheat(install_path: str) -> bool:
    """True if the game ships a known anti-cheat (EAC / BattlEye). Bounded walk
    (depth ≤ 3) — these live at or near the game root, so we don't crawl a whole
    50 GB install."""
    if not install_path or not os.path.isdir(install_path):
        return False
    base_depth = install_path.rstrip(os.sep).count(os.sep)
    try:
        for root, dirs, files in os.walk(install_path):
            for name in list(dirs) + files:
                low = name.lower()
                if any(m in low for m in _ANTICHEAT_MARKERS):
                    return True
            if root.count(os.sep) - base_depth >= 3:
                dirs[:] = []  # prune deeper descent
    except Exception:
        pass
    return False


def installed_fix_types(appid: int, install_path: str) -> list:
    """The `Fix Type:` of every [FIX] block on this game, in log order ("fix"
    when a block has none). Non-empty = a LuaTools fix is installed; Goldberg,
    Steamless and the Online toggle keep no block and do not count."""
    out = []
    for b in _fix_log_blocks(appid, install_path):
        name = "fix"
        for l in b.splitlines():
            st = l.strip()
            if st.startswith("Fix Type:"):
                name = st.partition(":")[2].strip() or "fix"
                break
        out.append(name)
    return out


def _fix_log_blocks(appid: int, install_path: str) -> list:
    """The [FIX] blocks of this game's fix log, as raw text; [] when none."""
    if not install_path:
        return []
    log_file = os.path.join(install_path, f"luatools-fix-log-{appid}.log")
    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return []
    return [b.split("[/FIX]")[0] for b in content.split("[FIX]")[1:]]


def _fix_declares_fakeappid(appid: int, install_path: str) -> bool:
    """A surviving fix registered a FakeAppId (the un-fix logic's own rule for
    "someone still needs the 480")."""
    return any(l.strip().startswith("FakeAppId:")
               for b in _fix_log_blocks(appid, install_path) for l in b.splitlines())


def _has_online_fix(appid: int, install_path: str) -> bool:
    """An online fix (LuaTools "online" tag, or one that declared a FakeAppId)
    is installed on this game."""
    for b in _fix_log_blocks(appid, install_path):
        for l in b.splitlines():
            st = l.strip()
            if st.startswith("Online: yes") or st.startswith("FakeAppId:"):
                return True
    return False


def _installed_fix_launchers(appid: int, install_path: str) -> list:
    """Relpaths of launcher-style .exe files any installed fix dropped — basename
    contains 'launcher' (case-insensitive). From the fix log's [FIX] blocks.

    Some cracks ship their own launcher (e.g. 'FC25 Launcher.exe') that must be
    run instead of the game exe. When present it takes precedence over the DLL
    override: Steam's Play points at the launcher and Proton runs it."""
    if not install_path:
        return []
    log_file = os.path.join(install_path, f"luatools-fix-log-{appid}.log")
    try:
        if not os.path.isfile(log_file):
            return []
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return []

    rels: list = []
    seen: set = set()
    for block in content.split("[FIX]")[1:]:
        block = block.split("[/FIX]")[0]
        for line in block.splitlines():
            s = line.strip()
            if s.lower().endswith(".exe") and "launcher" in os.path.basename(s).lower():
                key = s.lower()
                if key not in seen:
                    seen.add(key)
                    rels.append(s)
    return rels


def _pick_launcher(relpaths: list):
    """Pick the launcher to redirect to: an exact 'launcher.exe' basename wins,
    else the shallowest path (fewest dirs, then shortest). None if empty."""
    if not relpaths:
        return None
    exact = [r for r in relpaths if os.path.basename(r).lower() == "launcher.exe"]
    if exact:
        return exact[0]
    return min(relpaths, key=lambda r: (r.count("/") + r.count("\\"), len(r)))


def _merge_launch_options(current: str, winedll_value: str, launcher_abs: str = "", install_path: str = "", ld_audit_value: str = "") -> str:
    """Merge our managed prefixes into the game's existing launch options.

    Up to two independent managed pieces coexist on the one launch-options line:
      • LD_AUDIT="…netsock.so"  — native online (netsock), when enabled
      • a launcher redirect ("<abs.exe>") OR a WINEDLLOVERRIDES="…" — from the fix
    Composed as `LD_AUDIT="…" WINEDLLOVERRIDES="…" %command%` (both when present).

    Idempotent: strips any prior WINEDLLOVERRIDES, our prior netsock LD_AUDIT
    (scoped to the netsock path so a user's unrelated LD_AUDIT survives), AND a
    leading quoted .exe path inside the game's install dir (our previous launcher
    redirect — the install-dir check means we never clobber a user wrapper like
    mangohud). Then re-adds the current pieces at the front, preserving a single
    %command% and any other options. When nothing is managed and only the
    %command% we added remains, the options are cleared.
    """
    s = re.sub(r'WINEDLLOVERRIDES="[^"]*"\s*', "", current or "").strip()

    # LD_AUDIT is a SINGLE colon-separated list (a second assignment would just
    # override the first at runtime). Collect any existing entries, drop our
    # netsock one, then strip every LD_AUDIT so we can re-emit exactly one below —
    # netsock first, a user's unrelated entries kept after it.
    existing_audit = []
    for _m in re.finditer(r'LD_AUDIT="([^"]*)"', s):
        for _part in _m.group(1).split(":"):
            if _part and "netsock" not in _part.lower() and _part not in existing_audit:
                existing_audit.append(_part)
    s = re.sub(r'LD_AUDIT="[^"]*"\s*', "", s).strip()

    # Strip a leading quoted .exe path that points inside the game dir (ours).
    if install_path:
        norm_install = os.path.normpath(install_path)
        m = re.match(r'"([^"]+\.exe)"\s*', s, re.IGNORECASE)
        if m:
            p = os.path.normpath(m.group(1))
            try:
                inside = os.path.commonpath([norm_install, p]) == norm_install
            except Exception:
                inside = p.startswith(norm_install + os.sep)
            if inside:
                s = s[m.end():].strip()

    managed = []
    audit_parts = ([ld_audit_value] if ld_audit_value else []) + existing_audit
    if audit_parts:
        managed.append(f'LD_AUDIT="{":".join(audit_parts)}"')
    if launcher_abs:
        managed.append(f'"{launcher_abs}"')
    elif winedll_value:
        managed.append(f'WINEDLLOVERRIDES="{winedll_value}"')
    prefix = " ".join(managed)

    if prefix:
        if "%command%" in s:
            return f"{prefix} {s}".strip()
        if s:
            return f"{prefix} {s} %command%".strip()
        return f"{prefix} %command%"
    # Nothing managed: drop a stray lone %command% we likely added; keep real options.
    if s == "%command%":
        return ""
    return s


def compute_fix_launch_options(appid: int, install_path: str) -> dict:
    """Compute the launch-options string the frontend should write for `appid`
    after applying/removing a fix. Reads the current options from localconfig.vdf
    and merges in the WINEDLLOVERRIDES derived from the installed fixes' DLLs.

    The frontend writes the result via SteamClient.Apps.SetAppLaunchOptions —
    the reliable path that the running Steam persists without clobbering."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    # Launcher redirect takes precedence over the DLL override: if a fix shipped
    # its own launcher, point Play at it (Proton runs the launcher, which loads
    # whatever it needs) and skip WINEDLLOVERRIDES entirely.
    launcher_rel = _pick_launcher(_installed_fix_launchers(appid, install_path))
    launcher_abs = ""
    if launcher_rel and install_path:
        launcher_abs = os.path.normpath(
            os.path.join(install_path, launcher_rel.replace("\\", "/"))
        )

    stems = _installed_fix_dll_stems(appid, install_path)
    winedll = "" if launcher_abs else _build_winedll_value(stems)
    # netsock's LD_AUDIT is re-derived from the per-game marker so it survives this
    # recompute (which runs on every fix apply/remove) instead of being lost.
    ld_audit = _netsock_ld_audit_value(install_path, appid)
    current = get_app_launch_options(appid)
    merged = _merge_launch_options(current or "", winedll, launcher_abs, install_path, ld_audit)
    return {
        "success": True,
        "appid": appid,
        "dlls": stems,
        "winedlloverrides": winedll,
        "launcher": launcher_abs or None,
        "ldAudit": ld_audit or None,
        "netsock": bool(ld_audit),
        "launchOptions": merged,
        "changed": (current or "") != merged,
    }


def enable_online(appid: int, install_path: str) -> dict:
    """Turn the Online toggle on for a game, applying the three doors by
    detection:
      - FakeAppId 480 in SLSsteam: always (recorded as ours only if it was not
        there before, so disable never removes a fix's or the user's entry);
      - netsock: when netsock.so is on disk (no anti-cheat gate — the UI carries
        the fixed "do not use with anti-cheat games" warning, netsock's own);
      - the EOS proxy: when the game ships EOSSDK-Win64-Shipping.dll.
    Refuses on a game listed in SLSsteam's DenuvoGames (a ticket-activated
    Denuvo game: FakeAppId would break the activation and online cannot work
    on it anyway). Returns {"success", "applied": {...}, "skipped": {...}}."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    if not install_path or not os.path.exists(install_path):
        return {"success": False, "error": "Install path does not exist"}

    from slssteam_ops import add_fake_app_id, check_fake_app_id_status, is_in_denuvo_games
    from eos_proxy import apply_eos_proxy, get_eos_proxy_status

    if is_in_denuvo_games(appid):
        return {"success": False, "blockedBy": "denuvo",
                "error": "Denuvo-activated game: online is not available."}

    applied = {"fakeAppId": False, "netsock": False, "eos": False}
    skipped: dict = {}
    marker = _read_online_marker(install_path, appid) or {"netsock": False, "eos": False, "fakeAppId": False}

    # FakeAppId 480 — the shared primitive; ours only if we are the one adding it.
    had_fake = bool(check_fake_app_id_status(appid).get("exists"))
    fake_res = add_fake_app_id(appid, 480)
    if fake_res.get("success"):
        applied["fakeAppId"] = True
        marker["fakeAppId"] = marker["fakeAppId"] or not had_fake
    else:
        skipped["fakeAppId"] = fake_res.get("error") or "could not register FakeAppId"

    # netsock — via the LD_AUDIT the launch-options recompute emits.
    if _netsock_so_installed():
        marker["netsock"] = True
        applied["netsock"] = True
    else:
        skipped["netsock"] = "netsock not installed"

    # EOS proxy — only where the game ships the Epic SDK.
    eos = get_eos_proxy_status(install_path)
    if eos.get("status") in ("inactive", "stale", "active"):
        res = apply_eos_proxy(install_path)
        if res.get("success"):
            marker["eos"] = True
            applied["eos"] = True
        else:
            skipped["eos"] = res.get("error") or "EOS proxy failed"
    else:
        skipped["eos"] = "no EOS SDK"

    try:
        with open(_online_marker_path(install_path, appid), "w", encoding="utf-8") as f:
            json.dump(marker, f)
    except Exception as exc:
        return {"success": False, "error": f"Could not write online marker: {exc}"}
    logger.info(f"LumaDeck: online enabled for {appid}: applied={applied} skipped={skipped}")
    return {"success": True, "applied": applied, "skipped": skipped}


def disable_online(appid: int, install_path: str) -> dict:
    """Turn the Online toggle off: drop the marker (the next launch-options
    recompute strips the LD_AUDIT), remove the EOS proxy if we put it, and
    remove the FakeAppId only if the toggle added it and no surviving fix
    declares one. The online-fix automatism's legacy marker is not ours."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    marker = _read_online_marker(install_path, appid)
    if marker is None:
        return {"success": True, "removed": {"eos": False, "fakeAppId": False}}
    removed = {"eos": False, "fakeAppId": False}
    if marker["eos"]:
        from eos_proxy import remove_eos_proxy
        res = remove_eos_proxy(install_path)
        removed["eos"] = bool(res.get("success"))
        if not res.get("success"):
            logger.warning(f"LumaDeck: EOS proxy removal failed for {appid}: {res.get('error')}")
    if marker["fakeAppId"] and not _fix_declares_fakeappid(appid, install_path):
        try:
            from slssteam_ops import remove_fake_app_id
            removed["fakeAppId"] = bool(remove_fake_app_id(appid).get("success"))
        except Exception as exc:
            logger.warning(f"LumaDeck: could not remove FakeAppId for {appid}: {exc}")
    try:
        os.remove(_online_marker_path(install_path, appid))
    except FileNotFoundError:
        pass
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "removed": removed}


def get_online_status(appid: int, install_path: str = "") -> dict:
    """Everything the Online control renders: enabled + what is applied, the
    netsock and EOS facts, whether a Denuvo activation blocks it, and whether
    an online fix is installed (the "try that first" note)."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    from slssteam_ops import is_in_denuvo_games
    from eos_proxy import get_eos_proxy_status
    marker = _read_online_marker(install_path, appid)
    eos = get_eos_proxy_status(install_path) if install_path else {"status": "none", "bundled": False}
    return {
        "success": True,
        "enabled": marker is not None,
        "applied": marker or {"netsock": False, "eos": False, "fakeAppId": False},
        "netsockInstalled": _netsock_so_installed(),
        "eosStatus": eos.get("status", "none"),
        "eosBundled": bool(eos.get("bundled")),
        "blockedBy": "denuvo" if is_in_denuvo_games(appid) else None,
        "hasOnlineFix": _has_online_fix(appid, install_path),
    }


async def apply_game_fix(appid: int, download_url: str, install_path: str, fix_type: str = "", game_name: str = "", online: bool = False, replace: bool = False) -> dict:
    """Queue a fix download + extraction. One LuaTools fix per game: with a
    [FIX] block already on the game and `replace` false nothing is queued and
    the answer carries `needsReplace` + the installed types, for the UI to
    ask; with `replace` true the installed fix(es) are removed first."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    if not download_url or not install_path:
        return {"success": False, "error": "Missing download URL or install path"}
    if not os.path.exists(install_path):
        return {"success": False, "error": "Install path does not exist"}

    installed = installed_fix_types(appid, install_path)
    if installed and not replace:
        return {"success": False, "needsReplace": True, "installed": installed,
                "error": "This game already has a fix installed."}

    _set_fix_download_state(appid, {"status": "queued", "bytesRead": 0, "totalBytes": 0, "error": None})
    asyncio.create_task(_download_and_extract_fix(appid, download_url, install_path, fix_type, game_name, online,
                                                  replace=bool(installed)))
    return {"success": True, "replaced": installed}


def get_apply_fix_status(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    return {"success": True, "state": _get_fix_download_state(appid)}


def cancel_apply_fix(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    state = _get_fix_download_state(appid)
    if not state or state.get("status") in {"done", "failed"}:
        return {"success": True, "message": "Nothing to cancel"}

    _set_fix_download_state(appid, {"status": "cancelled", "success": False, "error": "Cancelled by user"})
    return {"success": True}


def _unfix_game_worker(appid: int, install_path: str, fix_date: str = "") -> None:
    """Synchronous un-fix worker (runs in executor)."""
    try:
        log_file_path = os.path.join(install_path, f"luatools-fix-log-{appid}.log")
        if not os.path.exists(log_file_path):
            _set_unfix_state(appid, {"status": "failed", "error": "No fix log found."})
            return

        _set_unfix_state(appid, {"status": "removing", "progress": "Reading log file..."})
        files_to_delete = set()
        remaining_fixes = []

        with open(log_file_path, "r", encoding="utf-8") as handle:
            log_content = handle.read()

        # Track OnlineFix FakeAppId ownership so we can undo it symmetrically: we
        # only pull the SLSsteam FakeAppId if a removed fix registered one AND no
        # surviving fix still needs it (and never if the user set it by hand — a
        # manual entry leaves no "FakeAppId:" line in any [FIX] block).
        removed_had_fakeid = False
        surviving_has_fakeid = False

        if "[FIX]" in log_content:
            fix_blocks = log_content.split("[FIX]")
            for block in fix_blocks:
                if not block.strip():
                    continue
                lines = block.split("\n")
                in_files_section = False
                block_date = None
                block_fake_id = False
                block_lines = []
                for line in lines:
                    line_stripped = line.strip()
                    if line_stripped == "[/FIX]" or line_stripped == "---":
                        break
                    if line_stripped.startswith("Date:"):
                        block_date = line_stripped.replace("Date:", "").strip()
                    if line_stripped.startswith("FakeAppId:"):
                        block_fake_id = True
                    block_lines.append(line)
                    if line_stripped == "Files:":
                        in_files_section = True
                    elif in_files_section and line_stripped:
                        if not fix_date or (block_date and block_date == fix_date):
                            files_to_delete.add(line_stripped)
                if fix_date and block_date and block_date != fix_date:
                    remaining_fixes.append("[FIX]\n" + "\n".join(block_lines) + "\n[/FIX]")
                    surviving_has_fakeid = surviving_has_fakeid or block_fake_id
                else:
                    removed_had_fakeid = removed_had_fakeid or block_fake_id
        else:
            lines = log_content.split("\n")
            in_files_section = False
            for line in lines:
                line = line.strip()
                if line == "Files:":
                    in_files_section = True
                elif in_files_section and line:
                    files_to_delete.add(line)

        _set_unfix_state(appid, {"status": "removing", "progress": f"Removing {len(files_to_delete)} files..."})
        deleted_count = 0
        restored_count = 0
        backup_root = _fix_backup_root(install_path, appid)
        for file_path in files_to_delete:
            try:
                rel = file_path.replace("\\", "/").replace("/", os.sep)
                full_path = os.path.join(install_path, rel)
                backup_path = os.path.join(backup_root, rel)
                if os.path.isfile(backup_path):
                    # The fix overwrote an original here → put the original back
                    # (over the crack file). COPY, not move: on a legacy install
                    # with two fixes over the same file, the second un-fix must
                    # still find the original. The tree goes when no fix remains.
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    shutil.copy2(backup_path, full_path)
                    restored_count += 1
                elif os.path.exists(full_path):
                    # Purely added by the fix → remove it.
                    os.remove(full_path)
                    deleted_count += 1
            except Exception:
                pass

        # Drop the backup tree only when no fixes remain; otherwise other fixes'
        # originals still live there (restores are copies, see above).
        if not remaining_fixes:
            shutil.rmtree(backup_root, ignore_errors=True)

        if remaining_fixes:
            try:
                with open(log_file_path, "w", encoding="utf-8") as handle:
                    handle.write("\n\n---\n\n".join(remaining_fixes))
            except Exception:
                pass
        else:
            try:
                os.remove(log_file_path)
            except Exception:
                pass

        # Undo the OnlineFix FakeAppId only if we set it and nothing left needs it,
        # and drop the netsock marker we set alongside it (same online-fix lifecycle).
        if removed_had_fakeid and not surviving_has_fakeid:
            try:
                from slssteam_ops import remove_fake_app_id
                remove_fake_app_id(appid)
            except Exception as exc:
                logger.warning(f"LumaDeck: could not remove FakeAppId for {appid}: {exc}")
            try:
                marker = _netsock_marker_path(install_path, appid)
                if os.path.isfile(marker):
                    os.remove(marker)
            except Exception as exc:
                logger.warning(f"LumaDeck: could not remove netsock marker for {appid}: {exc}")

        _set_unfix_state(appid, {
            "status": "done", "success": True,
            "filesRemoved": deleted_count + restored_count,
            "filesRestored": restored_count,
        })
    except Exception as exc:
        _set_unfix_state(appid, {"status": "failed", "error": str(exc)})


async def unfix_game(appid: int, install_path: str = "", fix_date: str = "") -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    resolved_path = install_path
    if not resolved_path:
        result = get_game_install_path_response(appid)
        if not result.get("success") or not result.get("installPath"):
            return {"success": False, "error": "Could not find game install path"}
        resolved_path = result["installPath"]

    if not os.path.exists(resolved_path):
        return {"success": False, "error": "Install path does not exist"}

    _set_unfix_state(appid, {"status": "queued", "progress": "", "error": None})
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _unfix_game_worker, appid, resolved_path, fix_date or "")
    return {"success": True}


def get_unfix_status(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    return {"success": True, "state": _get_unfix_state(appid)}


def get_installed_fixes() -> dict:
    """Scan all Steam library folders for games with fix logs."""
    try:
        steam_path = detect_steam_install_path()
        if not steam_path:
            return {"success": False, "error": "Steam not found"}

        library_vdf_path = os.path.join(steam_path, "config", "libraryfolders.vdf")
        if not os.path.exists(library_vdf_path):
            return {"success": False, "error": "libraryfolders.vdf not found"}

        with open(library_vdf_path, "r", encoding="utf-8") as handle:
            library_data = _parse_vdf_simple(handle.read())

        library_folders = library_data.get("libraryfolders", {})
        all_library_paths = []
        for folder_data in library_folders.values():
            if isinstance(folder_data, dict):
                folder_path = folder_data.get("path", "")
                if folder_path:
                    all_library_paths.append(folder_path.replace("\\\\", "\\"))

        installed_fixes = []
        for lib_path in all_library_paths:
            steamapps = os.path.join(lib_path, "steamapps")
            if not os.path.isdir(steamapps):
                continue
            try:
                for filename in os.listdir(steamapps):
                    if not filename.startswith("appmanifest_") or not filename.endswith(".acf"):
                        continue
                    try:
                        appid = int(filename.replace("appmanifest_", "").replace(".acf", ""))
                        acf_path = os.path.join(steamapps, filename)
                        with open(acf_path, "r", encoding="utf-8") as f:
                            manifest_data = _parse_vdf_simple(f.read())
                        app_state = manifest_data.get("AppState", {})
                        install_dir = app_state.get("installdir", "")
                        game_name = app_state.get("name", f"Unknown ({appid})")
                        if not install_dir:
                            continue
                        full_path = os.path.join(lib_path, "steamapps", "common", install_dir)
                        if not os.path.exists(full_path):
                            continue
                        log_path = os.path.join(full_path, f"luatools-fix-log-{appid}.log")
                        if not os.path.exists(log_path):
                            continue

                        with open(log_path, "r", encoding="utf-8") as lf:
                            log_content = lf.read()

                        if "[FIX]" in log_content:
                            surviving_blocks = []
                            dropped_any = False
                            for block in log_content.split("[FIX]"):
                                if not block.strip():
                                    continue
                                fix_data = {"appid": appid, "gameName": game_name, "installPath": full_path, "date": "", "fixType": "", "downloadUrl": "", "filesCount": 0, "files": [], "online": False}
                                in_files = False
                                files = []
                                block_lines = []
                                for line in block.split("\n"):
                                    stripped = line.strip()
                                    if stripped == "[/FIX]" or stripped == "---":
                                        break
                                    block_lines.append(line)
                                    if stripped.startswith("Date:"):
                                        fix_data["date"] = stripped.replace("Date:", "").strip()
                                    elif stripped.startswith("Fix Type:"):
                                        fix_data["fixType"] = stripped.replace("Fix Type:", "").strip()
                                    elif stripped.startswith("Download URL:"):
                                        fix_data["downloadUrl"] = stripped.replace("Download URL:", "").strip()
                                    elif stripped.startswith("FakeAppId:"):
                                        # OnlineFix (480) route: the OnlineFix.ini declared
                                        # a FakeAppId → definitely an online fix.
                                        fix_data["online"] = True
                                    elif stripped.startswith("Online:"):
                                        # Explicit catalogue-tag marker → catches online
                                        # fixes with no FakeAppId (EOS/EpicFix), which the
                                        # FakeAppId signal alone would miss.
                                        fix_data["online"] = True
                                    elif stripped == "Files:":
                                        in_files = True
                                    elif in_files and stripped:
                                        files.append(stripped)
                                # Self-heal: a fix whose files are ALL gone (Steam
                                # reinstall / manual delete reverted it) is stale —
                                # drop the block instead of listing a fix that isn't
                                # there. A block that lists no files is kept as-is.
                                present = [f for f in files
                                           if os.path.exists(os.path.join(full_path, f.replace("/", os.sep)))]
                                if files and not present:
                                    dropped_any = True
                                    continue
                                surviving_blocks.append("[FIX]\n" + "\n".join(block_lines).strip("\n") + "\n[/FIX]")
                                fix_data["filesCount"] = len(files)
                                fix_data["files"] = files
                                if fix_data["date"]:
                                    installed_fixes.append(fix_data)
                            # Persist the reconciliation if anything was dropped: keep
                            # the survivors, or clear the log + backups outright when
                            # nothing survives.
                            if dropped_any:
                                try:
                                    if surviving_blocks:
                                        with open(log_path, "w", encoding="utf-8") as wf:
                                            wf.write("\n\n---\n\n".join(surviving_blocks) + "\n")
                                    else:
                                        os.remove(log_path)
                                        shutil.rmtree(_fix_backup_root(full_path, appid), ignore_errors=True)
                                except Exception:
                                    pass
                    except Exception:
                        continue
            except Exception:
                continue

        return {"success": True, "fixes": installed_fixes}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def apply_linux_native_fix(install_path: str) -> dict:
    """Fix permissions for Linux native games: chown to deck + chmod +rwx."""
    import stat
    import subprocess
    if os.name != "posix":
        return {"success": False, "error": "This fix is for Linux only."}
    if not install_path or not os.path.exists(install_path):
        return {"success": False, "error": "Game path not found."}
    try:
        # Fix ownership first (Decky runs as root, Steam runs as the real user)
        try:
            from paths import real_user
            subprocess.run(
                ["chown", "-R", f"{real_user()}:", install_path],
                timeout=120, capture_output=True, env=clean_env(),
            )
        except Exception as chown_exc:
            logger.warning(f"LumaDeck: chown failed for {install_path}: {chown_exc}")

        count = 0
        for root, dirs, files in os.walk(install_path):
            # Directories: rwxr-xr-x (755) for traversal
            for d in dirs:
                dp = os.path.join(root, d)
                try:
                    os.chmod(dp, 0o755)
                except Exception:
                    pass
            # Files: rwxr-xr-x (755) — read+execute for all
            for name in files:
                fp = os.path.join(root, name)
                try:
                    os.chmod(fp, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                    count += 1
                except Exception:
                    pass
        return {"success": True, "count": count}
    except Exception as e:
        return {"success": False, "error": str(e)}

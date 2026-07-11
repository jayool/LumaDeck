"""Achievement schema generation for LumaDeck — Steam Web API method.

Generates ``UserGameStatsSchema_<appid>.bin`` files by fetching each game's
achievement schema from the Steam Web API (``ISteamUserStats/GetSchemaForGame``)
and encoding it as binary VDF, then seeding an empty ``UserGameStats`` file.
SLSsteam forces "offline stat usage", so the game reads/writes those local files
and achievements unlock. Steam reads them on the next start.

No external tool, no interactive Steam login, no .NET — just the user's Steam
Web API key (generated once at https://steamcommunity.com/dev/apikey). The key is
revocable and cannot log into the account; it only grants read access to the Web
API. Replaces the old SLScheevo integration (unmaintained + fragile).

Validated on-device: the Web-API-built schema unlocks and persists exactly like
the raw client-protocol schema.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import struct
from typing import Any, Dict, Optional

from paths import get_steam_appcache_stats_dir, find_steam_root, settings_dir

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


GET_SCHEMA_URL = "https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/"

# Per-appid generation state, polled by the frontend.
ACHIEVEMENT_STATE: Dict[int, Dict[str, Any]] = {}
ACHIEVEMENT_SYNC_STATE: Dict[str, Any] = {"status": "idle"}


# ---------------------------------------------------------------------------
# API key store (shared credentials.json in the settings dir)
# ---------------------------------------------------------------------------

def _cred_store_path() -> str:
    return os.path.join(settings_dir(), "credentials.json")


def _read_cred_store() -> dict:
    try:
        p = _cred_store_path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def get_api_key() -> str:
    return str(_read_cred_store().get("steam_webapi_key", "") or "").strip()


def set_steam_api_key(key: str) -> dict:
    """Persist the Steam Web API key. A key is 32 hex chars."""
    key = (key or "").strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{32}", key):
        return {"success": False, "error": "That doesn't look like a Steam Web API key (32 hex characters)."}
    try:
        store = _read_cred_store()
        store["steam_webapi_key"] = key.upper()
        p = _cred_store_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def get_api_key_status() -> dict:
    return {"success": True, "keySet": bool(get_api_key())}


# ---------------------------------------------------------------------------
# Binary VDF encoder — verified byte-identical to ValvePython/vdf.binary_dumps
# ---------------------------------------------------------------------------

_I32 = struct.Struct("<i")


def _bin_gen(obj: dict):
    for key, value in obj.items():
        kb = key.encode("utf-8")
        if isinstance(value, dict):
            yield b"\x00" + kb + b"\x00"
            for chunk in _bin_gen(value):
                yield chunk
        elif isinstance(value, bool):
            yield b"\x02" + kb + b"\x00" + _I32.pack(int(value))
        elif isinstance(value, int):
            yield b"\x02" + kb + b"\x00" + _I32.pack(value)
        else:
            yield b"\x01" + kb + b"\x00" + str(value).encode("utf-8") + b"\x00"
    yield b"\x08"


def _binary_dumps(obj: dict) -> bytes:
    return b"".join(_bin_gen(obj))


# Empty "cache { crc, PendingChanges }" UserGameStats seed (38 bytes). Steam
# grows this as achievements unlock. Same bytes AceSLS's schema-grabber and
# SLScheevo write.
_STATS_SEED = bytes([
    0x00, 0x63, 0x61, 0x63, 0x68, 0x65, 0x00, 0x02, 0x63, 0x72, 0x63, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x02, 0x50, 0x65, 0x6e, 0x64, 0x69, 0x6e, 0x67, 0x43, 0x68, 0x61, 0x6e,
    0x67, 0x65, 0x73, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 0x08,
])


def _account_id() -> Optional[int]:
    """The Steam account id (SteamID64 & 0xffffffff) used in the UserGameStats
    filename. Read from loginusers.vdf (most recent user)."""
    root = find_steam_root()
    if not root:
        return None
    path = os.path.join(root, "config", "loginusers.vdf")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except Exception:
        return None
    best = None
    for m in re.finditer(r'"(7656\d{10,})"\s*\{([^}]*)\}', txt):
        sid, body = m.group(1), m.group(2)
        if best is None:
            best = sid
        if re.search(r'"MostRecent"\s*"1"', body):
            best = sid
            break
    if not best:
        return None
    return int(best) & 0xFFFFFFFF


def _build_schema_blob(appid: int, game: dict) -> Optional[bytes]:
    """Build the binary VDF UserGameStatsSchema from a GetSchemaForGame payload,
    or None if the game has no achievements."""
    achs = (game.get("availableGameStats", {}) or {}).get("achievements", []) or []
    if not achs:
        return None
    stats: Dict[str, Any] = {}
    for i, a in enumerate(achs):
        block, bit = str(i // 32 + 1), i % 32
        stats.setdefault(block, {"type": "4", "id": block, "bits": {}})
        stats[block]["bits"][str(bit)] = {
            "name": a["name"],
            "bit": bit,
            "display": {
                "name": {"english": a.get("displayName", ""), "token": f"NEW_ACHIEVEMENT_{block}_{bit}_NAME"},
                "desc": {"english": a.get("description", ""), "token": f"NEW_ACHIEVEMENT_{block}_{bit}_DESC"},
                "hidden": str(a.get("hidden", 0)),
                "icon": str(a.get("icon", "")).split("/")[-1],
                "icon_gray": str(a.get("icongray", "")).split("/")[-1],
            },
        }
    schema = {
        str(appid): {
            "gamename": game.get("gameName", str(appid)),
            "version": str(game.get("gameVersion", "1")),
            "stats": stats,
        }
    }
    return _binary_dumps(schema)


# ---------------------------------------------------------------------------
# Status checks
# ---------------------------------------------------------------------------

def check_achievements_status(appid: int) -> dict:
    """Status for one appid: needs the API key, then whether a schema exists."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    key_set = bool(get_api_key())
    stats_dir = get_steam_appcache_stats_dir()
    schema_exists = False
    if stats_dir and os.path.isdir(stats_dir):
        schema_exists = os.path.isfile(os.path.join(stats_dir, f"UserGameStatsSchema_{appid}.bin"))

    if not key_set:
        status = "not_configured"      # no API key yet
    elif schema_exists:
        status = "generated"
    else:
        status = "ready"

    gen = ACHIEVEMENT_STATE.get(appid, {})
    if gen.get("status") == "running":
        status = "generating"

    return {
        "success": True,
        "status": status,
        "generated": schema_exists,
        "keySet": key_set,
    }


def check_all_achievements_status(appids: list) -> dict:
    """Which appids already have a schema file (batch)."""
    stats_dir = get_steam_appcache_stats_dir()
    have: set = set()
    if stats_dir and os.path.isdir(stats_dir):
        for fname in os.listdir(stats_dir):
            if fname.startswith("UserGameStatsSchema_") and fname.endswith(".bin"):
                have.add(fname)
    result_map = {}
    for appid in appids:
        try:
            aid = int(appid)
            result_map[aid] = f"UserGameStatsSchema_{aid}.bin" in have
        except (ValueError, TypeError):
            continue
    return {"success": True, "map": result_map}


# ---------------------------------------------------------------------------
# Schema generation
# ---------------------------------------------------------------------------

async def _fetch_and_write(appid: int, key: str, stats_dir: str, acc: Optional[int]) -> tuple[bool, str]:
    """Fetch the schema for one appid and write the .bin files. Returns (ok, msg)."""
    from http_client import ensure_http_client
    client = await ensure_http_client("achievements")
    resp = await client.get(GET_SCHEMA_URL, params={"key": key, "appid": str(appid), "l": "english"}, timeout=20)
    if resp.status_code == 403:
        return False, "The Steam Web API key was rejected (403). Re-check it."
    resp.raise_for_status()
    data = resp.json()
    game = data.get("game", {}) or {}
    blob = _build_schema_blob(appid, game)
    if blob is None:
        return False, "no_achievements"

    os.makedirs(stats_dir, exist_ok=True)
    schema_path = os.path.join(stats_dir, f"UserGameStatsSchema_{appid}.bin")
    with open(schema_path, "wb") as f:
        f.write(blob)

    if acc is not None:
        user_path = os.path.join(stats_dir, f"UserGameStats_{acc}_{appid}.bin")
        if not os.path.exists(user_path):
            with open(user_path, "wb") as f:
                f.write(_STATS_SEED)

    # Decky runs as root (or deck); ensure Steam can read the files.
    try:
        import subprocess
        subprocess.run(["chown", "deck:deck", schema_path], timeout=5, capture_output=True)
    except Exception:
        pass
    return True, "ok"


async def _run_generate(appid: int) -> None:
    key = get_api_key()
    if not key:
        ACHIEVEMENT_STATE[appid] = {"status": "error", "error": "No Steam Web API key set"}
        return
    stats_dir = get_steam_appcache_stats_dir()
    if not stats_dir:
        ACHIEVEMENT_STATE[appid] = {"status": "error", "error": "Steam not found"}
        return
    acc = _account_id()
    ACHIEVEMENT_STATE[appid] = {"status": "running", "progress": "Fetching schema...", "error": None}
    try:
        ok, msg = await _fetch_and_write(appid, key, stats_dir, acc)
        if ok:
            ACHIEVEMENT_STATE[appid] = {"status": "done", "progress": "Achievements generated!", "error": None}
        elif msg == "no_achievements":
            ACHIEVEMENT_STATE[appid] = {"status": "error", "error": "This game has no achievements."}
        else:
            ACHIEVEMENT_STATE[appid] = {"status": "error", "error": msg}
    except Exception as exc:
        logger.error("LumaDeck: achievement generation failed for %s: %s", appid, exc)
        ACHIEVEMENT_STATE[appid] = {"status": "error", "error": str(exc)}


def generate_achievements(appid: int) -> dict:
    """Start generation for one appid. Poll with get_generate_status()."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    if not get_api_key():
        return {"success": False, "error": "Set your Steam Web API key first."}
    if ACHIEVEMENT_STATE.get(appid, {}).get("status") == "running":
        return {"success": False, "error": "Generation already in progress"}
    ACHIEVEMENT_STATE[appid] = {"status": "running", "progress": "Starting...", "error": None}
    asyncio.create_task(_run_generate(appid))
    return {"success": True}


def get_generate_status(appid: int) -> dict:
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    return {"success": True, "state": ACHIEVEMENT_STATE.get(appid, {}).copy()}


def remove_achievement_files(appid: int, remove_progress: bool = False) -> dict:
    """Delete this game's achievement .bin files from Steam's appcache/stats,
    for the uninstall flow. Returns {removed: [...], errors: [...]}.

    The schema (UserGameStatsSchema_<appid>.bin) is always removed — it's just
    the LumaDeck-written definitions and is regenerated on reinstall. The
    per-user UserGameStats_<accountid>_<appid>.bin holds *unlocked* achievement
    progress (local-only for non-owned games — Steam won't restore it), so it's
    only removed when remove_progress is set, matching the "remove Proton
    prefix / my data too" intent of the uninstall toggle."""
    result = {"removed": [], "errors": []}
    try:
        appid = int(appid)
    except Exception:
        result["errors"].append("invalid_appid")
        return result
    stats_dir = get_steam_appcache_stats_dir()
    if not stats_dir or not os.path.isdir(stats_dir):
        return result

    schema = os.path.join(stats_dir, f"UserGameStatsSchema_{appid}.bin")
    if os.path.isfile(schema):
        try:
            os.remove(schema)
            result["removed"].append("achievement_schema")
        except Exception as exc:
            result["errors"].append(f"schema: {exc}")

    if remove_progress:
        # UserGameStats_<accountid>_<appid>.bin. Match by the "_<appid>.bin"
        # suffix (the leading underscore anchors the appid so 48 can't match
        # 1148) and the "UserGameStats_" prefix, which excludes the schema
        # file ("UserGameStatsSchema_...").
        suffix = f"_{appid}.bin"
        for fname in os.listdir(stats_dir):
            if fname.startswith("UserGameStats_") and fname.endswith(suffix):
                try:
                    os.remove(os.path.join(stats_dir, fname))
                    result["removed"].append("achievement_progress")
                except Exception as exc:
                    result["errors"].append(f"progress: {exc}")
    return result


async def auto_generate_on_install(appid: int) -> dict:
    """Best-effort schema generation for the install flow. Only does anything
    when a Steam Web API key is configured; otherwise it's a silent no-op so
    users who never set up achievements are unaffected. Never raises — the
    install must not fail because achievement generation did. The on-disk
    schema file is the source of truth check_achievements_status() reads, so
    writing it is all that's needed for the UI to show "generated"."""
    try:
        appid = int(appid)
    except Exception:
        return {"generated": False, "reason": "invalid_appid"}
    key = get_api_key()
    if not key:
        return {"generated": False, "reason": "no_key"}
    stats_dir = get_steam_appcache_stats_dir()
    if not stats_dir:
        return {"generated": False, "reason": "no_steam"}
    try:
        ok, msg = await _fetch_and_write(appid, key, stats_dir, _account_id())
        return {"generated": True} if ok else {"generated": False, "reason": msg}
    except Exception as exc:
        logger.warning("LumaDeck: auto achievement generation failed for %s: %s", appid, exc)
        return {"generated": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Batch ("Sync All")
# ---------------------------------------------------------------------------

async def _run_sync_all(appids: list) -> None:
    global ACHIEVEMENT_SYNC_STATE
    key = get_api_key()
    stats_dir = get_steam_appcache_stats_dir()
    if not key or not stats_dir:
        ACHIEVEMENT_SYNC_STATE = {"status": "error", "error": "Missing API key or Steam", "done": 0, "total": 0}
        return
    acc = _account_id()

    pending = []
    for appid in appids:
        try:
            aid = int(appid)
        except (ValueError, TypeError):
            continue
        if not os.path.isfile(os.path.join(stats_dir, f"UserGameStatsSchema_{aid}.bin")):
            pending.append(aid)

    total = len(pending)
    errors = []
    ACHIEVEMENT_SYNC_STATE = {"status": "running", "current": pending[0] if pending else None,
                              "done": 0, "total": total, "errors": []}
    for i, aid in enumerate(pending):
        ACHIEVEMENT_SYNC_STATE["current"] = aid
        ACHIEVEMENT_SYNC_STATE["done"] = i
        try:
            ok, msg = await _fetch_and_write(aid, key, stats_dir, acc)
            if not ok and msg not in ("no_achievements",):
                errors.append({"appid": aid, "error": msg})
        except Exception as exc:
            errors.append({"appid": aid, "error": str(exc)})
    ACHIEVEMENT_SYNC_STATE = {"status": "done", "done": total, "total": total, "errors": errors}
    logger.info("LumaDeck: Sync All complete. %d games, %d errors", total, len(errors))


def generate_all_achievements(appids: list) -> dict:
    if not get_api_key():
        return {"success": False, "error": "Set your Steam Web API key first."}
    if ACHIEVEMENT_SYNC_STATE.get("status") == "running":
        return {"success": False, "error": "Sync already in progress"}
    asyncio.create_task(_run_sync_all(appids))
    return {"success": True}


def get_sync_all_status() -> dict:
    return {"success": True, "state": ACHIEVEMENT_SYNC_STATE.copy()}

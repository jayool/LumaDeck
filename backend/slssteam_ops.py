"""SLSsteam config operations: FakeAppId, GameToken, DLCs, PlayStatus, Uninstall."""

from __future__ import annotations

import os
import shutil

from downloads import delete_luatools_for_app
from http_client import ensure_http_client
from steam_utils import get_game_install_path_response
from paths import get_slssteam_config_path, read_lumalinux_hook, real_home

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


def _config_path() -> str:
    return get_slssteam_config_path()


def _hot_reload_enabled() -> bool:
    """The MANUAL kill-switch for the whole no-restart machinery: env
    LUMA_NO_RECONCILE or the marker ~/.config/lumalinux/no_reconcile. DEFAULT ON.

    This is the same switch lumalinux reads for its license reconcile, so the two
    turn on/off as one unit. It does NOT know whether the reconcile actually
    resolved on this Steam build — that's _hot_reload_active(), which adds the
    automatic guard. Callers should use _hot_reload_active(), not this directly."""
    if os.environ.get("LUMA_NO_RECONCILE"):
        return False
    return not os.path.exists(os.path.expanduser("~/.config/lumalinux/no_reconcile"))


def _hot_reload_active() -> bool:
    """Whether an SLSsteam config poke may fire right now. Two gates:

      1. _hot_reload_enabled() — the manual kill-switch isn't set.
      2. lumalinux's license reconcile is not KNOWN-broken on this Steam build.

    (2) is the automatic guard (brick 4). The manual kill-switch couples the poke
    and the reconcile only if the USER sets it; it can't catch a reconcile that
    SILENTLY broke because a Steam update moved the NotifyLicensesUpdated pattern.
    In that state lumalinux writes status.json hook "Reconcile" = "failed" and the
    reconcile no-ops — so poking a just-added game into SLSsteam's live view would
    surface a game whose appinfo has no depot list -> it installs 0 files
    ("installed but broken" trap). We suppress ALL pokes then: a just-added game
    won't appear until a Steam restart (which refreshes appinfo the slow way), and
    live config toggles (FakeAppId / Token / DLC) likewise fall back to applying on
    restart — consistent with a build that already needs restarts.

    Unknown (Reconcile absent: Steam not running this session, or an older .so that
    predates the field) -> allowed; we never suppress on a guess (read_lumalinux_hook
    returns None, and None != "failed")."""
    if not _hot_reload_enabled():
        return False
    return read_lumalinux_hook("Reconcile") != "failed"


def _poke_reload(path: str) -> None:
    """Re-open `path` for a zero-byte append and close it: emits IN_CLOSE_WRITE,
    which SLSsteam's config watcher (filewatcher.cpp) listens for, so it
    hot-reloads AdditionalApps / FakeAppIds without a restart."""
    try:
        with open(path, "a", encoding="utf-8"):
            pass
    except Exception:
        pass


def poke_slssteam_reload() -> dict:
    """Explicitly poke SLSsteam's config.yaml so it hot-reloads AdditionalApps
    and a just-added game appears without a Steam restart. No-op when hot-reload
    is off — either the manual kill-switch, or the reconcile is broken on this
    build (_hot_reload_active); in the latter case surfacing the game would drop
    it into the "0 files" trap, so we hold it back until a restart. Called at the
    end of the Add Game flow so the appearance fires even for games that wrote no
    config of their own (no token / ≤64 DLC)."""
    if not _hot_reload_active():
        return {"success": True, "skipped": True}
    cfg = _config_path()
    if os.path.exists(cfg):
        _poke_reload(cfg)
    return {"success": True}


def _commit_config(src: str, dst: str) -> None:
    """Atomically replace config.yaml, then (unless the kill-switch disabled
    hot-reload, _hot_reload_enabled) poke SLSsteam's live reload so the change
    applies without a Steam restart.

    `os.replace` commits via a rename (`IN_MOVED_TO`), which SLSsteam's watcher
    (`IN_CLOSE_WRITE`) does not listen for — so on its own the edit would take
    effect only on the next Steam start. The poke re-opens/closes the file to
    emit IN_CLOSE_WRITE, applying live config toggles (FakeAppId / Token / DLC).
    Gated on _hot_reload_active(): the manual kill-switch OR a reconcile that
    broke on this build suppresses the poke, so a reconcile break never leaves
    the poke on alone (the 'installed / files missing' trap)."""
    os.replace(src, dst)
    if _hot_reload_active():
        _poke_reload(dst)


# ==========================================
#  FAKE APP ID MANAGEMENT
# ==========================================

def add_fake_app_id(appid: int, fake_id: int = 480) -> dict:
    try:
        config_path = _config_path()
        # Do NOT create the config here. A FakeAppId is meaningless until SLSsteam
        # has written its own config, and seeding a 1-line "FakeAppIds:" would
        # preempt SLSsteam's full-default write (its createFile is create-if-absent)
        # and strand a truncated config forever. Match the other config ops
        # (add_to_additional_apps / add_dlc): require the config to exist. A missing
        # config is completed by the boot-time reconcile, not seeded here.
        if not os.path.exists(config_path):
            return {"success": False, "error": "SLSsteam config not found — install dependencies first"}

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        entry_line = f"  {appid}: {fake_id}\n"
        target = str(appid)
        # Only treat the appid as "already configured" if it appears as a key
        # INSIDE the FakeAppIds: block. Scanning the whole file would false-
        # positive on the same appid living under AppTokens:/DlcData: etc.
        in_block = False
        for line in lines:
            stripped = line.strip()
            if not in_block:
                if stripped.lower().startswith("fakeappids:"):
                    in_block = True
                continue
            indent = len(line) - len(line.lstrip())
            if stripped and not stripped.startswith("#") and indent == 0:
                in_block = False  # next top-level key ends the block
                continue
            if stripped.startswith(f"{target}:") or stripped.startswith(f"'{target}':") or stripped.startswith(f'"{target}":'):
                return {"success": True, "message": "FakeAppId already configured"}

        new_lines = []
        inserted = False
        has_tag = False
        for line in lines:
            new_lines.append(line)
            if line.strip().lower().startswith("fakeappids:"):
                has_tag = True
                new_lines.append(entry_line)
                inserted = True

        if not has_tag:
            new_lines.append("\nFakeAppIds:\n")
            new_lines.append(entry_line)

        tmp = config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        _commit_config(tmp, config_path)
        return {"success": True, "message": f"FakeAppId ({appid} -> {fake_id}) added!"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def remove_fake_app_id(appid: int) -> dict:
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return {"success": True, "message": "Config not found"}

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        modified = False
        target = str(appid)
        # Scope the deletion to the FakeAppIds: block only. A whole-file scan
        # would also strip the same appid's entries from AppTokens:/DlcData:
        # (and orphan DlcData child lines, corrupting the YAML).
        in_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("fakeappids:"):
                in_block = True
                new_lines.append(line)
                continue
            if in_block:
                indent = len(line) - len(line.lstrip())
                if stripped and not stripped.startswith("#") and indent == 0:
                    in_block = False  # next top-level key ends the block
                elif (stripped.startswith(f"{target}:") or stripped.startswith(f"'{target}':") or stripped.startswith(f'"{target}":')):
                    modified = True
                    continue
            new_lines.append(line)

        if modified:
            tmp = config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            _commit_config(tmp, config_path)

        return {"success": True, "message": "FakeAppId removed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_fake_app_id_status(appid: int) -> dict:
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return {"success": True, "exists": False}
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        target = str(appid)
        in_fakeappids = False
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("fakeappids:"):
                in_fakeappids = True
                continue
            if in_fakeappids:
                indent = len(line) - len(line.lstrip())
                if indent <= 0 and stripped and not stripped.startswith("#"):
                    in_fakeappids = False
                elif stripped.startswith(f"{target}:"):
                    return {"success": True, "exists": True}
        return {"success": True, "exists": False}
    except Exception:
        return {"success": True, "exists": False}


def list_fake_app_ids() -> dict:
    """Read the current FakeAppIds map from config.yaml as {realId: fakeId}.
    Comment-safe: only parses the indented lines under the `FakeAppIds:` key."""
    try:
        config_path = _config_path()
        entries: dict = {}
        if not os.path.exists(config_path):
            return {"success": True, "entries": entries}
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        in_block = False
        for line in lines:
            stripped = line.strip()
            if not in_block:
                if stripped.lower().startswith("fakeappids:"):
                    in_block = True
                continue
            indent = len(line) - len(line.lstrip())
            if stripped and not stripped.startswith("#") and indent == 0:
                break  # next top-level key ends the block
            if not stripped or stripped.startswith("#"):
                continue
            key, _, val = stripped.partition(":")
            key = key.strip().strip("'\"")
            val = val.strip().strip("'\"")
            if key:
                entries[key] = val
        return {"success": True, "entries": entries}
    except Exception as e:
        return {"success": False, "error": str(e)}


def is_in_denuvo_games(appid: int) -> bool:
    """True if `appid` is listed under SLSsteam's `DenuvoGames:` block — an
    external Denuvo activation done with another account's identity:

        DenuvoGames:
          76561198000000000:
            - 1234
            - 5678

    Such a game must not get a FakeAppId: with the pipe reporting 480 SLSsteam
    can no longer find the activator's identity for the real appid and the
    activation fails (AceSLS, 293eb93, 2026-07-26). Online cannot work on a
    ticket-activated Denuvo game anyway (publisher servers want a real licence),
    so the Online toggle refuses instead of breaking it. Comment-safe, block
    and flow list styles; anything unparseable reads as "not listed"."""
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return False
        target = str(int(appid))
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        in_block = False
        for line in lines:
            stripped = line.strip()
            if not in_block:
                if stripped.lower().startswith("denuvogames:"):
                    in_block = True
                continue
            indent = len(line) - len(line.lstrip())
            if stripped and not stripped.startswith("#") and indent == 0:
                break                                   # next top-level key
            if not stripped or stripped.startswith("#"):
                continue
            # "- 1234" list items, or a flow list "steamid: [1234, 5678]"
            body = stripped[1:].strip() if stripped.startswith("-") else stripped.partition(":")[2]
            for tok in body.replace("[", " ").replace("]", " ").replace(",", " ").split():
                if tok.strip("'\"") == target:
                    return True
        return False
    except Exception:
        return False


# ==========================================
#  ADDITIONAL APPS MANAGEMENT
# ==========================================

def add_to_additional_apps(appid: int) -> dict:
    """Add appid to AdditionalApps list in SLSsteam config.
    This is required for unowned games to appear in the Steam library."""
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return {"success": False, "error": "SLSsteam config not found"}

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        entry = f"  - {appid}\n"
        # Check if already present
        for line in lines:
            stripped = line.strip()
            if stripped == f"- {appid}":
                return {"success": True, "message": "Already in AdditionalApps"}

        new_lines = []
        inserted = False
        for line in lines:
            new_lines.append(line)
            if line.strip().lower().startswith("additionalapps:"):
                new_lines.append(entry)
                inserted = True

        if not inserted:
            new_lines.append("\nAdditionalApps:\n")
            new_lines.append(entry)

        tmp = config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        _commit_config(tmp, config_path)
        return {"success": True, "message": f"AppID {appid} added to AdditionalApps"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_additional_apps() -> dict:
    """Read the current AdditionalApps list from config.yaml as [appid, ...].
    Comment-safe: only parses the indented `- N` lines under `AdditionalApps:`."""
    try:
        config_path = _config_path()
        appids: list = []
        if not os.path.exists(config_path):
            return {"success": True, "appids": appids}
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        in_block = False
        for line in lines:
            stripped = line.strip()
            if not in_block:
                if stripped.lower().startswith("additionalapps:"):
                    in_block = True
                continue
            indent = len(line) - len(line.lstrip())
            if stripped and not stripped.startswith("#") and indent == 0:
                break
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("-"):
                appids.append(stripped[1:].strip().strip("'\""))
        return {"success": True, "appids": appids}
    except Exception as e:
        return {"success": False, "error": str(e)}


def remove_from_additional_apps(appid: int) -> dict:
    """Public wrapper: drop `- appid` from the AdditionalApps list."""
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return {"success": True, "message": "Config not found"}
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        target = f"- {appid}"
        new_lines = [ln for ln in lines if ln.strip() != target]
        if len(new_lines) != len(lines):
            tmp = config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            _commit_config(tmp, config_path)
        return {"success": True, "message": f"AppID {appid} removed from AdditionalApps"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==========================================
#  GAME TOKEN MANAGEMENT
# ==========================================

def add_game_token(appid: int) -> dict:
    try:
        config_path = _config_path()

        # The app access token lives in the installed .lua as an
        # `addtoken(appid, "hex")` line — distinct from the `addappid(depot,
        # type, "64hex")` depot *decryption* keys, which are a different value
        # for a different job. SLSsteam needs this token to de-strip the app's
        # PICS appinfo for the subset of games Valve gates behind one; without
        # it those games throw "invalid configuration". We read it straight from
        # the .lua we already installed into stplug-in — there is no separate
        # token file. Games with no `addtoken` line aren't token-gated, so we
        # skip cleanly (a no-op, not an error).
        from steam_utils import detect_steam_install_path
        steam_path = detect_steam_install_path() or os.path.join(real_home(), ".local/share/Steam")
        lua_path = os.path.join(steam_path, "config", "stplug-in", f"{appid}.lua")
        if not os.path.exists(lua_path):
            lua_path += ".disabled"  # tolerate a disabled game
        if not os.path.exists(lua_path):
            return {"success": True, "skipped": True, "message": "No lua installed"}

        with open(lua_path, "r", encoding="utf-8") as f:
            lua_text = f.read()
        import re as _re
        m = _re.search(
            rf'addtoken\s*\(\s*{appid}\s*,\s*["\']([^"\']+)["\']\s*\)', lua_text)
        if not m:
            return {"success": True, "skipped": True, "message": "No token in lua"}
        token = m.group(1)

        # Do NOT create the config here (see add_fake_app_id): a 1-line "AppTokens:"
        # seed would preempt SLSsteam's full-default write and strand a truncated
        # config. Soft-skip when the config isn't there yet — the caller only logs
        # this, and the token is re-applied once SLSsteam has written its config.
        if not os.path.exists(config_path):
            return {"success": True, "skipped": True, "message": "SLSsteam config not found"}

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        entry = f"{appid}: {token}"
        for line in lines:
            if str(appid) in line and token in line:
                return {"success": True, "message": "Token already in config"}

        new_lines = []
        inserted = False
        has_tag = False
        for line in lines:
            new_lines.append(line)
            if line.strip().startswith("AppTokens:"):
                has_tag = True
                new_lines.append(f"  {entry}\n")
                inserted = True

        if not has_tag:
            new_lines.append("\nAppTokens:\n")
            new_lines.append(f"  {entry}\n")

        tmp = config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        _commit_config(tmp, config_path)
        return {"success": True, "message": "Token added!"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def remove_game_token(appid: int) -> dict:
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return {"success": True, "message": "Config not found"}

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        modified = False
        target = str(appid)
        in_tokens = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("AppTokens:"):
                in_tokens = True
                new_lines.append(line)
                continue
            if in_tokens:
                indent = len(line) - len(line.lstrip())
                if indent <= 0 and stripped and not stripped.startswith("#"):
                    in_tokens = False
                elif (stripped.startswith(f"{target}:") or
                      stripped.startswith(f"'{target}':") or
                      stripped.startswith(f'"{target}":')):
                    modified = True
                    continue
            new_lines.append(line)

        if modified:
            tmp = config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            _commit_config(tmp, config_path)

        return {"success": True, "message": "Token removed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==========================================
#  DLC MANAGEMENT
# ==========================================

async def _fetch_dlc_list(appid: int) -> list:
    try:
        client = await ensure_http_client("DLC Fetcher")
        resp = await client.get(f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic,dlc", timeout=10)
        data = resp.json()
        if not data or str(appid) not in data or not data[str(appid)]["success"]:
            return []
        dlc_ids = data[str(appid)]["data"].get("dlc", [])
        if not dlc_ids:
            return []

        dlc_info = []
        chunk_size = 10
        for i in range(0, len(dlc_ids), chunk_size):
            chunk = dlc_ids[i:i + chunk_size]
            ids_str = ",".join(map(str, chunk))
            try:
                resp = await client.get(f"https://store.steampowered.com/api/appdetails?appids={ids_str}&filters=basic", timeout=10)
                names_data = resp.json()
                for d_id in chunk:
                    name = f"DLC {d_id}"
                    d_str = str(d_id)
                    if names_data and d_str in names_data and names_data[d_str]["success"]:
                        name = names_data[d_str]["data"]["name"]
                    name = name.replace('"', "").replace("'", "")
                    dlc_info.append((d_id, name))
            except Exception:
                for d_id in chunk:
                    dlc_info.append((d_id, f"DLC {d_id}"))
        return dlc_info
    except Exception:
        return []


async def add_game_dlcs(appid: int) -> dict:
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return {"success": False, "error": "Config not found. Install SLSsteam first."}

        dlcs = await _fetch_dlc_list(appid)
        if not dlcs:
            return {"success": False, "error": "No DLCs found for this game"}

        # Steam/SLSsteam handles up to 64 DLCs natively; only write to config if >64
        if len(dlcs) <= 64:
            return {"success": True, "message": f"{len(dlcs)} DLCs found — Steam handles ≤64 natively, no config needed", "count": len(dlcs), "skipped": True}

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Check if already configured
        in_dlc = False
        for line in lines:
            if line.strip().startswith("DlcData:"):
                in_dlc = True
            if in_dlc and line.strip().startswith(f"{appid}:"):
                return {"success": True, "message": "DLCs already configured"}

        new_block = [f"  {appid}:\n"]
        for d_id, d_name in dlcs:
            new_block.append(f'    {d_id}: "{d_name}"\n')

        new_lines = []
        inserted = False
        has_tag = False
        for line in lines:
            new_lines.append(line)
            if line.strip().startswith("DlcData:"):
                has_tag = True
                new_lines.extend(new_block)
                inserted = True

        if not has_tag:
            new_lines.append("\nDlcData:\n")
            new_lines.extend(new_block)

        tmp = config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        _commit_config(tmp, config_path)

        return {"success": True, "message": f"{len(dlcs)} DLCs added!", "count": len(dlcs)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def remove_game_dlcs(appid: int) -> dict:
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return {"success": True}

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        in_target = False
        target = f"{appid}:"
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(target):
                in_target = True
                continue
            if in_target:
                indent = len(line) - len(line.lstrip())
                if indent <= 2 and stripped:
                    in_target = False
                    new_lines.append(line)
                else:
                    continue
            else:
                new_lines.append(line)

        tmp = config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        _commit_config(tmp, config_path)
        return {"success": True, "message": "DLCs removed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_game_dlcs_status(appid: int) -> dict:
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return {"success": True, "exists": False, "count": 0}
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Find appid block under DlcData and count entries
        in_dlcdata = False
        in_app_block = False
        count = 0
        target = f"{appid}:"
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("DlcData:"):
                in_dlcdata = True
                continue
            if in_dlcdata:
                indent = len(line) - len(line.lstrip())
                if indent <= 0 and stripped and not stripped.startswith("#"):
                    in_dlcdata = False
                    continue
                if indent == 2 and stripped.startswith(target):
                    in_app_block = True
                    continue
                elif indent == 2 and stripped and in_app_block:
                    in_app_block = False
                elif in_app_block and indent >= 4 and stripped:
                    count += 1
        exists = count > 0
        return {"success": True, "exists": exists, "count": count}
    except Exception:
        return {"success": True, "exists": False, "count": 0}


# ==========================================
#  FULL UNINSTALL
# ==========================================

def _remove_from_additional_apps(appid: int) -> None:
    try:
        config_path = _config_path()
        if not os.path.exists(config_path):
            return
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = []
        modified = False
        target = f"- {appid}"
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(target):
                remainder = stripped[len(target):]
                if not remainder or remainder[0] in " \t#":
                    modified = True
                    continue
            new_lines.append(line)
        if modified:
            tmp = config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            _commit_config(tmp, config_path)
    except Exception:
        pass


def _find_game_dir_fallback(appid: int) -> str:
    """Multi-strategy fallback to find a game's install directory when the ACF is missing.

    Strategies (in order):
    1. Steam API installdir — official directory name from Steam store
    2. Lua file installdir hint — parsed from the download's lua script
    3. Name match — fuzzy match game name against steamapps/common entries
    4. All library folders — repeat strategies across all Steam library paths
    """
    from steam_utils import detect_steam_install_path

    steam_path = detect_steam_install_path()
    if not steam_path:
        return ""

    # Collect all library paths (main + additional)
    library_paths = [steam_path]
    try:
        library_vdf = os.path.join(steam_path, "config", "libraryfolders.vdf")
        if os.path.exists(library_vdf):
            from steam_utils import _parse_vdf_simple
            with open(library_vdf, "r", encoding="utf-8") as f:
                data = _parse_vdf_simple(f.read())
            for folder in data.get("libraryfolders", {}).values():
                if isinstance(folder, dict):
                    p = folder.get("path", "").replace("\\\\", "\\")
                    if p and p not in library_paths:
                        library_paths.append(p)
    except Exception:
        pass

    # Strategy 1: Steam API installdir
    try:
        from downloads import _fetch_installdir_from_api
        import asyncio
        loop = asyncio.get_event_loop()
        api_dir = loop.run_until_complete(_fetch_installdir_from_api(appid))
        if api_dir:
            for lib in library_paths:
                candidate = os.path.join(lib, "steamapps", "common", api_dir)
                if os.path.isdir(candidate):
                    return candidate
    except Exception:
        pass

    # Strategy 2: Lua file — extract game name from download log
    game_name = ""
    try:
        from downloads import _get_loaded_app_name, _get_app_name_from_applist
        game_name = _get_loaded_app_name(appid) or _get_app_name_from_applist(appid) or ""
    except Exception:
        pass

    # Strategy 3: Name match across all library folders
    if game_name:
        game_lower = game_name.lower()
        for lib in library_paths:
            common_path = os.path.join(lib, "steamapps", "common")
            if not os.path.isdir(common_path):
                continue
            try:
                # Exact match first
                for d in os.listdir(common_path):
                    if d.lower() == game_lower:
                        candidate = os.path.join(common_path, d)
                        if os.path.isdir(candidate):
                            return candidate
                # Prefix match as fallback
                for d in os.listdir(common_path):
                    dl = d.lower()
                    if dl.startswith(game_lower[:20]) or game_lower.startswith(dl[:20]):
                        candidate = os.path.join(common_path, d)
                        if os.path.isdir(candidate):
                            return candidate
            except Exception:
                continue

    # Strategy 4: Scan for appid in directory names (e.g. "app_2417610")
    for lib in library_paths:
        common_path = os.path.join(lib, "steamapps", "common")
        if not os.path.isdir(common_path):
            continue
        try:
            for d in os.listdir(common_path):
                if str(appid) in d:
                    candidate = os.path.join(common_path, d)
                    if os.path.isdir(candidate):
                        return candidate
        except Exception:
            continue

    return ""


def _retire_key_lines(lines: list) -> int:
    """Append keyed depot lines to lumalinux's retired_keys.txt (same line
    format as keys.txt), replacing an older entry for the same depot. Returns
    how many were written. See remove_from_lumalinux_keys(retire=True)."""
    from paths import get_lumalinux_retired_keys_path
    keyed = {}
    for raw in lines:
        fields = raw.strip().split(";")
        if len(fields) >= 5 and len(fields[4]) == 64:
            keyed[fields[0]] = raw.strip() + "\n"
    if not keyed:
        return 0
    path = get_lumalinux_retired_keys_path()
    kept = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                st = raw.strip()
                if st and not st.startswith("#") and st.split(";")[0] in keyed:
                    continue
                kept.append(raw if raw.endswith("\n") else raw + "\n")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(kept)
        f.writelines(keyed.values())
    os.replace(tmp, path)
    return len(keyed)


def prune_retired_keys() -> int:
    """Drop retired entries for depots that are back in keys.txt with a key
    (the DLC were added again): keys.txt wins in lumalinux anyway, this only
    keeps the file honest. Returns how many were dropped."""
    from paths import get_lumalinux_keys_path, get_lumalinux_retired_keys_path
    path = get_lumalinux_retired_keys_path()
    keys_path = get_lumalinux_keys_path()
    if not os.path.isfile(path) or not os.path.isfile(keys_path):
        return 0
    live = set()
    with open(keys_path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            fields = raw.strip().split(";")
            if len(fields) >= 5 and len(fields[4]) == 64:
                live.add(fields[0])
    kept, dropped = [], 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            st = raw.strip()
            if st and not st.startswith("#") and st.split(";")[0] in live:
                dropped += 1
                continue
            kept.append(raw)
    if dropped:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(tmp, path)
    return dropped


def remove_from_lumalinux_keys(appid: int, extra_depot_ids=None, retire: bool = False) -> dict:
    """Remove an app's lines from lumalinux's keys.txt.

    Removes any non-comment line that is:
      - the app's own dummy line:        '<appid>;<hex>'
      - a depot line parented to appid:  '<depot>;<appid>;<gid>;<size>;<key>'
      - a depot line for any id in extra_depot_ids (legacy/no-key shapes that
        carry no parent field, recovered from the .lua before it's deleted)

    retire — move the keyed depot lines to retired_keys.txt instead of
    dropping them: lumalinux keeps serving those keys to Steam but no longer
    injects them as licences. For an owned game's DLC: Steam deletes their
    files only with the key (depotcache manifests carry encrypted file names)
    and asks for it after the uninstall unticked them — measured 2026-10-06
    14:51, "Missing decryption key", nothing deleted, when the key went with
    the licence. Exactly what Steam does with its own key cache.

    Comments (#...) and blank lines are preserved verbatim. Best-effort: any
    read/write error is reported but never raises. Returns the depot ids that
    were removed and a count of removed lines.
    """
    from paths import get_lumalinux_keys_path

    keys_path = get_lumalinux_keys_path()
    if not os.path.isfile(keys_path):
        return {"success": True, "removed": 0, "depot_ids": [], "retired": 0}

    appid_str = str(appid)
    extra = {str(d) for d in (extra_depot_ids or [])}
    removed_depot_ids = set()
    kept_lines = []
    removed_lines = []
    removed = 0
    try:
        with open(keys_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for raw in lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                kept_lines.append(raw)
                continue
            fields = stripped.split(";")
            depot = fields[0]
            is_app_dummy = depot == appid_str
            is_parented = len(fields) >= 2 and fields[1] == appid_str
            is_extra = depot in extra
            if is_app_dummy or is_parented or is_extra:
                removed += 1
                # The app's own dummy line is not a depot.
                if not is_app_dummy:
                    removed_depot_ids.add(depot)
                    removed_lines.append(raw)
                continue
            kept_lines.append(raw)

        retired = 0
        if removed:
            # Retire BEFORE rewriting keys.txt: lumalinux reloads both files
            # on the keys.txt write, so the key is never absent in between.
            if retire:
                retired = _retire_key_lines(removed_lines)
            tmp = keys_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(kept_lines)
            os.replace(tmp, keys_path)
        return {"success": True, "removed": removed, "depot_ids": sorted(removed_depot_ids), "retired": retired}
    except Exception as e:
        logger.warning(f"LumaDeck: remove_from_lumalinux_keys failed: {e}")
        return {"success": False, "error": str(e), "depot_ids": sorted(removed_depot_ids)}


def remove_depot_decryption_keys(depot_ids) -> dict:
    """Remove DecryptionKey blocks for the given depot ids from config.vdf.

    Mirrors the block shape written by write_depot_decryption_keys:
        "<depot>"
        {
            "DecryptionKey"  "<64 hex>"
        }
    The regex only matches a brace block with no nested braces, so it can't
    eat a larger surrounding section. Best-effort; the rest of the file is
    preserved. Returns the depot ids actually removed.
    """
    import re
    from steam_utils import detect_steam_install_path

    depot_ids = [str(d) for d in (depot_ids or [])]
    if not depot_ids:
        return {"success": True, "removed": []}

    steam_path = detect_steam_install_path()
    if not steam_path:
        return {"success": False, "error": "Steam path not found"}
    config_vdf = os.path.join(steam_path, "config", "config.vdf")
    if not os.path.exists(config_vdf):
        return {"success": True, "removed": []}

    try:
        with open(config_vdf, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        removed = []
        for depot_str in depot_ids:
            # Consume the leading newline too so we don't leave a blank line.
            block_re = re.compile(
                rf'\n[ \t]*"{re.escape(depot_str)}"\s*\{{[^{{}}]*\}}',
                re.DOTALL,
            )
            new_content, n = block_re.subn("", content)
            if n:
                content = new_content
                removed.append(depot_str)
                logger.info(f"LumaDeck: Removed DecryptionKey block for depot {depot_str}")
        if removed:
            tmp = config_vdf + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp, config_vdf)
        return {"success": True, "removed": removed}
    except Exception as e:
        logger.warning(f"LumaDeck: remove_depot_decryption_keys failed: {e}")
        return {"success": False, "error": str(e)}


def _lua_dlc_appids(appid: int) -> list:
    """The DLC AppIDs LumaDeck registered for an owned game: the keyless
    addappid(n) lines of its stplug-in .lua (steamidra turned them into
    AdditionalApps). Empty without a .lua."""
    try:
        from steam_utils import detect_steam_install_path
        steam_path = detect_steam_install_path()
        if not steam_path:
            return []
        lua_path = os.path.join(steam_path, "config", "stplug-in", f"{int(appid)}.lua")
        if not os.path.exists(lua_path):
            lua_path += ".disabled"
        if not os.path.exists(lua_path):
            return []
        import re as _re
        with open(lua_path, "r", encoding="utf-8", errors="replace") as fh:
            txt = fh.read()
        return sorted({int(x) for x in _re.findall(r"^\s*addappid\s*\(\s*(\d+)\s*\)", txt, _re.MULTILINE)
                       if int(x) != int(appid)})
    except Exception:
        return []


def owned_dlc_to_disable(appid: int) -> dict:
    """Step one of uninstalling an owned game, for the frontend.

    Steam keeps an owned game's DLC installed whatever happens to the licence
    behind them (measured 2026-10-06: not on licence loss, not on restart).
    The one thing that makes it drop them is the DLC's own tick box in the
    game's properties — SteamClient.Apps.SetDLCEnabled(app, dlc, false) —
    after which Steam deletes their files with its own manifests and
    rewrites the .acf. Only the frontend can press that; the backend tells
    it which DLC, and uninstall_game_full then refuses to touch anything
    unless the frontend says it did (see steam_dlc_disabled).

    A DLC the account meanwhile BOUGHT is left out: unticking it would
    uninstall something the user paid for. Its LumaDeck lines are stale and
    the uninstall simply drops them.
    """
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    import pins as _pins
    owned = _pins.is_owned(appid)
    if not owned:
        return {"success": True, "owned": False, "installed": False, "running": False, "dlc": []}
    try:
        from steam_licenses import is_licensed
        dlc = [d for d in _lua_dlc_appids(appid) if not is_licensed(d)]
    except Exception:
        dlc = _lua_dlc_appids(appid)
    installed = _pins.find_acf(appid) is not None
    try:
        from steam_utils import is_app_running
        running = is_app_running(appid)
    except Exception:
        running = False
    return {"success": True, "owned": True, "installed": installed, "running": running, "dlc": dlc}


def uninstall_game_full(appid: int, remove_compatdata: bool = False, steam_dlc_disabled: bool = False) -> dict:
    """Full uninstall: game files, appmanifest, depotcache manifests, lua, all
    SLSsteam config entries and lumalinux keys.txt lines.

    An OWNED game (pins.json) is Steam's: its files, .acf and prefix stay,
    and so do depotcache and config.vdf — both are Steam's own caches. Steam
    needs the depotcache manifests to delete the DLC files once the frontend
    unticks the DLC (owned_dlc_to_disable), and it rewrites config.vdf from
    memory on exit anyway. What goes is LumaDeck's record: AdditionalApps
    entries, keys.txt lines (their keys move to retired_keys.txt: Steam
    still needs them to delete the DLC files, see remove_from_lumalinux_keys),
    pins, and the .lua — last, so a retry after a failure half-way still
    knows which DLC were ours.

    steam_dlc_disabled — the frontend confirms it unticked the DLC in Steam.
    Without it an installed owned game with DLC is refused, because the
    alternative is Steam keeping the DLC mounted while their keys vanish.
    """
    removed = []
    errors = []
    # Depot ids recovered from the .lua before it's deleted (step 3). Used to
    # clean legacy/no-key keys.txt lines and config.vdf keys that carry no
    # parent appid of their own.
    lua_depot_ids: list = []
    # DLC AppIDs recovered from the .lua (keyless addappid lines): for a game
    # the account OWNS they are what steamidra put into AdditionalApps.
    lua_dlc_appids: list = []
    try:
        import pins as _pins
        owned = _pins.is_owned(appid)
    except Exception:
        owned = False

    if owned:
        prep = owned_dlc_to_disable(appid)
        if prep.get("running"):
            return {"success": False, "error": "Close the game first: its DLC are removed through Steam's own DLC list, which Steam only applies while the game is not running."}
        if prep.get("installed") and prep.get("dlc") and not steam_dlc_disabled:
            return {"success": False, "error": "Steam has not removed the DLC yet; nothing was changed. Try again from the game page."}

    try:
        # 1. Find and remove game files — NOT for a game the account owns:
        # LumaDeck only added its DLC (RESEARCH §21 run E); the game, its .acf
        # and its prefix are Steam's, and Steam drops the DLC depots itself on
        # its next plan once their licences are gone.
        path_info = get_game_install_path_response(appid)
        install_path = path_info.get("installPath") if isinstance(path_info, dict) else None
        library_path = path_info.get("libraryPath") if isinstance(path_info, dict) else None

        # Fallback chain: multiple strategies to find game dir when ACF is gone or dir is missing
        if not install_path or not os.path.exists(install_path):
            install_path = _find_game_dir_fallback(appid)
            if install_path:
                from steam_utils import detect_steam_install_path
                library_path = library_path or detect_steam_install_path()
                logger.info(f"LumaDeck: Found game dir via fallback: {install_path}")

        if owned:
            logger.info(f"LumaDeck: {appid} is owned by the account — leaving its files, .acf and prefix alone")
            # Older steamidra builds left an ACCELA marker inside the game
            # folder (an owned game's folder is the user's): drop it.
            if install_path:
                marker = os.path.join(install_path, ".DepotDownloader")
                if os.path.isdir(marker):
                    shutil.rmtree(marker, ignore_errors=True)
            install_path = None
            remove_compatdata = False
        elif install_path and os.path.exists(install_path):
            shutil.rmtree(install_path, ignore_errors=True)
            if not os.path.exists(install_path):
                removed.append("game_files")
                logger.info(f"LumaDeck: Removed game directory: {install_path}")
            else:
                errors.append("Failed to fully remove game directory")
        else:
            logger.info(f"LumaDeck: No game directory found for {appid}, skipping file removal")

        # 1b. Remove appmanifest — always, independent of whether game dir was found.
        # Search all known library paths so orphan ACFs are always cleaned up.
        try:
            from steam_utils import get_steam_libraries, detect_steam_install_path
            libs = [] if owned else (get_steam_libraries() or [{"path": detect_steam_install_path()}])
            for lib in libs:
                lib_path = lib.get("path", "") if isinstance(lib, dict) else str(lib)
                acf_file = os.path.join(lib_path, "steamapps", f"appmanifest_{appid}.acf")
                if os.path.exists(acf_file):
                    try:
                        os.chmod(acf_file, 0o644)
                        os.remove(acf_file)
                        if "appmanifest" not in removed:
                            removed.append("appmanifest")
                        logger.info(f"LumaDeck: Removed ACF: {acf_file}")
                    except Exception as e:
                        errors.append(f"Failed to remove appmanifest: {e}")
        except Exception as e:
            logger.warning(f"LumaDeck: ACF removal error: {e}")

        # 1b. Remove compatdata/proton prefix if requested
        if remove_compatdata:
            try:
                from steam_utils import detect_steam_install_path
                steam_path = detect_steam_install_path()
                if steam_path:
                    compatdata_path = os.path.join(steam_path, "steamapps", "compatdata", str(appid))
                    if os.path.exists(compatdata_path):
                        shutil.rmtree(compatdata_path, ignore_errors=True)
                        if not os.path.exists(compatdata_path):
                            removed.append("compatdata")
                            logger.info(f"LumaDeck: Removed compatdata: {compatdata_path}")
                        else:
                            errors.append("Failed to fully remove compatdata")
                    # Also check other library paths
                    if library_path and library_path != steam_path:
                        alt_compatdata = os.path.join(library_path, "steamapps", "compatdata", str(appid))
                        if os.path.exists(alt_compatdata):
                            shutil.rmtree(alt_compatdata, ignore_errors=True)
                            if not os.path.exists(alt_compatdata):
                                if "compatdata" not in removed:
                                    removed.append("compatdata")
            except Exception as e:
                logger.warning(f"LumaDeck: Compatdata cleanup error: {e}")

        # 2. Remove depotcache manifests for this game's depots. NOT for an
        # owned game: Steam deletes the unticked DLC's files by reading those
        # very manifests (with them gone it deleted nothing — 2026-10-06 10:23,
        # 1 GB left orphaned), and it keeps old manifests around itself.
        try:
            from steam_utils import detect_steam_install_path
            from downloads import _parse_lua_depots
            steam_path = detect_steam_install_path()
            if steam_path:
                lua_path = os.path.join(steam_path, "config", "stplug-in", f"{appid}.lua")
                lua_path_disabled = lua_path + ".disabled"
                actual_lua = lua_path if os.path.exists(lua_path) else (lua_path_disabled if os.path.exists(lua_path_disabled) else None)
                if actual_lua:
                    depots = _parse_lua_depots(actual_lua)
                    # Capture depot ids now — the .lua is deleted in step 3.
                    lua_depot_ids = [d["depot"] for d in depots if "depot" in d]
                    try:
                        import re as _re
                        with open(actual_lua, "r", encoding="utf-8", errors="replace") as _fh:
                            _lua_txt = _fh.read()
                        lua_dlc_appids = [int(x) for x in _re.findall(r"^\s*addappid\s*\(\s*(\d+)\s*\)", _lua_txt, _re.MULTILINE)
                                          if int(x) != int(appid)]
                    except Exception:
                        lua_dlc_appids = []
                    depotcache_dir = os.path.join(steam_path, "depotcache")
                    for depot_info in ([] if owned else depots):
                        manifest_file = os.path.join(depotcache_dir, f"{depot_info['depot']}_{depot_info['manifest']}.manifest")
                        if os.path.exists(manifest_file):
                            try:
                                os.remove(manifest_file)
                                logger.info(f"LumaDeck: Removed manifest: {manifest_file}")
                            except Exception:
                                pass
                    if depots and not owned:
                        removed.append("depot_manifests")
        except Exception as e:
            logger.warning(f"LumaDeck: Depotcache cleanup error: {e}")

        # 3. (the .lua goes last — see below)

        # 4. Remove all SLSsteam config entries
        try:
            _remove_from_additional_apps(appid)
            # Owned game: steamidra registered the DLC AppIDs, not the base.
            if owned:
                for dlc in lua_dlc_appids:
                    _remove_from_additional_apps(dlc)
            removed.append("additional_apps")
        except Exception:
            pass
        try:
            remove_fake_app_id(appid)
            removed.append("fake_app_id")
        except Exception:
            pass
        try:
            remove_game_token(appid)
            removed.append("game_token")
        except Exception:
            pass
        try:
            remove_game_dlcs(appid)
            removed.append("game_dlcs")
        except Exception:
            pass

        # 5. Remove lumalinux keys.txt lines. keys.txt parent==appid is the
        # reliable source for the native/lumalinux flow; lua_depot_ids
        # supplements it for legacy/no-key shapes recovered from the .lua.
        # config.vdf's DecryptionKeys are left alone: that section is Steam's
        # own key cache, held in memory and rewritten on exit, so editing it
        # while Steam runs is undone (measured 2026-10-06) and a stale key
        # for a depot the user no longer has is inert.
        try:
            keys_res = remove_from_lumalinux_keys(appid, extra_depot_ids=lua_depot_ids, retire=owned)
            if keys_res.get("removed"):
                removed.append("lumalinux_keys")
            if keys_res.get("retired"):
                removed.append("lumalinux_keys_retired")
        except Exception as e:
            logger.warning(f"LumaDeck: lumalinux keys cleanup error: {e}")

        # 5b. Legacy ACCELA update-tracking marker (older steamidra builds).
        try:
            depot_marker = os.path.join(real_home(), ".local", "share", "ACCELA", "depots", f"{appid}.depot")
            if os.path.isfile(depot_marker):
                os.remove(depot_marker)
        except Exception:
            pass

        # 6. Remove achievement files. The schema (LumaDeck-written definitions)
        # always goes; the unlocked-achievement progress file only on the full
        # "remove Proton prefix / my data too" path, so a normal uninstall →
        # reinstall keeps earned achievements.
        if not owned:
            try:
                from achievements import remove_achievement_files
                ach_res = remove_achievement_files(appid, remove_progress=remove_compatdata)
                removed.extend(ach_res.get("removed", []))
                errors.extend(ach_res.get("errors", []))
            except Exception as e:
                logger.warning(f"LumaDeck: achievement cleanup error: {e}")

        # 7. The .lua, last: it is the record of what was ours, and a retry
        # after any failure above must still be able to read it.
        try:
            delete_luatools_for_app(appid)
            removed.append("lua_script")
        except Exception as e:
            errors.append(f"Failed to remove lua: {e}")

        if owned:
            try:
                _pins.set_owned(appid, False)
            except Exception:
                pass

        logger.info(f"LumaDeck: Uninstall {appid} complete (owned={owned}). Removed: {removed}")
        return {"success": True, "removed": removed, "errors": errors}
    except Exception as e:  # noqa: E722 (kept for symmetry with original)
        return {"success": False, "error": str(e)}


# ==========================================
#  DEPOT DECRYPTION KEYS → config.vdf
# ==========================================

def write_depot_decryption_keys(depot_token_map: dict) -> dict:
    """Write DecryptionKey entries for depots into Steam's config.vdf.

    depot_token_map: {depot_id (str/int): token (str)}

    SLSsteam injects keys dynamically, but Steam also reads DecryptionKey
    from config.vdf directly. Writing here ensures the game works even if
    SLSsteam hasn't processed the lua yet.
    """
    import re
    from steam_utils import detect_steam_install_path

    steam_path = detect_steam_install_path()
    if not steam_path:
        return {"success": False, "error": "Steam path not found"}

    config_vdf = os.path.join(steam_path, "config", "config.vdf")
    if not os.path.exists(config_vdf):
        return {"success": False, "error": f"config.vdf not found: {config_vdf}"}

    try:
        with open(config_vdf, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        depots_re = re.compile(r'^([ \t]*)"depots"[ \t]*\n[ \t]*\{', re.MULTILINE)
        m = depots_re.search(content)
        if not m:
            return {"success": False, "error": "depots section not found in config.vdf"}

        d_indent = m.group(1)
        entry_indent = d_indent + "\t"
        field_indent = entry_indent + "\t"

        written = []
        for depot_id, token in depot_token_map.items():
            depot_str = str(depot_id)
            token_str = str(token).strip()
            if not token_str or len(token_str) != 64:
                continue

            new_block = (
                f'{entry_indent}"{depot_str}"\n'
                f'{entry_indent}{{\n'
                f'{field_indent}"DecryptionKey"\t\t"{token_str}"\n'
                f'{entry_indent}}}\n'
            )

            existing_re = re.compile(
                rf'{re.escape(entry_indent)}"{re.escape(depot_str)}"\s*\{{[^{{}}]*\}}',
                re.DOTALL,
            )
            if existing_re.search(content):
                content = existing_re.sub(new_block.rstrip("\n"), content)
                logger.info(f"LumaDeck: Updated DecryptionKey for depot {depot_str}")
            else:
                insert_pos = m.end()
                content = content[:insert_pos] + "\n" + new_block + content[insert_pos:]
                logger.info(f"LumaDeck: Added DecryptionKey for depot {depot_str}")

            written.append(depot_str)

        tmp = config_vdf + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, config_vdf)

        return {"success": True, "written": written}

    except Exception as exc:
        logger.warning(f"LumaDeck: write_depot_decryption_keys failed: {exc}")
        return {"success": False, "error": str(exc)}


# ==========================================
#  Headcrab repair
# ==========================================

_SLS_LOG_PATH = os.path.join(real_home(), ".SLSsteam.log")


def check_slssteam_hash_status() -> dict:
    """Return whether the last SLSsteam session aborted due to an unknown steamclient.so hash."""
    try:
        if not os.path.exists(_SLS_LOG_PATH):
            return {"success": True, "unknown_hash": False}
        with open(_SLS_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        unknown_hash = "Unknown steamclient.so hash! Aborting..." in content
        return {"success": True, "unknown_hash": unknown_hash}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def repair_slssteam_headcrab() -> dict:
    """Repair the unlock stack.

    WS2: re-runs lumalinux/setup.sh (idempotent wrapper-model reinstall of the
    whole stack) instead of headcrab's reset2vanilla + repatch. The old sequence
    ran `reset2vanilla.sh`, hard-killed Steam, and re-patched steam.sh — exactly
    the Game Mode crash-loop / brick pattern seen in the SFF post-mortem. setup.sh
    touches neither steam.sh nor kills Steam, and is idempotent, so a repair is
    just a fresh run of it. (Name kept for the existing main.py/UI binding; WS3
    removed the dead headcrab reset/repatch URLs this used to fetch.)
    """
    from installer import install_via_setup
    return await install_via_setup()


async def reconfigure_slssteam(appid: int) -> dict:
    """Re-run SLSsteam configuration for an already-installed game.

    Useful after fixing add_game_token or when SLSsteam config is out of sync.
    Reads tokens from the installed Lua and writes them to SLSsteam config + config.vdf.
    """
    import re as _re
    from steam_utils import detect_steam_install_path

    results = {}
    try:
        results["additional_apps"] = add_to_additional_apps(appid)
        results["token"] = add_game_token(appid)

        steam_path = detect_steam_install_path() or os.path.join(real_home(), ".local/share/Steam")
        lua_path = os.path.join(steam_path, "config", "stplug-in", f"{appid}.lua")
        if os.path.exists(lua_path):
            with open(lua_path, "r", encoding="utf-8") as lf:
                lua_text = lf.read()
            depot_keys = {}
            for m in _re.finditer(r'addappid\(\s*(\d+)\s*,\s*\d+\s*,\s*"([0-9a-fA-F]{64})"\s*\)', lua_text):
                depot_keys[m.group(1)] = m.group(2)
            if depot_keys:
                results["decryption_keys"] = write_depot_decryption_keys(depot_keys)

        results["dlcs"] = await add_game_dlcs(appid)
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e), "results": results}

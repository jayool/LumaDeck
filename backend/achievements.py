"""SLScheevo achievement generation for LumaDeck.

Downloads, manages, and runs the SLScheevo binary as an async subprocess
to generate achievement files for SLSsteam-managed games.
"""

from __future__ import annotations

import asyncio
import os
import stat
import tarfile
from typing import Any, Dict

from paths import (
    find_slscheevo_binary,
    get_slscheevo_dir,
    get_slscheevo_login_token_path,
    get_steam_appcache_stats_dir,
)

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# ---------------------------------------------------------------------------
# Per-AppID generation state
# ---------------------------------------------------------------------------

ACHIEVEMENT_STATE: Dict[int, Dict[str, Any]] = {}

SLSCHEEVO_DOWNLOAD_STATE: Dict[str, Any] = {"status": "idle"}

_EXIT_CODES = {
    0: "Success",
    1: "General error",
    2: "Invalid arguments",
    3: "Login failed",
    4: "Steam Guard required",
    5: "Rate limited",
    6: "App not found",
    7: "No achievements for this app",
    8: "Network error",
    9: "File write error",
    10: "Token expired",
    11: "Account locked",
    12: "Invalid app ID",
    13: "Service unavailable",
    14: "Unknown error",
}


# ---------------------------------------------------------------------------
# Status checks
# ---------------------------------------------------------------------------

def check_slscheevo_installed() -> dict:
    """Check if SLScheevo binary exists and login token is available."""
    binary = find_slscheevo_binary()
    token = get_slscheevo_login_token_path()
    scheevo_dir = get_slscheevo_dir() if binary else None
    return {
        "success": True,
        "installed": binary is not None,
        "binaryPath": binary,
        "binaryDir": scheevo_dir,
        "loginReady": token is not None,
    }


def check_achievements_status(appid: int) -> dict:
    """Check if achievement files exist for a given appid."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    stats_dir = get_steam_appcache_stats_dir()
    schema_exists = False
    user_stats_exists = False

    if stats_dir and os.path.isdir(stats_dir):
        schema_file = os.path.join(stats_dir, f"UserGameStatsSchema_{appid}.bin")
        schema_exists = os.path.isfile(schema_file)

        suffix = f"_{appid}.bin"
        for fname in os.listdir(stats_dir):
            if fname.startswith("UserGameStats_") and not fname.startswith("UserGameStatsSchema_") and fname.endswith(suffix):
                user_stats_exists = True
                break

    binary = find_slscheevo_binary()
    token = get_slscheevo_login_token_path()

    if not binary:
        status = "not_installed"
    elif not token:
        status = "not_configured"
    elif schema_exists:
        status = "generated"
    else:
        status = "ready"

    gen_state = ACHIEVEMENT_STATE.get(appid, {})
    if gen_state.get("status") == "running":
        status = "generating"

    return {
        "success": True,
        "status": status,
        "generated": schema_exists,
        "schemaExists": schema_exists,
        "userStatsExists": user_stats_exists,
        "installed": binary is not None,
        "loginReady": token is not None,
        "binaryPath": binary,
    }


# ---------------------------------------------------------------------------
# Achievement generation (async subprocess)
# ---------------------------------------------------------------------------

async def _run_slscheevo(appid: int) -> None:
    """Run SLScheevo as async subprocess."""
    binary = find_slscheevo_binary()
    if not binary:
        ACHIEVEMENT_STATE[appid] = {"status": "error", "error": "SLScheevo binary not found"}
        return

    token = get_slscheevo_login_token_path()
    if not token:
        ACHIEVEMENT_STATE[appid] = {"status": "error", "error": "SLScheevo login not configured"}
        return

    try:
        try:
            st = os.stat(binary)
            os.chmod(binary, st.st_mode | stat.S_IEXEC)
        except Exception:
            pass

        scheevo_dir = os.path.dirname(binary)

        # Ensure template file exists (not included in release tar)
        template_path = os.path.join(scheevo_dir, "data", "UserGameStats_TEMPLATE.bin")
        if not os.path.isfile(template_path):
            try:
                from http_client import ensure_http_client
                client = await ensure_http_client("SLScheevo template")
                os.makedirs(os.path.dirname(template_path), exist_ok=True)
                tmpl_resp = await client.get(SLSCHEEVO_TEMPLATE_URL, follow_redirects=True, timeout=15)
                tmpl_resp.raise_for_status()
                tmpl_data: bytes = tmpl_resp.content  # type: ignore[attr-defined]
                with open(template_path, "wb") as f:
                    f.write(tmpl_data)
                import subprocess
                subprocess.run(["chown", "deck:deck", template_path], timeout=5, capture_output=True)
                logger.info(f"LumaDeck: Downloaded missing template ({len(tmpl_data)} bytes)")
            except Exception as exc:
                logger.warning(f"LumaDeck: Failed to download template: {exc}")

        clean_env = os.environ.copy()
        clean_env.pop("LD_LIBRARY_PATH", None)
        clean_env.pop("LD_PRELOAD", None)
        clean_env.pop("STEAM_RUNTIME", None)
        # Decky runs as root — SLScheevo needs HOME pointing to deck's home
        # so it can find Steam at ~/.local/share/Steam
        clean_env["HOME"] = "/home/deck"
        clean_env["USER"] = "deck"
        clean_env["TERM"] = "xterm"

        # SLScheevo must run as the deck user so it can decrypt its per-UID
        # login token (saved as deck). How we get there depends on which user
        # Decky runs this backend as:
        #   - root: drop to deck via runuser (root can, and this is the same
        #     invocation the Steam-restart path uses successfully).
        #   - non-root (Decky running unprivileged as deck): we're ALREADY the
        #     right user, so run the binary directly. runuser here fails outright
        #     ("runuser may not be used by non-root users") — the error users hit
        #     on the Generate button — and is pointless when we're already deck.
        if os.geteuid() == 0:
            cmd = ["runuser", "-u", "deck", "--", binary, "--appid", str(appid), "--silent"]
        else:
            cmd = [binary, "--appid", str(appid), "--silent"]
        logger.info(f"LumaDeck: Running SLScheevo (euid={os.geteuid()}): {' '.join(cmd)}")

        ACHIEVEMENT_STATE[appid] = {
            "status": "running",
            "progress": "Generating achievements...",
            "error": None,
        }

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=scheevo_dir,
            env=clean_env,
        )

        last_line = ""
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            clean_line = line.decode("utf-8", errors="replace").strip()
            if clean_line:
                last_line = clean_line
                ACHIEVEMENT_STATE[appid]["progress"] = clean_line
                logger.info(f"LumaDeck: SLScheevo[{appid}]: {clean_line}")

        await process.wait()
        rc = process.returncode

        logger.info(f"LumaDeck: SLScheevo exit code: {rc} ({_EXIT_CODES.get(rc or -1, 'unknown')})")

        if rc == 0:
            stats_dir = get_steam_appcache_stats_dir()
            if stats_dir:
                try:
                    import subprocess
                    subprocess.run(
                        ["chown", "-R", "deck:deck", stats_dir],
                        timeout=30, capture_output=True,
                    )
                except Exception as chown_exc:
                    logger.warning(f"LumaDeck: chown failed for stats dir: {chown_exc}")

            ACHIEVEMENT_STATE[appid] = {
                "status": "done",
                "progress": "Achievements generated!",
                "error": None,
            }
        else:
            error_msg = _EXIT_CODES.get(rc or -1, f"Unknown error (exit code {rc})")
            if last_line:
                error_msg = f"{error_msg}: {last_line}"
            ACHIEVEMENT_STATE[appid] = {"status": "error", "error": error_msg}

    except Exception as exc:
        logger.error(f"LumaDeck: SLScheevo error: {exc}")
        ACHIEVEMENT_STATE[appid] = {"status": "error", "error": str(exc)}


def generate_achievements(appid: int) -> dict:
    """Start achievement generation. Returns immediately; poll with get_generate_status()."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}

    current = ACHIEVEMENT_STATE.get(appid, {})
    if current.get("status") == "running":
        return {"success": False, "error": "Generation already in progress"}

    ACHIEVEMENT_STATE[appid] = {"status": "running", "progress": "Starting...", "error": None}
    asyncio.create_task(_run_slscheevo(appid))
    return {"success": True}


def get_generate_status(appid: int) -> dict:
    """Return current generation status for an appid."""
    try:
        appid = int(appid)
    except Exception:
        return {"success": False, "error": "Invalid appid"}
    return {"success": True, "state": ACHIEVEMENT_STATE.get(appid, {}).copy()}


# ---------------------------------------------------------------------------
# Batch achievement status & sync all
# ---------------------------------------------------------------------------

ACHIEVEMENT_SYNC_STATE: Dict[str, Any] = {"status": "idle"}


def check_all_achievements_status(appids: list) -> dict:
    """Check which appids have achievement files generated (batch)."""
    stats_dir = get_steam_appcache_stats_dir()
    schema_files: set = set()

    if stats_dir and os.path.isdir(stats_dir):
        for fname in os.listdir(stats_dir):
            if fname.startswith("UserGameStatsSchema_") and fname.endswith(".bin"):
                schema_files.add(fname)

    result_map = {}
    for appid in appids:
        try:
            aid = int(appid)
            result_map[aid] = f"UserGameStatsSchema_{aid}.bin" in schema_files
        except (ValueError, TypeError):
            continue

    return {"success": True, "map": result_map}


async def _run_sync_all(appids: list) -> None:
    """Generate achievements for multiple appids sequentially."""
    global ACHIEVEMENT_SYNC_STATE

    stats_dir = get_steam_appcache_stats_dir()
    schema_files: set = set()
    if stats_dir and os.path.isdir(stats_dir):
        for fname in os.listdir(stats_dir):
            if fname.startswith("UserGameStatsSchema_") and fname.endswith(".bin"):
                schema_files.add(fname)

    pending = []
    for appid in appids:
        try:
            aid = int(appid)
            if f"UserGameStatsSchema_{aid}.bin" not in schema_files:
                pending.append(aid)
        except (ValueError, TypeError):
            continue

    if not pending:
        ACHIEVEMENT_SYNC_STATE = {"status": "done", "done": 0, "total": 0, "errors": []}
        return

    total = len(pending)
    errors = []
    ACHIEVEMENT_SYNC_STATE = {"status": "running", "current": pending[0], "done": 0, "total": total, "errors": []}

    for i, appid in enumerate(pending):
        ACHIEVEMENT_SYNC_STATE["current"] = appid
        ACHIEVEMENT_SYNC_STATE["done"] = i

        await _run_slscheevo(appid)

        state = ACHIEVEMENT_STATE.get(appid, {})
        if state.get("status") == "error":
            errors.append({"appid": appid, "error": state.get("error", "Unknown")})

    ACHIEVEMENT_SYNC_STATE = {"status": "done", "done": total, "total": total, "errors": errors}
    logger.info(f"LumaDeck: Sync all complete. {total} games, {len(errors)} errors")


def generate_all_achievements(appids: list) -> dict:
    """Start batch achievement generation. Poll with get_sync_all_status()."""
    binary = find_slscheevo_binary()
    if not binary:
        return {"success": False, "error": "SLScheevo not installed"}

    token = get_slscheevo_login_token_path()
    if not token:
        return {"success": False, "error": "SLScheevo login not configured"}

    if ACHIEVEMENT_SYNC_STATE.get("status") == "running":
        return {"success": False, "error": "Sync already in progress"}

    asyncio.create_task(_run_sync_all(appids))
    return {"success": True}


def get_sync_all_status() -> dict:
    """Return current batch sync status."""
    return {"success": True, "state": ACHIEVEMENT_SYNC_STATE.copy()}


# ---------------------------------------------------------------------------
# SLScheevo binary download
# ---------------------------------------------------------------------------

SLSCHEEVO_RELEASE_API = "https://api.github.com/repos/xamionex/SLScheevo/releases/latest"
SLSCHEEVO_TEMPLATE_URL = "https://raw.githubusercontent.com/xamionex/SLScheevo/main/data/UserGameStats_TEMPLATE.bin"


async def _download_slscheevo_binary() -> None:
    """Download and extract latest SLScheevo Linux binary from GitHub releases."""
    global SLSCHEEVO_DOWNLOAD_STATE

    try:
        from http_client import ensure_http_client
        client = await ensure_http_client("SLScheevo download")

        SLSCHEEVO_DOWNLOAD_STATE = {
            "status": "downloading",
            "progress": "Fetching release info...",
            "error": None,
        }

        resp = await client.get(SLSCHEEVO_RELEASE_API, timeout=15)
        resp.raise_for_status()
        release = resp.json()

        linux_asset = None
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if "Linux" in name and name.endswith(".tar.gz"):
                linux_asset = asset
                break

        if not linux_asset:
            SLSCHEEVO_DOWNLOAD_STATE = {"status": "error", "error": "No Linux binary found in latest release"}
            return

        download_url = linux_asset["browser_download_url"]
        file_size = linux_asset.get("size", 0)

        SLSCHEEVO_DOWNLOAD_STATE = {
            "status": "downloading",
            "progress": "Downloading SLScheevo...",
            "error": None,
        }

        dest_dir = get_slscheevo_dir()
        os.makedirs(dest_dir, exist_ok=True)
        tmp_archive = os.path.join(dest_dir, "SLScheevo-Linux.tar.gz")

        async with client.stream("GET", download_url, follow_redirects=True, timeout=120) as stream_resp:
            stream_resp.raise_for_status()

            bytes_read = 0
            with open(tmp_archive, "wb") as output:
                async for chunk in stream_resp.aiter_bytes():
                    if not chunk:
                        continue
                    output.write(chunk)
                    bytes_read += len(chunk)

        SLSCHEEVO_DOWNLOAD_STATE["progress"] = "Extracting..."
        SLSCHEEVO_DOWNLOAD_STATE["status"] = "extracting"

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _extract_slscheevo_tar, tmp_archive, dest_dir)

        # Download UserGameStats_TEMPLATE.bin (not included in release tar)
        template_dir = os.path.join(dest_dir, "data")
        os.makedirs(template_dir, exist_ok=True)
        template_path = os.path.join(template_dir, "UserGameStats_TEMPLATE.bin")
        if not os.path.isfile(template_path):
            SLSCHEEVO_DOWNLOAD_STATE["progress"] = "Downloading template file..."
            try:
                tmpl_resp = await client.get(SLSCHEEVO_TEMPLATE_URL, follow_redirects=True, timeout=15)
                tmpl_resp.raise_for_status()
                tmpl_data2: bytes = tmpl_resp.content  # type: ignore[attr-defined]
                with open(template_path, "wb") as f:
                    f.write(tmpl_data2)
                logger.info(f"LumaDeck: Downloaded UserGameStats_TEMPLATE.bin ({len(tmpl_data2)} bytes)")
            except Exception as tmpl_exc:
                logger.warning(f"LumaDeck: Failed to download template: {tmpl_exc}")

        binary_path = os.path.join(dest_dir, "SLScheevo")
        if not os.path.isfile(binary_path):
            binary_path = os.path.join(dest_dir, "SLScheevo-Linux")
        if os.path.isfile(binary_path):
            os.chmod(binary_path, 0o755)

        # Decky runs as root — make the directory writable by deck user
        # so they can run SLScheevo in terminal and save login token
        try:
            import subprocess
            subprocess.run(
                ["chown", "-R", "deck:deck", dest_dir],
                timeout=10, capture_output=True,
            )
        except Exception as chown_exc:
            logger.warning(f"LumaDeck: chown failed for SLScheevo dir: {chown_exc}")

        try:
            os.remove(tmp_archive)
        except Exception:
            pass

        SLSCHEEVO_DOWNLOAD_STATE = {"status": "done", "progress": "SLScheevo installed!", "error": None}
        logger.info(f"LumaDeck: SLScheevo installed to {dest_dir}")

    except Exception as exc:
        logger.error(f"LumaDeck: SLScheevo download failed: {exc}")
        SLSCHEEVO_DOWNLOAD_STATE = {"status": "error", "error": str(exc)}


def _extract_slscheevo_tar(archive_path: str, dest_dir: str) -> None:
    """Extract SLScheevo tar.gz safely."""
    real_dest = os.path.realpath(dest_dir)
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            member_path = os.path.realpath(os.path.join(dest_dir, member.name))
            if not member_path.startswith(real_dest + os.sep) and member_path != real_dest:
                raise RuntimeError(f"Tar path traversal blocked: {member.name}")
        tar.extractall(dest_dir)


def download_slscheevo() -> dict:
    """Start downloading SLScheevo binary. Poll get_slscheevo_download_status()."""
    if SLSCHEEVO_DOWNLOAD_STATE.get("status") in ("downloading", "extracting"):
        return {"success": False, "error": "Download already in progress"}
    asyncio.create_task(_download_slscheevo_binary())
    return {"success": True}


def get_slscheevo_download_status() -> dict:
    """Return current SLScheevo binary download status."""
    return {"success": True, "state": SLSCHEEVO_DOWNLOAD_STATE.copy()}

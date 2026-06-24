"""In-plugin self-update from GitHub releases (#23).

LumaDeck is sideloaded (not a Decky-store plugin), so it doesn't get Decky's
automatic updates. This module fills that gap: it compares the installed
version against the latest jayool/LumaDeck release and, on request, downloads
the LumaDeck.zip asset and extracts it over the plugin directory.

Manual-first by design — the frontend exposes a "Check for updates" button in
Settings ▸ About and surfaces a notice in the QAM update banner. There is no
background auto-installer. Only ever pulls from our own repo.
"""
import json
import os
import re
import shutil
import tempfile
import zipfile

from http_client import ensure_http_client
from paths import get_plugin_dir, settings_dir

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

_REPO = "jayool/LumaDeck"
_ASSET = "LumaDeck.zip"


def _pending_zip_path() -> str:
    # Lives in the settings dir (outside the plugin dir) so it survives the
    # extraction that overwrites the plugin dir, and persists across restarts.
    return os.path.join(settings_dir(), "pending_update.zip")


def _installed_version() -> str:
    """The plugin's own version, from the package.json shipped in the plugin dir."""
    try:
        with open(os.path.join(get_plugin_dir(), "package.json"), "r", encoding="utf-8") as f:
            return str(json.load(f).get("version", "0.0.0"))
    except Exception:
        return "0.0.0"


def _parse_version(s: str) -> tuple:
    """'v0.3.15' / '0.3.15' -> (0, 3, 15). Pads/truncates to 3 components."""
    nums = [int(n) for n in re.findall(r"\d+", s or "")][:3]
    return tuple(nums) + (0,) * (3 - len(nums))


async def check_plugin_update() -> dict:
    """Compare the installed version against the latest GitHub release.

    Returns {success, has_update, installed, latest, download_url}. Never
    raises — a network failure is reported as success=False so callers (the
    QAM load path included) can stay quiet.
    """
    installed = _installed_version()
    try:
        client = await ensure_http_client("self_update")
        resp = await client.get(
            f"https://api.github.com/repos/{_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"success": False, "error": f"GitHub API {resp.status_code}", "installed": installed}
        data = resp.json()
        latest_tag = data.get("tag_name") or ""
        download_url = ""
        for asset in data.get("assets", []):
            if asset.get("name") == _ASSET:
                download_url = asset.get("browser_download_url", "")
                break
        has_update = _parse_version(latest_tag) > _parse_version(installed)
        return {
            "success": True,
            "has_update": bool(has_update and download_url),
            "installed": installed,
            "latest": latest_tag.lstrip("v"),
            "download_url": download_url,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "installed": installed}


def _extract_over_plugin(zip_path: str) -> bool:
    """Apply LumaDeck.zip over the *live* plugin directory.

    The zip wraps everything in a single top-level `LumaDeck/` folder. The old
    approach extracted to the plugin dir's PARENT, which silently breaks in two
    ways that both leave the real files untouched (the update "succeeds" yet the
    version never changes):
      - if DECKY_PLUGIN_DIR carries a trailing slash, os.path.dirname() returns
        the plugin dir itself, so the zip lands nested at LumaDeck/LumaDeck/…;
      - if the on-disk folder isn't named exactly `LumaDeck`, the zip's folder
        is created alongside it instead of over it.

    Instead: extract to a temp dir, descend into the single wrapping folder, and
    copy its contents straight into the normalised plugin dir. Path- and
    name-proof. Only files present in the zip are overwritten, so user data
    under backend/data/ (api.json, cookies) is left untouched.
    """
    if not zipfile.is_zipfile(zip_path):
        return False
    plugin_dir = os.path.normpath(get_plugin_dir())
    with tempfile.TemporaryDirectory() as tmpd:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmpd)
        entries = [e for e in os.listdir(tmpd) if not e.startswith(".")]
        src = (
            os.path.join(tmpd, entries[0])
            if len(entries) == 1 and os.path.isdir(os.path.join(tmpd, entries[0]))
            else tmpd
        )
        for root, _dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            dest = plugin_dir if rel == "." else os.path.join(plugin_dir, rel)
            os.makedirs(dest, exist_ok=True)
            for fn in files:
                shutil.copy2(os.path.join(root, fn), os.path.join(dest, fn))
    return True


async def update_plugin() -> dict:
    """Download the latest LumaDeck.zip and apply it.

    Overwriting the running plugin's files is fine on Linux (the loaded code
    keeps running; the new code takes effect on the next Steam restart). If the
    extraction fails anyway, the zip is staged and applied at the next plugin
    load by apply_pending_update_if_any().
    """
    info = await check_plugin_update()
    if not info.get("success"):
        return {"success": False, "error": info.get("error", "update check failed")}
    if not info.get("has_update"):
        return {"success": True, "updated": False, "message": "Already up to date"}

    tmp = os.path.join(settings_dir(), "_dl_update.zip")
    try:
        client = await ensure_http_client("self_update")
        resp = await client.get(info["download_url"], follow_redirects=True, timeout=60)
        if resp.status_code != 200:
            return {"success": False, "error": f"Download failed ({resp.status_code})"}
        with open(tmp, "wb") as f:
            f.write(resp.content)
    except Exception as exc:
        return {"success": False, "error": f"Download failed: {exc}"}

    if not zipfile.is_zipfile(tmp):
        try:
            os.remove(tmp)
        except Exception:
            pass
        return {"success": False, "error": "Downloaded asset is not a valid zip"}

    plugin_dir = os.path.normpath(get_plugin_dir())
    try:
        _extract_over_plugin(tmp)
        os.remove(tmp)
        # Trust nothing: re-read the version on disk. If it didn't become the
        # target, the extraction wrote somewhere harmless (or couldn't write at
        # all) — report that honestly instead of a false "applied", and include
        # the path + euid so the real cause (wrong dir vs. permissions) is clear.
        applied = _installed_version()
        logger.info(
            "LumaDeck: self-update extracted into %s (on-disk now %s, target %s, euid %s)",
            plugin_dir, applied, info.get("latest"), os.geteuid(),
        )
        if _parse_version(applied) != _parse_version(info.get("latest", "")):
            return {
                "success": False,
                "error": (
                    f"Update extracted but {plugin_dir}/package.json is still "
                    f"{applied} (wanted {info.get('latest')}). euid={os.geteuid()} "
                    "— likely the plugin process can't write its own directory."
                ),
            }
        return {"success": True, "updated": True, "pending": False, "latest": info.get("latest")}
    except Exception as exc:
        logger.warning("LumaDeck: live update extraction failed, staging pending: %s", exc)
        try:
            os.replace(tmp, _pending_zip_path())
            return {"success": True, "updated": True, "pending": True, "latest": info.get("latest")}
        except Exception as exc2:
            return {"success": False, "error": f"Could not stage update: {exc2}"}


def apply_pending_update_if_any() -> None:
    """Apply a staged update zip at plugin load, then remove it. Synchronous so
    it can run at the very top of _main. Takes effect on the following restart
    (the current session already loaded the old code)."""
    pending = _pending_zip_path()
    if not os.path.isfile(pending):
        return
    try:
        if _extract_over_plugin(pending):
            logger.info(
                "LumaDeck: applied pending self-update (on-disk now %s, euid %s)",
                _installed_version(), os.geteuid(),
            )
        os.remove(pending)
    except Exception as exc:
        logger.warning("LumaDeck: failed to apply pending update: %s", exc)

"""Unified component status — one shape for SLSsteam, lumalinux, CloudRedirect.

Aggregates the existing per-component health (paths.read_*_health) and update
checks into a single payload the UI consumes in one call, instead of 8 separate
fetches. See the "Component model" spec in DESIGN_UI.md.

ADDITIVE: this wraps existing detection functions, it does not replace them. The
frontend swap (and deleting the old per-component fetches/banners) is a later
step — this module can ship without changing anything visible.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Optional

from http_client import ensure_http_client
from update_checks import has_update

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# The exact asset h3adcr-b installs for CloudRedirect: a rolling `linux-test`
# tag whose cloud_redirect.so is replaced in place (no semver). The only honest
# "is there an update" check is a content-hash compare against this file.
_CR_LINUX_TEST_SO = (
    "https://github.com/Selectively11/h3adcr-b/releases/download/"
    "linux-test/cloud_redirect.so"
)
_CR_HASH_CACHE = os.path.expanduser("~/.cache/lumadeck/releases/cr_linux_test.json")
_CR_CACHE_TTL = 6 * 60 * 60  # 6 h, same TTL as the GitHub release checks
_FETCH_TIMEOUT = 20.0


# --- SLSsteam update (via h3adcr-b's source repo) ---------------------------

async def check_slssteam_update() -> dict:
    """SLSsteam update = a newer release at AceSLS/SLSsteam — the repo h3adcr-b
    installs `latest` from. Compares the installed config Version against it.
    Replaces the old (wrong) signal derived from headcrab compatibility."""
    from slssteam_config import get_sls_version
    return await has_update("AceSLS", "SLSsteam", get_sls_version())


# --- CloudRedirect update (content hash, via h3adcr-b's asset) ---------------

def _sha256_file(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _read_cr_cache() -> Optional[str]:
    try:
        with open(_CR_HASH_CACHE, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry.get("_cached_at", 0) > _CR_CACHE_TTL:
            return None
        return entry.get("hash")
    except Exception:
        return None


def _write_cr_cache(remote_hash: str) -> None:
    try:
        os.makedirs(os.path.dirname(_CR_HASH_CACHE), exist_ok=True)
        with open(_CR_HASH_CACHE, "w", encoding="utf-8") as f:
            json.dump({"hash": remote_hash, "_cached_at": time.time()}, f)
    except Exception as exc:
        logger.warning(f"components: failed to write CR hash cache: {exc}")


async def _remote_cr_hash() -> Optional[str]:
    """sha256 of the current linux-test cloud_redirect.so, cached 6 h. None on
    network failure (caller then reports no-update, the safe default)."""
    cached = _read_cr_cache()
    if cached:
        return cached
    try:
        client = await ensure_http_client(context="cr_update")
        resp = await client.get(_CR_LINUX_TEST_SO, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200 and resp.content:
            remote = hashlib.sha256(resp.content).hexdigest()
            _write_cr_cache(remote)
            return remote
        logger.info(f"components: CR asset HTTP {resp.status_code}")
    except Exception as exc:
        logger.info(f"components: CR hash fetch failed ({exc})")
    return None


async def check_cloudredirect_update() -> dict:
    """CloudRedirect has no semver of its own — its "version" is which build of
    the linux-test cloud_redirect.so is on disk. has_update = installed .so
    differs from the current linux-test asset. Returns the has_update shape with
    short hashes in installed/latest for display/debug."""
    from paths import cloudredirect_so_path
    local_path = cloudredirect_so_path()
    local = _sha256_file(local_path) if local_path else None
    if not local:
        return {"installed": None, "latest": None, "has_update": False, "url": None}
    remote = await _remote_cr_hash()
    if not remote:
        return {"installed": local[:12], "latest": None, "has_update": False, "url": None}
    return {
        "installed": local[:12],
        "latest": remote[:12],
        "has_update": local != remote,
        "url": None,
    }


# --- The aggregate -----------------------------------------------------------

def _component(id_: str, name: str, installed: bool, health: dict, update: dict) -> dict:
    return {
        "id": id_,
        "name": name,
        "installed": installed,
        "health": health.get("state"),
        "cause": health.get("cause"),
        "action": health.get("action"),
        "update": {
            "installed": update.get("installed"),
            "latest": update.get("latest"),
            "available": bool(update.get("has_update")),
        },
    }


async def get_components_status() -> dict:
    """One uniform payload for the system-status surface — per-component health +
    update, plus the headcrab compat gate and the plugin. Wraps existing
    detection; nothing here re-implements it."""
    from paths import (
        read_slssteam_health,
        read_lumalinux_health,
        read_cloudredirect_health,
        check_slssteam_installed,
        check_lumalinux_installed,
        check_cloudredirect_installed,
    )
    from headcrab_compat import check_headcrab_compat
    from self_update import check_plugin_update

    def _safe_sync(fn, default):
        try:
            return fn()
        except Exception as exc:
            logger.warning(f"components: {getattr(fn, '__name__', 'check')} failed: {exc}")
            return default

    async def _safe(coro, default):
        # Each subcheck is isolated: a single failure (network, parse) must not
        # blank the whole status surface.
        try:
            return await coro
        except Exception as exc:
            logger.warning(f"components: async check failed: {exc}")
            return default

    no_update = {"installed": None, "latest": None, "has_update": False}

    sls_health = _safe_sync(read_slssteam_health, {"state": None})
    ll_health = _safe_sync(read_lumalinux_health, {"state": None})
    cr_health = _safe_sync(read_cloudredirect_health, {"state": None})

    sls_update = await _safe(check_slssteam_update(), no_update)
    ll_update = await _safe(has_update("jayool", "lumalinux", ll_health.get("version")), no_update)
    cr_update = await _safe(check_cloudredirect_update(), no_update)

    headcrab = await _safe(check_headcrab_compat(), {"compatible": None, "target": None, "current_build": None})
    plugin = await _safe(check_plugin_update(), {"installed": None, "latest": None, "has_update": False})

    components = [
        _component("slssteam", "SLSsteam", check_slssteam_installed(), sls_health, sls_update),
        _component("cloudredirect", "CloudRedirect", check_cloudredirect_installed(), cr_health, cr_update),
        _component("lumalinux", "lumalinux", check_lumalinux_installed(), ll_health, ll_update),
    ]

    return {
        "success": True,
        "components": components,
        "headcrab": {
            "compatible": headcrab.get("compatible"),
            "target": headcrab.get("target"),
            "current": headcrab.get("current_build"),
        },
        "plugin": {
            "installed": plugin.get("installed"),
            "latest": plugin.get("latest"),
            "available": bool(plugin.get("has_update")),
        },
    }

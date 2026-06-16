"""GitHub Releases API client for checking component updates.

Used to detect whether a newer release of CloudRedirect / lumalinux is available
upstream. Cached to disk so opening the panel doesn't hit the API every time —
60 req/hour anonymous is plenty, but the right TTL is 6 h regardless (a new
release can wait that long to surface, the user notices fine).

SLSsteam doesn't go through this — its update signal is "is Headcrab's pin
ahead of the local Steam build?", which lives in headcrab_compat.py.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from http_client import ensure_http_client

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


_CACHE_DIR = os.path.expanduser("~/.cache/lumadeck/releases")
_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 h
_FETCH_TIMEOUT = 10.0


def _cache_path(owner: str, repo: str) -> str:
    return os.path.join(_CACHE_DIR, f"{owner}__{repo}.json")


def _read_cache(owner: str, repo: str) -> Optional[dict]:
    """Return cached entry if it exists and is still within TTL. Else None.

    A stale cache (older than TTL) is treated as missing — we'd rather refetch
    than serve outdated tags. If the network refetch fails, the caller can
    fall back to reading the stale entry on its own.
    """
    path = _cache_path(owner, repo)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        ts = entry.get("_cached_at", 0)
        if time.time() - ts > _CACHE_TTL_SECONDS:
            return None
        return entry
    except Exception:
        return None


def _read_cache_stale_ok(owner: str, repo: str) -> Optional[dict]:
    """Return cached entry even if past TTL — for the offline fallback path."""
    path = _cache_path(owner, repo)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(owner: str, repo: str, payload: dict) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        payload["_cached_at"] = time.time()
        with open(_cache_path(owner, repo), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception as exc:
        logger.warning(f"update_checks: failed to write cache: {exc}")


def _normalise(tag: str) -> str:
    """Drop a leading 'v' from a release tag so comparisons match semvers
    reported by the binaries (lumalinux status.json reports "0.13.5"; the
    release tag is "v0.13.5"). No deeper semver parsing — equality is enough
    for "is this the same release"."""
    if tag and (tag[0] == "v" or tag[0] == "V"):
        return tag[1:]
    return tag


async def get_latest_release(owner: str, repo: str) -> Optional[dict]:
    """Return {"tag": str, "tag_normalised": str, "url": str} for the latest
    release of owner/repo, or None if unreachable. Reads cache first (6 h TTL),
    refetches on miss, falls back to a stale cache entry on network failure."""
    cached = _read_cache(owner, repo)
    if cached and cached.get("tag"):
        return {
            "tag": cached["tag"],
            "tag_normalised": cached.get("tag_normalised") or _normalise(cached["tag"]),
            "url": cached.get("url", ""),
        }

    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        client = await ensure_http_client(context="update_checks")
        resp = await client.get(url, timeout=_FETCH_TIMEOUT,
                                headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 200:
            data = resp.json()
            tag = data.get("tag_name") or ""
            html_url = data.get("html_url") or ""
            payload = {"tag": tag, "tag_normalised": _normalise(tag), "url": html_url}
            _write_cache(owner, repo, payload)
            return payload
        logger.info(f"update_checks: HTTP {resp.status_code} from {url}, using stale cache")
    except Exception as exc:
        logger.info(f"update_checks: live fetch failed ({exc}), using stale cache")

    stale = _read_cache_stale_ok(owner, repo)
    if stale and stale.get("tag"):
        return {
            "tag": stale["tag"],
            "tag_normalised": stale.get("tag_normalised") or _normalise(stale["tag"]),
            "url": stale.get("url", ""),
        }
    return None


async def has_update(owner: str, repo: str, installed_version: Optional[str]) -> dict:
    """Compare an installed version string against the latest release tag.

    Returns {"installed", "latest", "has_update", "url"}. has_update is False
    when we can't determine it (unknown installed, unreachable latest) — the
    safe default is "no nag".
    """
    latest = await get_latest_release(owner, repo)
    if not latest or not installed_version:
        return {
            "installed": installed_version,
            "latest": latest.get("tag_normalised") if latest else None,
            "has_update": False,
            "url": latest.get("url") if latest else None,
        }
    installed_norm = _normalise(installed_version.strip())
    return {
        "installed": installed_norm,
        "latest": latest["tag_normalised"],
        "has_update": installed_norm != latest["tag_normalised"],
        "url": latest.get("url"),
    }

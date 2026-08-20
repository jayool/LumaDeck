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
import re
import time
from typing import Optional

from http_client import ensure_http_client
from paths import real_home

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# Decky runs the backend as root, so expanduser("~") would be /root; use the
# real user's home so every lumadeck cache lives under one tree (matches
# headcrab_compat._CACHE_DIR). On SteamOS this is /home/deck/.cache/... as before.
_CACHE_DIR = os.path.join(real_home(), ".cache/lumadeck/releases")
_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 h
_FETCH_TIMEOUT = 10.0


def _cache_path(owner: str, repo: str, variant: str = "") -> str:
    # `variant` keeps different questions about the same repo in different files
    # (e.g. "the latest release" vs "the latest release that ships <asset>",
    # which are not the same release for a repo with per-platform releases).
    suffix = f"__{re.sub(r'[^A-Za-z0-9._-]', '_', variant)}" if variant else ""
    return os.path.join(_CACHE_DIR, f"{owner}__{repo}{suffix}.json")


def _read_cache(owner: str, repo: str, variant: str = "") -> Optional[dict]:
    """Return cached entry if it exists and is still within TTL. Else None.

    A stale cache (older than TTL) is treated as missing — we'd rather refetch
    than serve outdated tags. If the network refetch fails, the caller can
    fall back to reading the stale entry on its own.
    """
    path = _cache_path(owner, repo, variant)
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


def _read_cache_stale_ok(owner: str, repo: str, variant: str = "") -> Optional[dict]:
    """Return cached entry even if past TTL — for the offline fallback path."""
    path = _cache_path(owner, repo, variant)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(owner: str, repo: str, payload: dict, variant: str = "") -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        payload["_cached_at"] = time.time()
        with open(_cache_path(owner, repo, variant), "w", encoding="utf-8") as f:
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


def _version_tuple(v: str) -> tuple:
    """Parse a normalised version ('0.16.9') into a comparable (major, minor,
    patch) int tuple, padded to 3. Used so 'is there an update' means installed
    < latest (semver order), NOT installed != latest — otherwise a stale-cached
    'latest' that is OLDER than the installed build nags 'update available'
    forever (installed 0.17.0 vs a stale-cached 0.16.9)."""
    nums = re.findall(r"\d+", v or "")
    t = tuple(int(n) for n in nums[:3])
    return t + (0,) * (3 - len(t))


async def get_latest_release(owner: str, repo: str, force: bool = False) -> Optional[dict]:
    """Return {"tag": str, "tag_normalised": str, "url": str} for the latest
    release of owner/repo, or None if unreachable. Reads cache first (6 h TTL),
    refetches on miss, falls back to a stale cache entry on network failure.
    force=True skips the fresh-cache read so a manual refresh always re-fetches
    (the stale-cache fallback on network failure still applies)."""
    cached = None if force else _read_cache(owner, repo)
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


# How many releases back to look for one that ships the asset. CloudRedirect's
# longest observed run of consecutive Windows-only releases is two (v2.6.1 and
# v2.6.2); ten leaves a wide margin without paging.
_RELEASES_PAGE_SIZE = 10


async def get_latest_release_with_asset(
    owner: str, repo: str, asset_name: str, force: bool = False,
) -> Optional[dict]:
    """Newest release that actually publishes `asset_name`.

    /releases/latest is the wrong question for a repo whose releases are not all
    for every platform. CloudRedirect cuts Windows-only releases — v2.1.9,
    v2.2.4, v2.5.3, v2.6.1 and v2.6.2 carry CloudRedirect.exe but no
    cloud_redirect.so — so "latest" regularly names a version that has no Linux
    build at all. Announcing it would nag forever: applying the update installs
    the same .so it already had, and the offer comes straight back.

    Same {"tag", "tag_normalised", "url"} shape and same caching behaviour as
    get_latest_release, under a cache key of its own. None when unreachable and
    no cache exists, which callers treat as "no update".

    A successful fetch that matches nothing falls back to the stale cache too,
    not just a failed one: if the newest Linux release has scrolled past the page
    (a long run of Windows-only releases), the last one we saw is a better answer
    than None — None would read as "up to date" and hide a real update.
    """
    cached = None if force else _read_cache(owner, repo, asset_name)
    if cached and cached.get("tag"):
        return {
            "tag": cached["tag"],
            "tag_normalised": cached.get("tag_normalised") or _normalise(cached["tag"]),
            "url": cached.get("url", ""),
        }

    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={_RELEASES_PAGE_SIZE}"
    try:
        client = await ensure_http_client(context="update_checks")
        resp = await client.get(url, timeout=_FETCH_TIMEOUT,
                                headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 200:
            # The API returns releases newest-first, so the first match wins.
            # Drafts and prereleases are skipped to match /releases/latest, which
            # is what every other component here is compared against.
            for release in resp.json() or []:
                if release.get("draft") or release.get("prerelease"):
                    continue
                names = {a.get("name") for a in release.get("assets") or []}
                if asset_name not in names:
                    continue
                tag = release.get("tag_name") or ""
                payload = {"tag": tag, "tag_normalised": _normalise(tag),
                           "url": release.get("html_url") or ""}
                _write_cache(owner, repo, payload, asset_name)
                return payload
            logger.info(
                f"update_checks: no release in the last {_RELEASES_PAGE_SIZE} of "
                f"{owner}/{repo} ships {asset_name}"
            )
        else:
            logger.info(f"update_checks: HTTP {resp.status_code} from {url}, using stale cache")
    except Exception as exc:
        logger.info(f"update_checks: live fetch failed ({exc}), using stale cache")

    stale = _read_cache_stale_ok(owner, repo, asset_name)
    if stale and stale.get("tag"):
        return {
            "tag": stale["tag"],
            "tag_normalised": stale.get("tag_normalised") or _normalise(stale["tag"]),
            "url": stale.get("url", ""),
        }
    return None


async def has_update(owner: str, repo: str, installed_version: Optional[str],
                     force: bool = False) -> dict:
    """Compare an installed version string against the latest release tag.

    Returns {"installed", "latest", "has_update", "url"}. has_update is False
    when we can't determine it (unknown installed, unreachable latest) — the
    safe default is "no nag". force=True bypasses the release cache.
    """
    latest = await get_latest_release(owner, repo, force=force)
    return await has_update_from(installed_version, latest)


async def has_update_from(installed_version: Optional[str],
                          latest: Optional[dict]) -> dict:
    """The comparison half of has_update, against an already-resolved release.

    Split out for callers that do not want "the latest release" — CloudRedirect
    needs the latest release that ships a Linux asset, which is a different
    release (see get_latest_release_with_asset). The verdict must stay identical
    either way, so both paths share this.
    """
    if not latest or not installed_version:
        return {
            "installed": installed_version,
            "latest": latest.get("tag_normalised") if latest else None,
            "has_update": False,
            "url": latest.get("url") if latest else None,
        }
    installed_norm = _normalise(installed_version.strip())
    latest_norm = latest["tag_normalised"]
    # Update only when the installed version is genuinely BEHIND latest (semver),
    # not merely different — so a stale-cached 'latest' that is OLDER than the
    # installed build (e.g. installed 0.17.0 vs a stale 0.16.9) never nags.
    return {
        "installed": installed_norm,
        "latest": latest_norm,
        "has_update": _version_tuple(installed_norm) < _version_tuple(latest_norm),
        "url": latest.get("url"),
    }

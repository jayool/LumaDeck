"""Headcrab build-ID compatibility check.

Headcrab pins Steam to a single client build (see `HeadcrabCompatibleClientVer`
in https://raw.githubusercontent.com/Deadboy666/h3adcr-b/main/headcrab.sh).
Deadboy666 bumps that pin whenever Valve ships a new client he has tested
against, which means hardcoding the value in the plugin goes stale within
weeks. We fetch the current pin dynamically from the live script on every
mount of the Settings page, cache the last seen value to disk, and fail
closed if neither network nor cache yields a number.

If the current Steam build differs from the pinned target, running
`headcrab.sh` from Game Mode triggers its downgrade flow, which races
with gamescope's short-session detection and ends up wiping the Steam
dir. The check feeds the gate on every UI surface that invokes Headcrab
(Install Dependencies, Repair SLSsteam Headcrab) so the user is pushed
at Desktop Mode in that case.
"""

from __future__ import annotations

import glob
import os
import re

from http_client import ensure_http_client
from paths import find_steam_root

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


_HEADCRAB_URL = "https://raw.githubusercontent.com/Deadboy666/h3adcr-b/main/headcrab.sh"
_CACHE_DIR = "/home/deck/.cache/lumadeck"
_CACHE_FILE = os.path.join(_CACHE_DIR, "headcrab_target")
_FETCH_TIMEOUT = 5.0

# lumalinux annotates each whitelisted hash in res/updates.yaml with a
# `# steam_version: <build>` comment (SafeModeHashes). Headcrab bumps its pin on
# SLSsteam + CloudRedirect readiness only — NOT lumalinux — so a user could align
# Steam to a build lumalinux can't hook yet and break native downloads. We gate
# the Steam-update offer on lumalinux ALSO being ready for the target build.
_LUMALINUX_UPDATES_URL = "https://raw.githubusercontent.com/jayool/lumalinux/main/res/updates.yaml"
_LL_CACHE_FILE = os.path.join(_CACHE_DIR, "lumalinux_updates.yaml")

# The SafeMode group-id (res/version.txt) compiled into the LATEST published .so,
# shipped as a release asset by lumalinux's build.yml. The deployed .so keys on
# its compile-time group (src/update.cpp: clientHashMap[VERSION]) and only trusts
# THAT group's hashes — so "will installing latest hook build X?" is answered by
# "is X whitelisted under the RELEASE's group", not "under the newest group main
# may carry ahead of a release". Reading main's newest group would offer a build
# the downloadable binary can't hook yet (the release/updates.yaml fleco).
_LUMALINUX_RELEASE_VERSION_URL = "https://github.com/jayool/lumalinux/releases/latest/download/version.txt"
_REL_GROUP_CACHE_FILE = os.path.join(_CACHE_DIR, "lumalinux_release_group")


def _manifest_path() -> str | None:
    """Find Steam's installed-client manifest.

    Filename varies by branch — SteamOS Stable writes
    `steam_client_steamdeck_stable_ubuntu12.manifest`, generic Linux Steam
    writes `steam_client_ubuntu12.manifest`, Beta writes
    `steam_client_steamdeck_beta_ubuntu12.manifest`. We glob for any
    `steam_client_*.manifest` in the package dir and pick the most recently
    modified — that's the active channel.
    """
    root = find_steam_root()
    if not root:
        return None
    pkg_dir = os.path.join(root, "package")
    if not os.path.isdir(pkg_dir):
        return None
    candidates = glob.glob(os.path.join(pkg_dir, "steam_client_*.manifest"))
    if not candidates:
        return None
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def current_steam_build() -> int | None:
    """Read the active Steam client build from the manifest.

    The manifest uses Valve's KeyValues format; the line we want looks like:
        "version"               "1781041600"
    """
    path = _manifest_path()
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'^\s*"version"\s+"(\d+)"', line)
                if m:
                    return int(m.group(1))
    except Exception as exc:
        logger.warning(f"headcrab_compat: failed to read manifest at {path}: {exc}")
    return None


def _parse_target(content: str) -> int | None:
    m = re.search(r'^\s*HeadcrabCompatibleClientVer\s*=\s*(\d+)', content, re.MULTILINE)
    return int(m.group(1)) if m else None


def _save_cache(target: int) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(str(target))
    except Exception as exc:
        logger.warning(f"headcrab_compat: failed to write cache: {exc}")


def _load_cache() -> int | None:
    try:
        if not os.path.isfile(_CACHE_FILE):
            return None
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception as exc:
        logger.warning(f"headcrab_compat: failed to read cache: {exc}")
        return None


async def headcrab_target() -> int | None:
    """Fetch the current Headcrab-pinned client version from upstream.

    Live read of `HeadcrabCompatibleClientVer` in Deadboy666/h3adcr-b's
    main branch via LumaDeck's shared HTTP client (handles SSL/CA bundle
    on the PyInstaller-bundled Python that Decky ships). Cached on disk
    after a successful fetch so the check keeps working offline. Fails
    closed (returns None) if neither network nor cache yields a value.
    """
    try:
        client = await ensure_http_client(context="headcrab_compat")
        resp = await client.get(_HEADCRAB_URL, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200:
            target = _parse_target(resp.text)
            if target is not None:
                _save_cache(target)
                return target
            logger.warning("headcrab_compat: fetched script but no HeadcrabCompatibleClientVer line")
        else:
            logger.info(f"headcrab_compat: HTTP {resp.status_code} from upstream, falling back to cache")
    except Exception as exc:
        logger.info(f"headcrab_compat: live fetch failed ({exc}), falling back to cache")

    return _load_cache()


async def _lumalinux_updates_text() -> str | None:
    """Fetch lumalinux's res/updates.yaml (main), cached to disk. None if
    unreachable and no cache. main is the right source for the per-group BUILD
    LISTS (hashes append live, no release needed); the group POINTER comes from
    the release instead — see latest_release_group()."""
    text = None
    try:
        client = await ensure_http_client(context="headcrab_compat")
        resp = await client.get(_LUMALINUX_UPDATES_URL, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200:
            text = resp.text
            try:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                with open(_LL_CACHE_FILE, "w", encoding="utf-8") as f:
                    f.write(text)
            except Exception as exc:
                logger.warning(f"headcrab_compat: failed to cache lumalinux updates: {exc}")
        else:
            logger.info(f"headcrab_compat: HTTP {resp.status_code} for lumalinux updates, trying cache")
    except Exception as exc:
        logger.info(f"headcrab_compat: lumalinux updates fetch failed ({exc}), trying cache")

    if text is None:
        try:
            with open(_LL_CACHE_FILE, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return None
    return text


async def latest_release_group() -> str | None:
    """The SafeMode group-id (res/version.txt value) compiled into the LATEST
    published lumalinux release .so, read from its release asset.

    This is the authority for "which SafeModeHashes group does the downloadable
    binary actually hook?" — the .so trusts only its compile-time group. Cached to
    disk. Returns None when unreachable + no cache, OR when the release predates
    the version.txt asset (older releases); callers then fall back to a whole-file
    scan (safe while a single group exists)."""
    group = None
    try:
        client = await ensure_http_client(context="headcrab_compat")
        resp = await client.get(_LUMALINUX_RELEASE_VERSION_URL, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200:
            cand = resp.text.strip()
            if re.fullmatch(r"\d+", cand):
                group = cand
                try:
                    os.makedirs(_CACHE_DIR, exist_ok=True)
                    with open(_REL_GROUP_CACHE_FILE, "w", encoding="utf-8") as f:
                        f.write(group)
                except Exception as exc:
                    logger.warning(f"headcrab_compat: failed to cache release group: {exc}")
        else:
            logger.info(f"headcrab_compat: HTTP {resp.status_code} for release version.txt, trying cache")
    except Exception as exc:
        logger.info(f"headcrab_compat: release version.txt fetch failed ({exc}), trying cache")

    if group is None:
        try:
            with open(_REL_GROUP_CACHE_FILE, "r", encoding="utf-8") as f:
                cand = f.read().strip()
                group = cand if re.fullmatch(r"\d+", cand) else None
        except Exception:
            return None
    return group


def _build_in_group(text: str, group: str, build: int) -> bool:
    """True iff `steam_version: <build>` appears inside SafeModeHashes[<group>].

    Scans from the `  <group>:` header (2-space indent) to the next 2-space
    `  <digits>:` group header, a dedent to a top-level key, or EOF. Dependency-
    free — Decky's bundled Python has no YAML lib."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^  {re.escape(group)}:\s*$", line):
            start = i + 1
            break
    if start is None:
        return False
    for line in lines[start:]:
        if re.match(r"^  \d+:\s*$", line):     # next group header ends the block
            break
        if line and not line[0].isspace():     # dedent to a top-level key ends it
            break
        if re.search(rf"steam_version:\s*{build}\b", line):
            return True
    return False


def _supports_build(text: str | None, group: str | None, build: int | None) -> bool | None:
    """Would the LATEST release hook Steam build `build`? None when unknown.

    Checks `build` against the RELEASE's group (`group`) in `text`. Falls back to
    a whole-file scan when the release exposes no version.txt (`group` is None) —
    equivalent while a single group exists."""
    if build is None or text is None:
        return None
    # A pre-schema file has no steam_version anywhere -> unknown, don't false-block.
    if "steam_version" not in text:
        return None
    if group is None:
        return re.search(rf"steam_version:\s*{build}\b", text) is not None
    return _build_in_group(text, group, build)


async def lumalinux_supports_build(build: int | None) -> bool | None:
    """Whether the LATEST lumalinux release would hook Steam build `build`.

    "Latest release" — NOT main: reads the release's compiled SafeMode group
    (latest_release_group()) and checks `build` under THAT group in res/updates.yaml,
    ignoring any newer group main may carry ahead of a release. None on ambiguity."""
    return _supports_build(await _lumalinux_updates_text(), await latest_release_group(), build)


async def check_headcrab_compat() -> dict:
    """Return whether the current Steam build matches Headcrab's pinned target,
    and whether the LATEST lumalinux release is ready for both the pinned target
    (Steam-update gate) and the build the user is on now (lumalinux-update gate)."""
    build = current_steam_build()
    target = await headcrab_target()
    # Fetch the two inputs once, then answer both questions against them.
    text = await _lumalinux_updates_text()
    group = await latest_release_group()
    return {
        "success": True,
        "current_build": build,
        "target": target,
        "compatible": (
            build is not None
            and target is not None
            and build == target
        ),
        # Steam-update gate: is the LATEST release ready for the pinned target?
        # Callers require True (not merely "not False") before offering to move
        # Steam up to the pin. None = unknown -> don't hard-block (prior behaviour).
        "lumalinux_ready": _supports_build(text, group, target),
        # lumalinux-update gate: would the latest release still hook the build the
        # user is on now? Callers suppress the lumalinux update offer only on a
        # positive False (latest dropped this build's pattern-set), never on None.
        "current_build_supported_by_latest": _supports_build(text, group, build),
    }

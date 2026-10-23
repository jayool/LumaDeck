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

import asyncio
import glob
import os
import re

from feed_cache import fresh
from http_client import ensure_http_client
from paths import find_steam_root, real_home, steam_client_arch

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


_HEADCRAB_URL = "https://raw.githubusercontent.com/Deadboy666/h3adcr-b/main/headcrab.sh"
_CACHE_DIR = os.path.join(real_home(), ".cache", "lumadeck")
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


async def headcrab_target(force: bool = False) -> int | None:
    """Fetch the current Headcrab-pinned client version from upstream.

    Live read of `HeadcrabCompatibleClientVer` in Deadboy666/h3adcr-b's
    main branch via LumaDeck's shared HTTP client (handles SSL/CA bundle
    on the PyInstaller-bundled Python that Decky ships). Cached on disk
    after a successful fetch: a copy younger than feed_cache.FEED_TTL is
    served without a fetch unless `force`, and any copy keeps the check
    working offline. Fails closed (returns None) if neither network nor
    cache yields a value.
    """
    if not force and fresh(_CACHE_FILE):
        cached = _load_cache()
        if cached is not None:
            return cached
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


def _looks_like_feed(text: str) -> bool:
    """Is this actually res/updates.yaml, or a 200 carrying something else?

    An HTTP 200 says the transfer worked, not that the file arrived — GitHub has
    served lumalinux's C++ side an unrelated body under a 200, which is what
    src/update.cpp's looksLikeFeed() guards against; this is the same guard on the
    Python side, and the two must agree on what counts as the feed.

    Anchored to the start of a line on purpose: res/updates.yaml opens with a
    header comment that itself contains the word `SafeModeHashes`, so a bare
    substring test would accept an error page that merely quoted it.
    """
    return any(line.startswith("SafeModeHashes:") for line in text.splitlines())


async def _lumalinux_updates_text(force: bool = False) -> str | None:
    """Fetch lumalinux's res/updates.yaml (main), cached to disk. None if
    unreachable and no cache. main is the right source for the per-group BUILD
    LISTS (hashes append live, no release needed); the group POINTER comes from
    the release instead — see latest_release_group(). A cached copy younger
    than feed_cache.FEED_TTL is served without a fetch unless `force`."""
    text = None
    if not force and fresh(_LL_CACHE_FILE):
        try:
            with open(_LL_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = f.read()
            if _looks_like_feed(cached):
                return cached
        except Exception:
            pass
    try:
        client = await ensure_http_client(context="headcrab_compat")
        resp = await client.get(_LUMALINUX_UPDATES_URL, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200 and _looks_like_feed(resp.text):
            text = resp.text
            try:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                with open(_LL_CACHE_FILE, "w", encoding="utf-8") as f:
                    f.write(text)
            except Exception as exc:
                logger.warning(f"headcrab_compat: failed to cache lumalinux updates: {exc}")
        elif resp.status_code == 200:
            logger.info(
                f"headcrab_compat: lumalinux updates returned 200 but the body is "
                f"not the feed ({len(resp.text)} bytes), trying cache"
            )
        else:
            logger.info(f"headcrab_compat: HTTP {resp.status_code} for lumalinux updates, trying cache")
    except Exception as exc:
        logger.info(f"headcrab_compat: lumalinux updates fetch failed ({exc}), trying cache")

    if text is None:
        try:
            with open(_LL_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = f.read()
        except Exception:
            return None
        # A cache written before the guard above existed can hold a 200-with-garbage
        # body; re-check rather than trust its provenance.
        if not _looks_like_feed(cached):
            logger.info("headcrab_compat: cached lumalinux updates is not the feed, discarding")
            return None
        text = cached
    return text


async def latest_release_group(force: bool = False) -> str | None:
    """The SafeMode group-id (res/version.txt value) compiled into the LATEST
    published lumalinux release .so, read from its release asset.

    This is the authority for "which SafeModeHashes group does the downloadable
    binary actually hook?" — the .so trusts only its compile-time group. Cached to
    disk. Returns None when unreachable + no cache, OR when the release predates
    the version.txt asset (older releases); callers then fall back to a whole-file
    scan (safe while a single group exists). A cached copy younger than
    feed_cache.FEED_TTL is served without a fetch unless `force`."""
    group = None
    if not force and fresh(_REL_GROUP_CACHE_FILE):
        try:
            with open(_REL_GROUP_CACHE_FILE, "r", encoding="utf-8") as f:
                cand = f.read().strip()
            if re.fullmatch(r"\d+", cand):
                return cand
        except Exception:
            pass
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


# One whitelisted hash = the `# ...` annotation lines above it (steam_version,
# caps, arch, free notes) + its `- <sha256>` line. Since 2026-10-23 the file also
# lists the 64-bit (steamrt64) client's hashes, marked `# arch: steamrt64`: same
# steam_version as the 32-bit hash of that build (one manifest, two packages),
# different file. Every scan below therefore filters by architecture: an entry
# without an arch mark is the ubuntu12_32 client's. lumalinux's own runtime
# ignores the mark (each .so looks its own hash up); downgrade.sh's
# hash_for_build applies the same rule — keep the three in step.
_HASH_LINE_RE = re.compile(r"^\s*-\s*([0-9a-f]{64})\b")
_STEAM_VERSION_RE = re.compile(r"^\s*#\s*steam_version:\s*(\d+)\b")
_ARCH_RE = re.compile(r"^\s*#\s*arch:\s*(\S+)")
_DEFAULT_ARCH = "ubuntu12_32"


def _whitelist_entries(text: str):
    """Yield (group, steam_versions, arch, sha) per hash line of SafeModeHashes.
    `group` is the `  <digits>:` header the hash sits under (None before any);
    `steam_versions` every `# steam_version:` annotated above it since the last
    hash; `arch` the `# arch:` mark or ubuntu12_32. Dependency-free — Decky's
    bundled Python has no YAML lib."""
    group, versions, arch = None, [], _DEFAULT_ARCH
    for line in text.splitlines():
        g = re.match(r"^  (\d+):\s*$", line)
        if g:
            group, versions, arch = g.group(1), [], _DEFAULT_ARCH
            continue
        if line and not line[0].isspace():     # dedent to a top-level key
            group, versions, arch = None, [], _DEFAULT_ARCH
            continue
        m = _STEAM_VERSION_RE.match(line)
        if m:
            versions.append(int(m.group(1)))
            continue
        a = _ARCH_RE.match(line)
        if a:
            arch = a.group(1)
            continue
        h = _HASH_LINE_RE.match(line)
        if h:
            yield group, versions, arch, h.group(1)
            versions, arch = [], _DEFAULT_ARCH


def _build_in_group(text: str, group: str, build: int, arch: str = _DEFAULT_ARCH) -> bool:
    """True iff a `# steam_version: <build>` entry of client `arch` sits inside
    SafeModeHashes[<group>]."""
    return any(g == group and build in vs and a == arch
               for g, vs, a, _sha in _whitelist_entries(text))


def _supports_build(text: str | None, group: str | None, build: int | None,
                    arch: str = _DEFAULT_ARCH) -> bool | None:
    """Would the LATEST release hook Steam build `build`? None when unknown.

    Checks `build` against the RELEASE's group (`group`) in `text`. Falls back to a
    whole-file scan when the release exposes no version.txt (`group` is None).

    A `# steam_version:` annotation is OPTIONAL metadata (a whitelisted hash may
    carry none), so an un-annotated build is UNKNOWN (None) — NOT unsupported. Only
    a build that IS annotated somewhere but NOT in the release's group is a positive
    False (a re-derived pattern-set dropped it). Without this, users on a
    whitelisted-but-un-annotated build (e.g. an older pin) would have their update
    offer wrongly suppressed."""
    if build is None or text is None:
        return None
    # A pre-schema file has no steam_version anywhere -> unknown, don't false-block.
    if "steam_version" not in text:
        return None
    # Un-annotated build (for this client arch) -> unknown (fail-open), never a
    # false "unsupported".
    if not any(build in vs and a == arch for _g, vs, a, _sha in _whitelist_entries(text)):
        return None
    if group is None:
        return True   # annotated + no release group to scope by -> supported (fallback)
    return _build_in_group(text, group, build, arch)


def _hash_for_build(text: str | None, build: int | None, arch: str = _DEFAULT_ARCH) -> str | None:
    """The steamclient.so SHA-256 res/updates.yaml records for `build` on client
    `arch`: the first hash whose annotations include `# steam_version: <build>`
    (a hash can carry several: Valve relabels builds without changing the file,
    1788291500 and 1788652215 are one binary) and whose arch is `arch`. The
    64-bit entry of the same build is a different file, never returned for the
    ubuntu12_32 tree. None when unknown. Same rule as downgrade.sh's
    hash_for_build — keep the two in step."""
    if text is None or build is None:
        return None
    for _g, vs, a, sha in _whitelist_entries(text):
        if build in vs and a == arch:
            return sha
    return None


def builds_share_binary(text: str | None, a: int | None, b: int | None) -> bool | None:
    """Do builds `a` and `b` name the same steamclient.so per res/updates.yaml?
    True / False when both hashes are known, None when either is not."""
    ha, hb = _hash_for_build(text, a), _hash_for_build(text, b)
    if ha is None or hb is None:
        return None
    return ha == hb


async def lumalinux_supports_build(build: int | None, arch: str = _DEFAULT_ARCH) -> bool | None:
    """Whether the LATEST lumalinux release would hook Steam build `build` on
    client `arch` (ubuntu12_32 unless the caller asks about the 64-bit one).

    "Latest release" — NOT main: reads the release's compiled SafeMode group
    (latest_release_group()) and checks `build` under THAT group in res/updates.yaml,
    ignoring any newer group main may carry ahead of a release. None on ambiguity."""
    return _supports_build(await _lumalinux_updates_text(), await latest_release_group(), build, arch)


async def check_headcrab_compat(force: bool = False) -> dict:
    """Return whether the current Steam build matches Headcrab's pinned target,
    and whether the LATEST lumalinux release is ready for both the pinned target
    (Steam-update gate) and the build the user is on now (lumalinux-update gate).
    `force` skips the feed caches (manual refresh)."""
    build = current_steam_build()
    # The three inputs are independent fetches: run them at once (the QAM waits
    # on this), then answer both questions against them.
    target, text, group = await asyncio.gather(
        headcrab_target(force=force),
        _lumalinux_updates_text(force=force),
        latest_release_group(force=force),
    )
    # Valve relabels a build without changing steamclient.so (1788291500 became
    # 1788652215 on 2026-09-05), and headcrab's pinned MANIFEST can keep the old
    # label while headcrab.sh carries the new one. A Deck downgrade.sh just put on
    # that manifest then reads 1788291500 against a target of 1788652215: not
    # "compatible", "behind the pin", and steam_freeze would lift the pin at the
    # next setup.sh. When the whitelist says both labels are ONE binary, treat
    # the pin as reached: report the current build as the target.
    same_binary = builds_share_binary(text, build, target)
    if same_binary and build is not None:
        logger.info(
            f"headcrab_compat: target {target} and installed {build} are the same "
            f"steamclient.so — treating the pin as reached"
        )
        target = build
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
        # "The build the user is on now" runs on whichever client boots (the
        # 32-bit one, or steamrt64 on the beta / RT3 opt-in), so the whitelist is
        # read for that client's entries.
        "current_build_supported_by_latest": _supports_build(text, group, build, steam_client_arch()),
    }

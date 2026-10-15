"""Unified component status — one shape for SLSsteam, lumalinux, CloudRedirect.

Aggregates the existing per-component health (paths.read_*_health) and update
checks into a single payload the UI consumes in one call, instead of 8 separate
fetches. See the "Component model" spec in DESIGN_UI.md.

ADDITIVE: this wraps existing detection functions, it does not replace them. The
frontend swap (and deleting the old per-component fetches/banners) is a later
step — this module can ship without changing anything visible.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from update_checks import get_latest_release_with_asset, has_update, has_update_from

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# --- SLSsteam update ---------------------------------------------------------

async def check_slssteam_update(force: bool = False) -> dict:
    """SLSsteam update = a newer release at AceSLS/SLSsteam — the repo setup.sh
    installs `latest` from.

    Nothing SLSsteam puts on disk states its version, so the installed side comes
    from slssteam_version.resolve_installed_version(): the tag setup.sh recorded
    at install, or — for installs predating that — a proven lower bound derived
    from the binary. Both are release tags (build timestamps like
    '20260820085507'), which has_update's compare orders correctly as-is, bigger
    being newer. An unknown version yields no update, the safe default.

    force=True bypasses the release cache for a manual refresh."""
    from slssteam_version import SOURCE_UNKNOWN, resolve_installed_version
    installed, source = await resolve_installed_version()
    result = await has_update("AceSLS", "SLSsteam", installed, force=force)
    # Tells "no update" apart from "no idea" in the log — the two are the same
    # answer to the user, and only this line distinguishes them in a bug report.
    result["version_source"] = source
    if source == SOURCE_UNKNOWN:
        result["has_update"] = False
    return result


# --- CloudRedirect update ----------------------------------------------------

# CloudRedirect ships its Linux build as a `cloud_redirect.so` asset on its own
# semver releases (alongside the Windows .exe/.dll and the flatpak). That is the
# channel we track. Two things about it are easy to get wrong:
#
#  * Not every release has a Linux build. v2.1.9, v2.2.4, v2.5.3, v2.6.1 and
#    v2.6.2 are Windows-only, so /releases/latest regularly names a version that
#    does not exist for Linux — hence get_latest_release_with_asset().
#  * Selectively11/h3adcr-b's `linux-test` tag mirrors the same .so (it is what
#    headcrab's crinstall() wgets, and what LumaDeck used to hash). It is a
#    rolling tag on a fork whose script has been frozen since May: the file is
#    replaced in place, carries no version, and has lagged the real releases. It
#    is not a version channel and is not used here.
_CR_SO_ASSET = "cloud_redirect.so"

# The .so states its own version. This is deliberate upstream, not incidental log
# text: CloudRedirect's CMakeLists reads <ReleaseVersion> out of Version.props,
# appends the git sha, compiles it in as CR_VERSION_STRING, and exports
# CR_GetVersion() (src/platform/linux/init.cpp). It reaches the binary's string
# table as e.g. "version=2.6.5+870afdb-dirty", so it can be read without running
# anything.
#
# We read it rather than calling CR_GetVersion because the Decky backend is
# 64-bit Python and the .so is 32-bit (it has to be, it is loaded into Steam), so
# it cannot be dlopen'd from here. cloud_redirect_cli exists for exactly that
# reason but has no `version` command.
#
# Only the X.Y.Z is captured; everything after it is build metadata that varies
# between rebuilds of the same version ("+870afdb-dirty" on recent builds,
# "+unknown" on ones built without git) and must not affect the compare. The
# suffix can also precede the "+" ("2.5.0-Final+unknown"), which this ignores
# too. Verified present on every release that ships a Linux .so, from the first
# one (v2.0.3) to v2.6.5.
_CR_VERSION_RE = re.compile(rb"version=(\d+\.\d+\.\d+)")

# The .so is ~2 MB and the components panel re-checks on every mount; memoise on
# (path, mtime, size) so a reinstall re-reads and repeat calls do not.
_cr_version_cache: dict = {}


def read_cloudredirect_version(so_path: str) -> Optional[str]:
    """The version compiled into a cloud_redirect.so, or None."""
    try:
        stat = os.stat(so_path)
    except OSError:
        return None
    key = (so_path, stat.st_mtime_ns, stat.st_size)
    if key in _cr_version_cache:
        return _cr_version_cache[key]
    try:
        with open(so_path, "rb") as fh:
            blob = fh.read()
    except Exception as exc:
        logger.info(f"components: cannot read {so_path} ({exc})")
        return None
    match = _CR_VERSION_RE.search(blob)
    result = match.group(1).decode("ascii") if match else None
    if result is None:
        logger.info(f"components: no version string in {so_path}")
    _cr_version_cache[key] = result
    return result


# --- lumalinux version from disk -------------------------------------------

# liblumalinux.so embeds its version twice: the gmrc User-Agent
# ("lumalinux/v0.22.1") and the preinit log line ("lumalinux v0.22.1 preinit").
# Either anchors the compare. Reading the file means the update shows whether
# or not Steam has loaded lumalinux; status.json (what the .so writes once it
# is loaded) stays the health source and the fallback for a build without the
# string.
_LL_VERSION_RE = re.compile(rb"lumalinux[/ ]v?(\d+\.\d+\.\d+)")
_ll_version_cache: dict = {}


def read_lumalinux_version(so_path: str) -> Optional[str]:
    """The version compiled into a liblumalinux.so, or None."""
    try:
        stat = os.stat(so_path)
    except OSError:
        return None
    key = (so_path, stat.st_mtime_ns, stat.st_size)
    if key in _ll_version_cache:
        return _ll_version_cache[key]
    try:
        with open(so_path, "rb") as fh:
            blob = fh.read()
    except Exception as exc:
        logger.info(f"components: cannot read {so_path} ({exc})")
        return None
    match = _LL_VERSION_RE.search(blob)
    result = match.group(1).decode("ascii") if match else None
    if result is None:
        logger.info(f"components: no version string in {so_path}")
    _ll_version_cache[key] = result
    return result


def installed_lumalinux_version(health_version: Optional[str] = None) -> Optional[str]:
    """Disk first, status.json second."""
    from paths import get_lumalinux_so_path
    so_path = get_lumalinux_so_path()
    from_disk = read_lumalinux_version(so_path) if so_path else None
    return from_disk or health_version


async def check_lumalinux_update(health_version: Optional[str] = None, force: bool = False) -> dict:
    """lumalinux update = a newer release than the .so on disk."""
    return await has_update("jayool", "lumalinux", installed_lumalinux_version(health_version), force=force)


async def check_cloudredirect_update(force: bool = False) -> dict:
    """CloudRedirect update = a newer Linux release than the .so on disk.

    Both sides are semver, so this is the same comparison lumalinux gets: the
    version compiled into the installed .so against the tag of the newest release
    that ships one.

    This replaced a plain content-hash diff against the rolling `linux-test`
    asset. That fired on any byte difference, so every upstream rebuild of an
    unchanged version announced an update that installing could not clear.
    Unknown on either side means no update, the safe default."""
    from paths import get_cloudredirect_so_path
    local_path = get_cloudredirect_so_path()
    installed = read_cloudredirect_version(local_path) if local_path else None
    latest = await get_latest_release_with_asset(
        "Selectively11", "CloudRedirect", _CR_SO_ASSET, force=force)
    return await has_update_from(installed, latest)


# --- The aggregate -----------------------------------------------------------

def _component(id_: str, name: str, installed: bool, health: dict, update: dict,
               supports_current_build=None) -> dict:
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
            # Would the LATEST release of this component hook the Steam client
            # installed right now? True/False/None(unknown). With the component
            # not_supported, True means "Update fixes it" and the UI offers
            # Update instead of Fix in Desktop (2026-10-14: SLSsteam
            # 20261014151919 fixed 1791918634; downgrading was the wrong fix).
            "supports_current_build": supports_current_build,
        },
    }


def _slssteam_health_from_feed(health: dict, sls_text, cur_hash) -> dict:
    """not_loaded / not_injected -> not_supported when the installed SLSsteam
    release's SafeModeHashes group lacks the client on disk. Any other state,
    an unknown installed tag, a missing feed or an unreadable client hash
    leave `health` as is."""
    if health.get("state") not in ("not_loaded", "not_injected"):
        return health
    from slssteam_version import read_recorded_version
    from steam_update_gate import slssteam_supports
    tag = read_recorded_version()
    if not tag or slssteam_supports(sls_text, tag, cur_hash) is not False:
        return health
    logger.info("components: SLSsteam %s does not list client %s; not_supported",
                tag, (cur_hash or "")[:8])
    return {"state": "not_supported", "cause": "version", "action": "downgrade"}


def _sls_release_cache_stale(sls_text) -> bool:
    """True when SLSsteam's feed names a newer pattern group than the release
    our 6-hour cache knows about: Ace just shipped, the cache hasn't noticed.
    Today's case: the gate said "update SLSsteam first" (fresh feed) while the
    Update row stayed hidden (stale cache). One release fetch fixes it."""
    from steam_update_gate import slssteam_latest_group
    from update_checks import _read_cache_stale_ok
    newest = slssteam_latest_group(sls_text)
    if not newest:
        return False
    cached = _read_cache_stale_ok("AceSLS", "SLSsteam") or {}
    known = cached.get("tag_normalised") or cached.get("tag")
    return bool(known) and str(known) < newest


async def get_components_status(force: bool = False) -> dict:
    """One uniform payload for the system-status surface — per-component health +
    update, plus the headcrab compat gate and the plugin. Wraps existing
    detection; nothing here re-implements it. force=True bypasses the update
    caches (lumalinux release + CloudRedirect hash) for a manual refresh."""
    from paths import (
        read_slssteam_health,
        read_lumalinux_health,
        read_cloudredirect_health,
        read_crash_guard,
    )
    from headcrab_compat import check_headcrab_compat
    from steam_freeze import read_freeze
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
    # The launcher's crash guard (paths.read_crash_guard). While it is latched
    # every hook component reads not_loaded and a plain restart cannot help, so
    # the UI shows "Recovery mode" + Retry instead of "Restart needed". Stack-wide
    # like headcrab, not per component. Inactive on any failure (safe default).
    guard = _safe_sync(read_crash_guard, {"active": False, "fails": 0, "since": None, "client_changed": False})
    # The Steam-update pin (steam.cfg). `mine` = written by our downgrade.sh
    # (signed `# lumalinux`), which is the only pin the UI offers to lift in
    # place: "Let Steam update" strips it and restarts, no Desktop needed.
    freeze = _safe_sync(read_freeze, {"frozen": False, "mine": False})
    # Only while OUR pin is on does "is it safe to let Steam update?" matter
    # (steam_update_gate: Valve's stable manifest + lumalinux's and SLSsteam's
    # whitelists). Advice for the button's text, never a lock.
    gate = None
    if freeze.get("frozen") and freeze.get("mine"):
        from steam_update_gate import steam_update_gate
        gate = await _safe(steam_update_gate(force=force), {"state": "unknown", "blocker": None})

    # SLSsteam has no readable version on disk of its own (config.yaml is settings
    # only; the version is a build timestamp embedded inside the .so). setup.sh
    # records the release tag it installed into `.slssteam.version`, so we CAN now
    # surface updates — needed since headcrab is decoupled and no longer carries
    # SLSsteam updates along. Without a recorded version the check reports no
    # update (safe default), so this is inert on pre-this-feature installs.
    # When a component's health is FORCED via the Dev tab, its version is
    # synthetic ("9.9.9"), so a real update check would compare against a fake
    # value and spuriously report "update available". Skip the check for any
    # Dev-forced component (preview only; no effect on a normal install).
    import dev
    sls_forced = dev.get("slssteam_health") is not None
    ll_forced = dev.get("lumalinux_health") is not None
    cr_forced = dev.get("cloudredirect_health") is not None

    # SLSsteam's own feed, fetched fresh (cache fallback): decides whether the
    # latest SLSsteam hooks the client on disk, and whether the release cache
    # is behind Ace's newest pattern group.
    from steam_update_gate import current_client_hash, slssteam_latest_supports, slssteam_updates_text
    sls_text = await _safe(slssteam_updates_text(), None)
    cur_hash = _safe_sync(current_client_hash, None)
    sls_supports_current = slssteam_latest_supports(sls_text, cur_hash)
    # SLSsteam not mapped in Steam reads not_loaded / not_injected from the
    # process alone. When the INSTALLED release's own list says it does not
    # hook the client on disk, that is the real cause (a crash-guarded or
    # aborted load), and the fix is the not_supported row (Update / Let Steam
    # update / Wait / Fix in Desktop), not a restart. Loaded + log still wins;
    # a Dev-forced state is left alone; no feed or no record -> unchanged.
    if not sls_forced:
        sls_health = _safe_sync(
            lambda: _slssteam_health_from_feed(sls_health, sls_text, cur_hash), sls_health)
    sls_force = force or _safe_sync(lambda: _sls_release_cache_stale(sls_text), False)

    sls_update = no_update if sls_forced else await _safe(
        check_slssteam_update(force=sls_force), no_update)
    ll_update = no_update if ll_forced else await _safe(
        check_lumalinux_update(ll_health.get("version"), force=force), no_update)
    cr_update = no_update if cr_forced else await _safe(
        check_cloudredirect_update(force=force), no_update)

    headcrab = await _safe(check_headcrab_compat(), {"compatible": None, "target": None, "current_build": None})
    # Would Fix in Desktop help? Only asked while something is not_supported
    # (the one state that offers it). possible False -> the QAM shows the Wait
    # row instead of a button that would be refused.
    downgrade = {"target": None, "possible": None, "error": None}
    if any(h.get("state") == "not_supported" for h in (sls_health, ll_health, cr_health)):
        from desktop_handoff import downgrade_check
        downgrade = await _safe(downgrade_check(force=force), downgrade)
    plugin = await _safe(check_plugin_update(), {"installed": None, "latest": None, "has_update": False})

    # `installed` is derived from the (dev-aware) health state, NOT a raw disk
    # check. read_*_health() returns "not_installed" exactly when the .so is
    # absent, so this equals check_*_installed() in production — but it also
    # lets the Dev health overrides drive the installed flag, so forcing a
    # state (not_supported, not_loaded, ...) surfaces the matching SystemStatus
    # row instead of being filtered out by a disk check the override can't touch.
    def _installed(h: dict) -> bool:
        return h.get("state") not in (None, "not_installed")

    components = [
        _component("slssteam", "SLSsteam", _installed(sls_health), sls_health, sls_update,
                   sls_supports_current),
        _component("cloudredirect", "CloudRedirect", _installed(cr_health), cr_health, cr_update),
        _component("lumalinux", "lumalinux", _installed(ll_health), ll_health, ll_update,
                   headcrab.get("current_build_supported_by_latest")),
    ]

    # Dev preview: force the Quick Install onboarding on/off without touching
    # real component files. "show"/"hide"/None — the frontend gate reads it.
    quick_install_override = dev.get("quick_install")

    return {
        "success": True,
        "components": components,
        "quickInstall": quick_install_override,
        "headcrab": {
            "compatible": headcrab.get("compatible"),
            "target": headcrab.get("target"),
            "current": headcrab.get("current_build"),
            # v0.16: is lumalinux's pattern set published for the pinned target?
            # The frontend gates the Steam-update / desktop-handoff offer on this
            # so a user never aligns Steam ahead of lumalinux. None = unknown
            # (don't hard-block; fall back to prior behaviour).
            "lumalinux_ready": headcrab.get("lumalinux_ready"),
            # Would the LATEST lumalinux release still hook the build the user is
            # on now? The frontend suppresses the lumalinux update offer only on a
            # positive False (a new release re-derived patterns and dropped this
            # build) so updating never breaks a working install. None = unknown
            # (don't suppress).
            "current_build_supported_by_latest": headcrab.get("current_build_supported_by_latest"),
        },
        "plugin": {
            "installed": plugin.get("installed"),
            "latest": plugin.get("latest"),
            "available": bool(plugin.get("has_update")),
        },
        "freeze": {
            "frozen": bool(freeze.get("frozen")),
            "mine": bool(freeze.get("mine")),
            # Our pin holds a client the latest SLSsteam no longer hooks: any
            # install would break Steam (plan_setup refuses it), so Components
            # hides Reinstall and the held row says what to do instead.
            "install_blocked": bool(freeze.get("frozen") and freeze.get("mine")
                                    and sls_supports_current is False),
            "gate": None if gate is None else {
                "state": gate.get("state"),
                "blocker": gate.get("blocker"),
                "stable_build": gate.get("stable_build"),
                "slssteam_required": gate.get("slssteam_required"),
            },
        },
        "downgrade": {
            "target": downgrade.get("target"),
            "possible": downgrade.get("possible"),
        },
        "guard": {
            "active": bool(guard.get("active")),
            "fails": int(guard.get("fails") or 0),
            "since": guard.get("since"),
            "client_changed": bool(guard.get("client_changed")),
        },
    }

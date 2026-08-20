"""Which SLSsteam release is installed on this device.

SLSsteam publishes proper releases (tagged with a build timestamp, e.g.
`20260820085507`), but nothing that lands on disk says which one you have:

  * the release archive ships `SLSsteam.so`, `library-inject.so`, `setup.sh`,
    `docs/LICENSE`, `res/config.yaml` and two .NET tools — no `res/version.txt`;
  * the `.so` exports no version symbol, logs no version banner, and its API
    (`/tmp/SLSsteam.API`) has no `version` command;
  * `config.yaml` has no version field.

So "which release is installed" has to be **remembered at install time**, the
way dpkg/rpm/pacman do it: lumalinux's setup.sh records the tag it resolved into
`~/.config/SLSsteam/.slssteam.version` (the "recorded" source below).

That leaves one gap: installs predating that change have no record, and would
report no version forever — which `has_update()` cannot distinguish from "you
are up to date", so the user would silently never see an SLSsteam update again.
`derive_version_floor()` closes it. See its docstring for why what it returns is
a proven lower bound rather than a guess.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from http_client import ensure_http_client
from paths import find_slssteam_root, get_slssteam_config_dir

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# Where the installed version came from. Callers log this so a "LumaDeck never
# offers me SLSsteam updates" report can be diagnosed from the backend log
# instead of guessed at.
SOURCE_RECORDED = "recorded"   # setup.sh wrote it: the exact release tag
SOURCE_DERIVED = "derived"     # deduced from the binary: a lower bound
SOURCE_UNKNOWN = "unknown"     # neither worked; caller must not report an update

# AceSLS tags every release with a build timestamp, YYYYMMDDHHMMSS. Anything else
# — the stale rolling `update` tag, a truncated file, an error page saved by a
# failed curl — is rejected rather than fed to the version compare, which would
# turn it into (0, 0, 0) and silently mis-order it.
_TAG_RE = re.compile(r"^\d{14}$")

_VERSION_FILE = ".slssteam.version"

# SLSsteam's SafeMode feed: a map of VERSION -> the steamclient.so hashes that
# VERSION is certified against. We only want its KEYS, which are exactly the set
# of VERSION values that have ever shipped. SLSsteam caches this beside its
# config (src/update.cpp), so we prefer the local copy — but only reads it when
# SafeMode or WarnHashMissmatch is on (upstream made the download conditional in
# 20260728212859), so the remote is not a rare fallback. Same URL SLSsteam uses,
# minus its jsDelivr mirror.
_UPDATES_YAML_CACHE = ".updates.yaml"
_UPDATES_YAML_URL = (
    "https://raw.githubusercontent.com/AceSLS/SLSsteam/refs/heads/main/res/updates.yaml"
)
_FETCH_TIMEOUT = 20.0

# Deriving means fetching updates.yaml and reading a ~22 MB binary, and the
# components panel re-checks on every mount. Memoise the whole derivation on the
# binary's (path, mtime, size) so a reinstall re-derives but repeat calls in the
# same session cost nothing. Only reached when there is no recorded tag.
_derive_cache: dict = {}


# --- the recorded version (the normal path) ---------------------------------

def read_recorded_version() -> Optional[str]:
    """The release tag setup.sh recorded at install time, or None.

    None means "no usable record" — either the file is absent (an install from
    before setup.sh recorded it) or its contents are not a release tag.
    """
    path = os.path.join(get_slssteam_config_dir(), _VERSION_FILE)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = fh.read().strip()
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.info(f"slssteam_version: cannot read {path} ({exc})")
        return None
    if not _TAG_RE.match(value):
        if value:
            logger.warning(
                f"slssteam_version: ignoring malformed {_VERSION_FILE} "
                f"({value[:32]!r}); expected a 14-digit release tag"
            )
        return None
    return value


# --- the derived floor (the fallback for pre-existing installs) --------------

def candidate_versions(yaml_text: str) -> List[int]:
    """The VERSION values that have ever shipped, newest first.

    Parsed with a regex rather than a YAML library: the Decky backend has no
    pyyaml, and all we need are the top-level keys under SafeModeHashes.
    """
    found = {int(m) for m in re.findall(r"^\s{2}(\d{14}):", yaml_text, re.M)}
    return sorted(found, reverse=True)


def scan_so_version(so_path: str, candidates: List[int]) -> Optional[int]:
    """Identify which candidate VERSION is compiled into `so_path`.

    SLSsteam declares `constexpr uint64_t VERSION = 20260815201341;`, so the
    compiler stores the NUMBER (8 bytes, little-endian on x86), not the text —
    which is why `strings` finds nothing. The value cannot be read out of a
    22 MB binary, but it can be identified, because the set of possible values
    is public (the updates.yaml keys). We test each one.

    A 14-digit value is ~2e13, so a chance collision is not a practical concern;
    still, only an unambiguous single match is accepted. Zero matches (a build
    older than the first SafeMode VERSION, or a layout change) and two or more
    both return None so the caller reports nothing rather than something wrong.
    """
    try:
        with open(so_path, "rb") as fh:
            blob = fh.read()
    except Exception as exc:
        logger.info(f"slssteam_version: cannot read {so_path} ({exc})")
        return None

    hits = [v for v in candidates if v.to_bytes(8, "little") in blob]
    if len(hits) > 1:
        logger.warning(f"slssteam_version: ambiguous VERSION scan, {len(hits)} matches")
    return hits[0] if len(hits) == 1 else None


async def _updates_yaml_text() -> Optional[str]:
    """SLSsteam's own cached copy if present, else the upstream file."""
    local = os.path.join(get_slssteam_config_dir(), _UPDATES_YAML_CACHE)
    try:
        with open(local, "r", encoding="utf-8") as fh:
            text = fh.read()
        if "SafeModeHashes" in text:
            return text
    except Exception:
        pass
    try:
        client = await ensure_http_client(context="slssteam_version")
        resp = await client.get(_UPDATES_YAML_URL, timeout=_FETCH_TIMEOUT)
        if resp.status_code == 200 and resp.text:
            return resp.text
        logger.info(f"slssteam_version: updates.yaml HTTP {resp.status_code}")
    except Exception as exc:
        logger.info(f"slssteam_version: updates.yaml fetch failed ({exc})")
    return None


async def derive_version_floor() -> Optional[str]:
    """A release tag the installed SLSsteam is guaranteed to be at or above.

    Not an estimate — a deduction:

        the binary carries VERSION = V
          -> it was built at or after the commit that set res/version.txt to V
          -> that commit is tagged V          (every VERSION value is also a tag)
          -> the installed release is V or newer

    So V can only ever UNDERSTATE how new the install is, never overstate it.
    Used to seed a missing record, that asymmetry is the one we want: it can
    never wrongly say "you are up to date" (a silent, permanent miss), only
    wrongly say "an update is available" — at most once, since applying it makes
    setup.sh write the exact tag.

    Blind spot: releases before 20251226083318 shipped no res/version.txt, so
    there is no VERSION in those binaries and this returns None.
    """
    so_path = os.path.join(find_slssteam_root(), "SLSsteam.so")
    try:
        stat = os.stat(so_path)
    except OSError:
        return None
    key = (so_path, stat.st_mtime_ns, stat.st_size)
    if key in _derive_cache:
        return _derive_cache[key]

    text = await _updates_yaml_text()
    if not text:
        return None
    candidates = candidate_versions(text)
    if not candidates:
        logger.info("slssteam_version: no VERSION keys in updates.yaml")
        return None
    found = scan_so_version(so_path, candidates)
    result = str(found) if found is not None else None
    # A failed FETCH is not cached (above): it is transient and worth retrying.
    # A completed scan is, whatever its outcome — the answer only changes when
    # the binary does, and the key covers that.
    _derive_cache[key] = result
    return result


# --- what callers use --------------------------------------------------------

async def resolve_installed_version() -> Tuple[Optional[str], str]:
    """(version, source) for the installed SLSsteam.

    The recorded tag wins whenever it exists; the derived floor only fills in for
    installs that predate setup.sh recording it. A None version means the caller
    must report no update — "we don't know" and "nothing new" are the same answer
    to the user, so the source is logged to tell them apart afterwards.
    """
    recorded = read_recorded_version()
    if recorded:
        return recorded, SOURCE_RECORDED

    derived = await derive_version_floor()
    if derived:
        logger.info(
            f"slssteam_version: no {_VERSION_FILE} recorded; using the version "
            f"floor derived from the binary ({derived}). Reinstalling the "
            f"components records the exact release tag."
        )
        return derived, SOURCE_DERIVED

    logger.info(
        f"slssteam_version: no {_VERSION_FILE} recorded and the binary VERSION "
        f"could not be identified — SLSsteam updates cannot be detected until "
        f"the components are reinstalled."
    )
    return None, SOURCE_UNKNOWN

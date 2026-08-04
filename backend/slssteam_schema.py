"""SLSsteam config.yaml schema completion (append-only).

Why this exists
---------------
SLSsteam writes its FULL default config only when the file is ABSENT (its
``createFile()`` is create-if-missing; it never migrates or rewrites an existing
file). It DOES, however, validate on load and toast
``"Issues during config loading encountered! Missing key(s)"`` when the on-disk
config lacks keys the running SLSsteam expects.

So a config that predates newer SLSsteam keys — or one that some tool seeded
partial before SLSsteam's first run — stays incomplete forever and toasts on
every launch. Reinstalling does not fix it (the file exists → SLSsteam won't
rewrite it).

This module reconciles the on-disk config against SLSsteam's current default
key-set by APPENDING any missing top-level keys (with their default block +
comment). It is APPEND-ONLY: it never edits or deletes an existing byte, so it
cannot lose the user's values (AdditionalApps, ManifestIds, flag choices, …) or
corrupt nested structures. Idempotent.

The reference key-set is SLSsteam's own ``src/config_default.hpp`` — fetched live
(so newly-added keys are tracked) with the bundled snapshot below as the offline
fallback. If neither yields a valid reference, completion is a no-op (worst case:
the toast persists; never a partial write).
"""

from __future__ import annotations

import os
import re
from typing import List, Tuple

from paths import get_slssteam_config_path, real_home

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# Raw config_default.hpp URL (the authoritative default SLSsteam compiles in).
_CONFIG_DEFAULT_URL = "https://raw.githubusercontent.com/AceSLS/SLSsteam/master/src/config_default.hpp"
_CACHE_DIR = os.path.join(real_home(), ".cache/lumadeck")
_CACHE_FILE = os.path.join(_CACHE_DIR, "slssteam_config_default.yaml")
_FETCH_TIMEOUT = 8.0

# Bundled fallback: SLSsteam's default config YAML, verbatim from
# src/config_default.hpp (the content of its R"(...)" raw string). Updated when we
# bump supported SLSsteam. Used only when the live fetch is unavailable.
_BUNDLED_YAML = r"""#Example AppIds Config for those not familiar with YAML:
#AppIds:
#  - 440
#  - 730
#Take care of not messing up your spaces! Otherwise it won't work

#Example of DlcData:
#DlcData:
#  AppId:
#    FirstDlcAppId: "Dlc Name"
#    SecondDlcAppId: "Dlc Name"

#Example of DenuvoGames:
#DenuvoGames:
#  SteamId:
#    -  AppId1
#    -  AppId2

#Example of FakeAppIds:
#FakeAppIds:
#  AppId1: FakeAppId1
#  AppId2: FakeAppId2

#Disables Family Share license locking for self and others
DisableFamilyShareLock: yes

#Switches to whitelist instead of the default blacklist
UseWhitelist: no

#List of AppIds to ex-/include. Either specify each DLC you want to in-/exclude individually
#or add the DLC's parent AppId (the Game's one) to allow unlocking all of their child AppIds
AppIds:

#Additional AppIds to inject (Overrides OwnerIds for apps you got shared! This breaks downloads)
#Best to use this only on games NOT in your library.
#AppIds on this list will automatically get added to your AppIds setting aswell, but only for the initial check.
#It will get ignored in exclusion checks for the parent AppId
AdditionalApps:

#Extra Data for Dlcs belonging to a specific AppId. Only needed
#when the App you're playing is hit by Steams 64 DLC limit
DlcData:

#Used to retrieve ProductInfo from Steam servers for some games
AppTokens:

#Fake Steam being offline for specified AppIds. Same format as AppIds
FakeOffline:

#Change AppIds of games to enable networking features
#Use 0 as a key to set for all unowned Apps
#Keeps track of the proper AppIds via game launches, so please do not start multiple FakeAppId enabled games simultaneously
FakeAppIds:

#Override Depot manifest IDs
#Use this to download older game versions or to lock a game to a specific version
ManifestIds:

#Never download these depots
DepotBlacklist:

#Custom ingame statuses. Set AppId to 0 to disable
IdleStatus:
  AppId: 0
  Title: ""

#Override game titles. Only works with owned appIds! For injected appIds use either UnownedStatus or combine them with FakeAppIds
GameTitles:

#Override purchase time stamps
SubscriptionTimestamps:

#Blocks games from unlocking on wrong accounts
DenuvoGames:

#Overrides your SteamId an app sees. Only needed when the automatic SteamId spoofing
#fails (some games do call GetSteamId before they request your ticket)
#Also can be used to workaround locked saves
#Either set to SteamId or to 0 to use the SteamId in the cached AppOwnershipTicket
SteamIdOverride:

#Automatically grab Achievement schemas from Steams CDN which makes them always up to date
#Slows down game's loading page the first time you click them
#If you don't want this set it to 0 and use tools/schema-grabber instead to grab them outside of steam
#to get the achievement schemas. Doing so will revert to the previous behaviour of falling back to
#the offline cache (appcache/stats) when a GetUserStats request fails
MaxSchemaTries: 10

#Automatically disable SLSsteam when steamclient.so does not match a predefined file hash that is known to work
#You should enable this if you're planing to use SLSsteam with Steam Deck's gamemode
SafeMode: no

#Toggles notifications via notify-send
Notifications: yes

#Warn user via notification when steamclient.so hash differs from known safe hash
#Mostly useful for development so I don't accidentally miss an update
WarnHashMissmatch: no

#Notify when SLSsteam is done initializing
NotifyInit: yes

#Enable sending commands to SLSsteam via /tmp/SLSsteam.API
API: no

#Disable cloud saves for unlocked games. Set to "no" if using CloudRedirect or similar.
DisableCloud: yes

#Disable updates for AppIds on AdditionalApps
#Only works for unowned games, since those do not get any depots from CUserAppManager::BuildDepotDependency.
#For owned games use ManifestIds
DisableUpdates: yes

#Changes your Persona's Name clientsidedly
FakeName: ""

#Changes your account's E-Mail clientsided. Leave blank to disable
FakeEmail: ""

#Changes your wallet's balance clientsidedly. 0 to turn off
FakeWalletBalance: 0

#Log levels:
#Once = 0
#Debug = 1
#Info = 2
#NotifyShort = 3
#NotifyLong = 4
#Warn = 5
#None = 6
LogLevel: 2

#Dump all used IClientInterfaceMaps
DumpClientInterfaces: no

#Logs all calls to Steamworks (this makes the logfile huge! Only useful for debugging/analyzing
ExtendedLogging: no"""


# A top-level key line: starts at column 0 (no indent), not a comment, `name:`.
_TOP_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:")


def _is_top_key(line: str) -> bool:
    return bool(line) and not line[0].isspace() and not line.lstrip().startswith("#") \
        and _TOP_KEY.match(line) is not None


def _top_key_name(line: str):
    m = _TOP_KEY.match(line)
    return m.group(1) if m else None


def present_top_level_keys(content: str) -> set:
    """Names of keys present as a top-level (column-0, non-comment) line."""
    return {_top_key_name(l) for l in content.splitlines() if _is_top_key(l)}


def extract_yaml_from_hpp(text: str):
    """Pull the YAML out of config_default.hpp's `R"(...)"` raw-string literal.
    Returns the YAML text, or None if the wrapper isn't found."""
    m = re.search(r'R"\((.*)\)"', text, re.DOTALL)
    return m.group(1) if m else None


def _looks_like_reference(yaml_text: str) -> bool:
    """Sanity gate before trusting a reference: must carry the keys we key the
    whole thing on, so a garbled fetch/parse never drives the completion."""
    if not yaml_text:
        return False
    keys = present_top_level_keys(yaml_text)
    return {"SafeMode", "AdditionalApps", "DisableCloud"} <= keys and len(keys) >= 20


def split_blocks(yaml_text: str) -> List[Tuple[str, str]]:
    """Split a default-config YAML into ordered (key, block_text) pairs, where a
    block = its leading comment/blank lines + the top-level key line + any nested
    (indented) lines. Appending a block reproduces the canonical formatting.

    Trailing comment/blank lines after a key's nested content are treated as the
    LEADING comments of the NEXT key (that's how the canonical file is laid out).
    """
    blocks: List[Tuple[str, List[str]]] = []
    pending: List[str] = []          # comment/blank lines waiting for their key
    cur_key = None
    cur_lines: List[str] = []

    def flush():
        if cur_key is not None:
            blocks.append((cur_key, cur_lines))

    for line in yaml_text.splitlines():
        if _is_top_key(line):
            flush()
            cur_key = _top_key_name(line)
            cur_lines = pending + [line]
            pending = []
        elif cur_key is None:
            pending.append(line)                       # preamble before first key
        elif line.strip() == "" or line.lstrip().startswith("#"):
            pending.append(line)                       # maybe trailing -> next key
        elif line[0].isspace():
            cur_lines.extend(pending)                  # nested value of current key
            pending = []
            cur_lines.append(line)
        else:
            pending.append(line)                       # defensive; shouldn't happen
    flush()
    return [(k, "\n".join(ls)) for k, ls in blocks]


def complete_config_text(content: str, reference_yaml: str):
    """APPEND-ONLY completion. Returns (new_content, added_key_names).

    The original `content` is preserved byte-for-byte as a prefix of the result;
    only top-level keys absent from it are appended (with their default block).
    """
    reference = split_blocks(reference_yaml)
    if not reference:
        return content, []
    present = present_top_level_keys(content)
    missing = [(k, b) for k, b in reference if k not in present]
    if not missing:
        return content, []

    added = [k for k, _ in missing]
    header = "# --- keys added by LumaDeck to match SLSsteam's current schema ---"
    tail = "\n\n".join(b for _, b in missing)
    sep = "" if content.endswith("\n") else "\n"
    new_content = content + sep + "\n" + header + "\n" + tail + "\n"
    return new_content, added


def _cache_path() -> str:
    return _CACHE_FILE


def load_reference_yaml() -> str:
    """The reference YAML to complete against: the fetched cache if present and
    valid, else the bundled snapshot."""
    try:
        if os.path.isfile(_CACHE_FILE):
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = f.read()
            if _looks_like_reference(cached):
                return cached
    except Exception as exc:
        logger.warning(f"slssteam_schema: cache read failed ({exc}), using bundled")
    return _BUNDLED_YAML


async def refresh_reference_cache() -> bool:
    """Best-effort: fetch config_default.hpp, extract + validate the YAML, cache
    it to disk. Returns True on a successful refresh. Never raises. On any failure
    the existing cache (or the bundled snapshot) keeps being used."""
    try:
        from http_client import ensure_http_client
        client = await ensure_http_client(context="slssteam_schema")
        resp = await client.get(_CONFIG_DEFAULT_URL, timeout=_FETCH_TIMEOUT)
        if resp.status_code != 200:
            logger.info(f"slssteam_schema: HTTP {resp.status_code} for config_default.hpp; keeping cache")
            return False
        yaml_text = extract_yaml_from_hpp(resp.text)
        if not _looks_like_reference(yaml_text):
            logger.info("slssteam_schema: fetched config_default.hpp didn't validate; keeping bundled")
            return False
        os.makedirs(_CACHE_DIR, exist_ok=True)
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(yaml_text)
        os.replace(tmp, _CACHE_FILE)
        return True
    except Exception as exc:
        logger.info(f"slssteam_schema: reference refresh failed ({exc}); using bundled/cache")
        return False


def complete_slssteam_config(config_path: str | None = None) -> dict:
    """Append any missing SLSsteam keys to config.yaml (append-only, atomic).

    Returns {"completed": bool, "added": [...], "reason": str}. No-op (and never
    a write) when the config is absent, already complete, or no valid reference
    is available."""
    path = config_path or get_slssteam_config_path()
    if not os.path.isfile(path):
        return {"completed": False, "added": [], "reason": "config not present"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return {"completed": False, "added": [], "reason": f"read failed: {exc}"}

    new_content, added = complete_config_text(content, load_reference_yaml())
    if not added:
        return {"completed": False, "added": [], "reason": "already complete"}

    # Belt-and-suspenders: never write unless the original is preserved verbatim.
    if not new_content.startswith(content):
        logger.warning("slssteam_schema: completion would not preserve original; aborting write")
        return {"completed": False, "added": [], "reason": "safety check failed"}
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp, path)
    except Exception as exc:
        return {"completed": False, "added": [], "reason": f"write failed: {exc}"}
    logger.info(f"slssteam_schema: completed config with {len(added)} missing key(s): {added}")
    return {"completed": True, "added": added, "reason": "ok"}

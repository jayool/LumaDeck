"""What the account has a licence for, read from Steam's own package cache.

`<steam>/appcache/packageinfo.vdf` holds one entry per package the account is
licensed for (plus package 0, the one every account has) with the AppIDs each
package grants. Steam only requests PICS data for licensed packages, so an
AppID that appears in ANY package here is one the account has: bought, free,
or family-shared. An app that SLSsteam merely lists (ours or another tool's)
is in no package at all, and lumalinux's package-0 injection stays in memory:
measured on the SteamOS codespace, 2026-10-06, with an owned game (Darkest
Dungeon, package 33877), two owned free DLC (445700, 1117860), two paid DLC
the account lacks (none), a game LumaDeck added (Brotato, none) and TF2 /
Spacewar (package 0). SteamKit2's LicenseListCallback is the wire shape this
file caches: ownership is per package, and SLSsteam hooks app-level checks
(CheckAppOwnership, GetSubscribedApps), never the licence list.

Format: 4-byte magic (0x065655xx, the low byte is the version; 0x06565528 measured), 4-byte
universe, then per package: id (u32), SHA-1 (20), change number (u32), PICS
token (u64, version >= 0x28), a binary KeyValue tree whose root node is named
after the package, and a second terminator byte closing the document; the
list ends with id 0xFFFFFFFF. Binary KeyValue as SteamKit2 reads it: type
byte, NUL-terminated name, value by type (0 nested, 1 string, 2 int32, 3
float, 7 uint64, 0x0A int64, 8/0x0B end of node).

A parse failure yields an empty set: "not licensed" is the safe answer (the
normal add path), never a guess.
"""
from __future__ import annotations

import logging
import os
import struct
from typing import Dict, Optional, Set

from paths import real_home

logger = logging.getLogger("LumaDeck")

_cache: Dict[str, object] = {"path": "", "mtime": -1.0, "size": -1, "apps": set()}


def packageinfo_path() -> Optional[str]:
    home = real_home()
    for p in (os.path.join(home, ".local/share/Steam/appcache/packageinfo.vdf"),
              os.path.join(home, ".steam/steam/appcache/packageinfo.vdf"),
              os.path.join(home, ".steam/root/appcache/packageinfo.vdf")):
        if os.path.isfile(p) and os.path.getsize(p) > 8:
            return p
    return None


def _read_cstr(b: bytes, i: int):
    j = b.index(b"\x00", i)
    return b[i:j].decode("utf-8", "replace"), j + 1


def _read_kv(b: bytes, i: int):
    """One node's children, starting right after the node's name."""
    out: Dict[str, object] = {}
    while True:
        t = b[i]
        i += 1
        if t in (0x08, 0x0B):
            return out, i
        name, i = _read_cstr(b, i)
        if t == 0x00:
            out[name], i = _read_kv(b, i)
        elif t in (0x01, 0x05):
            out[name], i = _read_cstr(b, i)
        elif t in (0x02, 0x04, 0x06):
            out[name] = struct.unpack_from("<i", b, i)[0]
            i += 4
        elif t == 0x03:
            out[name] = struct.unpack_from("<f", b, i)[0]
            i += 4
        elif t in (0x07, 0x0A):
            out[name] = struct.unpack_from("<Q", b, i)[0]
            i += 8
        else:
            raise ValueError(f"unknown KeyValue type {t:#x} at offset {i - 1}")


def parse_packageinfo(data: bytes) -> Dict[int, Set[int]]:
    """{package id: {appids}} for every package in the file. Raises on a
    malformed file; callers decide what an unreadable cache means."""
    if len(data) < 8:
        raise ValueError("too short")
    magic = struct.unpack_from("<I", data, 0)[0]
    if (magic >> 8) != 0x065655:   # 0x065655xx, the low byte is the version
        raise ValueError(f"not a packageinfo.vdf (magic {magic:#x})")
    header = 32 if (magic & 0xFF) >= 0x28 else 24   # v28 adds the 8-byte PICS token
    i = 8
    out: Dict[int, Set[int]] = {}
    while i + 4 <= len(data):
        pid = struct.unpack_from("<I", data, i)[0]
        i += 4
        if pid == 0xFFFFFFFF:
            break
        i += header
        t = data[i]
        i += 1
        if t != 0x00:
            raise ValueError(f"package {pid}: root node type {t:#x}")
        _name, i = _read_cstr(data, i)
        kv, i = _read_kv(data, i)
        if i < len(data) and data[i] == 0x08:      # document terminator
            i += 1
        apps = kv.get("appids") if isinstance(kv, dict) else None
        ids: Set[int] = set()
        if isinstance(apps, dict):
            for v in apps.values():
                if isinstance(v, int) and v > 0:
                    ids.add(v)
        out[pid] = ids
    return out


def licensed_appids() -> Set[int]:
    """Every AppID the account has a licence for, package 0 included. Cached
    on the file's mtime and size; empty when the file is missing or does not
    parse (logged once per change)."""
    path = packageinfo_path()
    if not path:
        return set()
    try:
        st = os.stat(path)
    except OSError:
        return set()
    if (_cache["path"] == path and _cache["mtime"] == st.st_mtime
            and _cache["size"] == st.st_size):
        return set(_cache["apps"])  # type: ignore[arg-type]
    apps: Set[int] = set()
    try:
        with open(path, "rb") as fh:
            packages = parse_packageinfo(fh.read())
        for ids in packages.values():
            apps |= ids
        logger.info(f"LumaDeck: packageinfo.vdf: {len(packages)} licensed packages, {len(apps)} apps")
    except Exception as exc:
        logger.warning(f"LumaDeck: packageinfo.vdf unreadable ({exc}); treating nothing as licensed")
        apps = set()
    _cache.update({"path": path, "mtime": st.st_mtime, "size": st.st_size, "apps": set(apps)})
    return apps


def is_licensed(appid: int) -> bool:
    return int(appid) in licensed_appids()

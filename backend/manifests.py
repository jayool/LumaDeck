"""Manifest sourcing for lumalinux-managed games.

Since 2026-09-09 the manifest request-code providers are gone, so Steam can
only install or update a game we manage from a manifest that is ALREADY in
`<Steam>/depotcache/`. Everything here serves one question:

    "give me `<depot>_<gid>.manifest` for app A"

looked up in this order, stopping at the first hit:

  1. Steam's own depotcache/                      (nothing to do)
  2. LumaDeck's archive  ~/.local/share/lumadeck/manifests/<app>/
     Every manifest LumaDeck ever handles is copied here first. Steam deletes
     depotcache entries on uninstall (and, per moon's notes, after commits and
     re-plans); this copy survives, so a Steam-side reinstall or re-validate
     never needs the network. Verified 2026-09-11: putting the file back in
     depotcache is enough, Steam picks it up on its next ~30 s retry.
  3. GitHub P-ToyStore/SteamManifestCache_Pro, branch `<app>`, file
     `<depot>_<gid>.manifest`: the CURRENT public build, pushed by a bot on
     owning accounts within minutes of Valve. Fixed raw URL, no API, no key.
  4. Same repo, tag `<depot>_<gid>`: older builds the bot has seen (partial).
  5. Hubcap: the whole game zip (lua + keys + manifests). Only when the gid
     asked for is Valve's current one (Hubcap serves the current build) and at
     most once per app per day, because the API key has a daily quota.

Files fetched over the network are inflated when they come in the repo's
"Pro" wrapper (10-byte header + raw deflate), checked for the depotcache magic
and for the depot/gid stored INSIDE the manifest, archived, and only then
copied into depotcache/. A file that fails any check is dropped.

`current_gids` (Valve's public gid per depot) comes from api.steamcmd.net, a
PICS mirror; `steamcmd_app_info()` wraps it for the callers that need it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import tempfile
import time
import zipfile
import zlib
from typing import Dict, Optional, Tuple

from http_client import ensure_http_client
from paths import get_depotcache_dir, real_home, real_uid

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

REPO_OWNER = "P-ToyStore"
REPO_NAME = "SteamManifestCache_Pro"
_REPO_RAW = "https://raw.githubusercontent.com/" + REPO_OWNER + "/" + REPO_NAME + "/{ref}/{name}"
STEAMCMD_INFO = "https://api.steamcmd.net/v1/info/{appid}"

MANIFEST_MAGIC = b"\xd0\x17\xf6\x71"          # depotcache payload header
_PRO_HEADER = b"\x78\xda\x08\x00\x00\x00\x00\x00\x02\x03"
_HUBCAP_HOSTS = ("hubcapmanifest.com", "morrenus.xyz")
HUBCAP_RETRY_SECONDS = 24 * 60 * 60           # one Hubcap attempt per app per day

_DATA_ROOT = os.path.join(real_home(), ".local", "share", "lumadeck")
_CACHE_ROOT = os.path.join(real_home(), ".cache", "lumadeck")
_HUBCAP_ATTEMPTS = os.path.join(_CACHE_ROOT, "hubcap_attempts.json")


def archive_dir(appid: int) -> str:
    return os.path.join(_DATA_ROOT, "manifests", str(int(appid)))


def zip_copy_path(appid: int) -> str:
    """Where the last Hubcap zip for `appid` is kept (lua + keys + manifests)."""
    return os.path.join(_DATA_ROOT, "zips", f"{int(appid)}.zip")


def manifest_name(depot: int, gid: int) -> str:
    return f"{int(depot)}_{int(gid)}.manifest"


def _own(path: str) -> None:
    """Decky runs us as root; hand the file to the real user so Desktop-mode
    tooling (and the user) can touch it. Best effort."""
    try:
        uid = real_uid()
        import pwd
        gid = pwd.getpwuid(uid).pw_gid
        os.chown(path, uid, gid)
    except Exception:
        pass


def _write_atomic(path: str, data: bytes) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    _own(d)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise
    _own(path)


# ---------------------------------------------------------------------------
# Manifest bytes: inflate + identity
# ---------------------------------------------------------------------------

def inflate_pro(raw: bytes) -> Optional[bytes]:
    """Plain depotcache bytes from either a plain manifest or the repo's "Pro"
    wrapper (10-byte header, then a raw deflate stream). None if neither."""
    if raw[:4] == MANIFEST_MAGIC:
        return raw
    offsets = [10, 2, 0] if raw[:10] != _PRO_HEADER else [10]
    for off in offsets:
        try:
            out = zlib.decompressobj(-15).decompress(raw[off:])
        except zlib.error:
            continue
        if out[:4] == MANIFEST_MAGIC:
            return out
    return None


def _varint(b: bytes, i: int) -> Tuple[int, int]:
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return r, i


def _pb_fields(b: bytes) -> Dict[int, list]:
    i, out = 0, {}
    n = len(b)
    while i < n:
        k, i = _varint(b, i)
        f, t = k >> 3, k & 7
        if t == 0:
            v, i = _varint(b, i)
        elif t == 2:
            ln, i = _varint(b, i)
            v = b[i:i + ln]
            i += ln
        elif t == 1:
            v = b[i:i + 8]
            i += 8
        elif t == 5:
            v = b[i:i + 4]
            i += 4
        else:
            break
        out.setdefault(f, []).append(v)
    return out


def manifest_identity(data: bytes) -> Optional[Tuple[int, int]]:
    """(depot, gid) from the metadata block of a plain depotcache manifest."""
    i = 0
    while i + 8 <= len(data):
        magic, n = struct.unpack("<II", data[i:i + 8])
        i += 8
        if magic == 0x1F4812BE:                     # metadata
            f = _pb_fields(data[i:i + n])
            d = f.get(1, [None])[0]
            g = f.get(2, [None])[0]
            if isinstance(d, int) and isinstance(g, int):
                return d, g
            return None
        if magic not in (0x71F617D0, 0x1B81B817):   # payload, signature
            return None
        i += n
    return None


def validate_manifest(raw: bytes, depot: int, gid: int) -> Optional[bytes]:
    """Plain manifest bytes if `raw` is (or inflates to) the manifest for
    exactly depot/gid; None otherwise."""
    plain = inflate_pro(raw)
    if plain is None:
        return None
    ident = manifest_identity(plain)
    if ident != (int(depot), int(gid)):
        return None
    return plain


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

def archive_manifest(appid: int, depot: int, gid: int, data: bytes) -> str:
    path = os.path.join(archive_dir(appid), manifest_name(depot, gid))
    if not os.path.isfile(path):
        _write_atomic(path, data)
    return path


def archive_manifests_from_dir(appid: int, src_dir: str) -> int:
    """Copy every `<depot>_<gid>.manifest` under `src_dir` (recursively) into
    the app's archive. Files that don't validate are skipped. Returns count."""
    n = 0
    for root, _dirs, files in os.walk(src_dir):
        for name in files:
            m = re.fullmatch(r"(\d+)_(\d+)\.manifest", name)
            if not m:
                continue
            try:
                with open(os.path.join(root, name), "rb") as f:
                    raw = f.read()
            except OSError:
                continue
            plain = validate_manifest(raw, int(m.group(1)), int(m.group(2)))
            if plain is None:
                logger.warning(f"LumaDeck: archive skip {name} for {appid}: not a valid manifest")
                continue
            archive_manifest(appid, int(m.group(1)), int(m.group(2)), plain)
            n += 1
    return n


def archive_zip(appid: int, zip_path: str) -> int:
    """Keep a copy of a game zip (lua + manifests) and archive its manifests.
    Returns the number of manifests archived."""
    try:
        dest = zip_copy_path(appid)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        _own(os.path.dirname(dest))
        shutil.copyfile(zip_path, dest)
        _own(dest)
    except Exception as exc:
        logger.warning(f"LumaDeck: could not keep a copy of the zip for {appid}: {exc}")
    n = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                m = re.fullmatch(r"(\d+)_(\d+)\.manifest", os.path.basename(member))
                if not m or member.endswith("/"):
                    continue
                plain = validate_manifest(zf.read(member), int(m.group(1)), int(m.group(2)))
                if plain is None:
                    continue
                archive_manifest(appid, int(m.group(1)), int(m.group(2)), plain)
                n += 1
    except Exception as exc:
        logger.warning(f"LumaDeck: archive from zip failed for {appid}: {exc}")
    return n


def archived_manifests(appid: int) -> Dict[int, list]:
    """{depot: [gid, ...]} present in the app's archive."""
    out: Dict[int, list] = {}
    d = archive_dir(appid)
    if not os.path.isdir(d):
        return out
    for name in os.listdir(d):
        m = re.fullmatch(r"(\d+)_(\d+)\.manifest", name)
        if m:
            out.setdefault(int(m.group(1)), []).append(int(m.group(2)))
    return out


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def depotcache_path(depot: int, gid: int) -> Optional[str]:
    d = get_depotcache_dir()
    return os.path.join(d, manifest_name(depot, gid)) if d else None


def place_in_depotcache(depot: int, gid: int, data: bytes) -> Optional[str]:
    path = depotcache_path(depot, gid)
    if not path:
        return None
    if not os.path.isfile(path):
        _write_atomic(path, data)
    return path


async def fetch_repo_manifest(appid: int, depot: int, gid: int) -> Optional[bytes]:
    """Branch `<app>` first (current build), then tag `<depot>_<gid>` (history).
    Returns validated plain manifest bytes or None."""
    client = await ensure_http_client("manifests")
    name = manifest_name(depot, gid)
    for ref in (str(int(appid)), f"refs/tags/{int(depot)}_{int(gid)}"):
        url = _REPO_RAW.format(ref=ref, name=name)
        try:
            resp = await client.get(url, timeout=60)
        except Exception as exc:
            logger.info(f"LumaDeck: repo fetch error {url}: {exc}")
            continue
        if resp.status_code != 200:
            continue
        plain = validate_manifest(resp.content, depot, gid)
        if plain is None:
            logger.warning(f"LumaDeck: repo file {ref}/{name} did not validate as depot {depot} gid {gid}")
            continue
        logger.info(f"LumaDeck: manifest {name} for {appid} from repo ({'branch' if ref.isdigit() else 'tag'})")
        return plain
    return None


def _hubcap_attempts() -> Dict[str, float]:
    try:
        with open(_HUBCAP_ATTEMPTS, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def hubcap_budget_ok(appid: int) -> bool:
    last = _hubcap_attempts().get(str(int(appid)), 0)
    return (time.time() - float(last)) >= HUBCAP_RETRY_SECONDS


def note_hubcap_attempt(appid: int) -> None:
    data = _hubcap_attempts()
    data[str(int(appid))] = time.time()
    try:
        _write_atomic(_HUBCAP_ATTEMPTS, json.dumps(data).encode("utf-8"))
    except Exception:
        pass


def api_request(url_template: str, appid: int) -> Tuple[str, Dict[str, str]]:
    """(url, headers) for one api.json entry: substitutes <appid>, moves a
    Hubcap ?api_key= into an Authorization header so the key never lands in a
    log, and adds the Ryuu cookie when configured."""
    from config import USER_AGENT
    url = url_template.replace("<appid>", str(int(appid)))
    headers = {"User-Agent": USER_AGENT}
    if any(h in url for h in _HUBCAP_HOSTS):
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
        parts = urlsplit(url)
        rest, token = [], None
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            if k == "api_key":
                token = v
            else:
                rest.append((k, v))
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(rest), parts.fragment))
        if token:
            headers["Authorization"] = f"Bearer {token}"
    if "ryuu.lol" in url:
        try:
            from api_manifest import load_ryu_cookie
            cookie = load_ryu_cookie()
        except Exception:
            cookie = ""
        if cookie:
            headers.update({
                "Cookie": cookie, "Referer": "https://generator.ryuu.lol/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
    return url, headers


async def fetch_game_zip(appid: int, *, quiet: bool = True) -> Optional[str]:
    """Download the game zip from the first enabled api.json source that has
    it (Hubcap and friends). Returns a path in a fresh temp dir, or None. The
    caller owns the temp dir. Records a Hubcap attempt for the daily budget
    whether or not it succeeded."""
    from api_manifest import load_api_manifest
    apis = load_api_manifest()
    if not apis:
        return None
    client = await ensure_http_client("manifests")
    note_hubcap_attempt(appid)
    tmp_dir = tempfile.mkdtemp(prefix=f"lumadeck_zip_{int(appid)}_")
    dest = os.path.join(tmp_dir, f"{int(appid)}.zip")
    for api in apis:
        if not api.get("enabled", True):
            continue
        name = api.get("name", "?")
        url, headers = api_request(api.get("url", ""), appid)
        try:
            resp = await client.get(url, headers=headers, timeout=120)
        except Exception as exc:
            logger.info(f"LumaDeck: zip source '{name}' error for {appid}: {exc}")
            continue
        if resp.status_code != int(api.get("success_code", 200)):
            logger.info(f"LumaDeck: zip source '{name}' HTTP {resp.status_code} for {appid}")
            continue
        body = resp.content
        if body[:4] not in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
            logger.info(f"LumaDeck: zip source '{name}' returned non-zip for {appid}")
            continue
        with open(dest, "wb") as f:
            f.write(body)
        logger.info(f"LumaDeck: zip for {appid} from '{name}' ({len(body)} bytes)")
        return dest
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

async def resolve_manifest(
    appid: int, depot: int, gid: int, *,
    allow_hubcap: bool = True, current_gid: Optional[int] = None,
) -> Tuple[Optional[str], str]:
    """Make `<depot>_<gid>.manifest` exist in depotcache/. Returns
    (path, source) with source in {"depotcache", "archive", "repo", "hubcap"},
    or (None, reason). Hubcap is only tried when `gid == current_gid`."""
    depot, gid = int(depot), int(gid)
    path = depotcache_path(depot, gid)
    if not path:
        return None, "steam root not found"
    if os.path.isfile(path):
        return path, "depotcache"

    arch = os.path.join(archive_dir(appid), manifest_name(depot, gid))
    if os.path.isfile(arch):
        with open(arch, "rb") as f:
            data = f.read()
        if validate_manifest(data, depot, gid) is not None:
            place_in_depotcache(depot, gid, data)
            return path, "archive"
        logger.warning(f"LumaDeck: archived {os.path.basename(arch)} is corrupt, dropping it")
        try:
            os.remove(arch)
        except OSError:
            pass

    data = await fetch_repo_manifest(appid, depot, gid)
    if data is not None:
        archive_manifest(appid, depot, gid, data)
        place_in_depotcache(depot, gid, data)
        return path, "repo"

    if allow_hubcap and current_gid is not None and gid == int(current_gid):
        if not hubcap_budget_ok(appid):
            return None, "not in repo; Hubcap already tried today"
        zip_path = await fetch_game_zip(appid)
        if zip_path:
            try:
                archive_zip(appid, zip_path)
            finally:
                shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)
            if os.path.isfile(arch):
                with open(arch, "rb") as f:
                    data = f.read()
                place_in_depotcache(depot, gid, data)
                return path, "hubcap"
            return None, "Hubcap zip did not carry this manifest"
        return None, "not in repo; Hubcap did not return a zip"
    return None, "not in repo" + ("" if current_gid is None or gid == int(current_gid)
                                  else " (old build, Hubcap only has the current one)")


async def resolve_all(
    appid: int, wanted: Dict[int, int], *,
    allow_hubcap: bool = True, current_gids: Optional[Dict[int, int]] = None,
) -> Tuple[Dict[int, str], Dict[int, str]]:
    """Resolve every depot->gid in `wanted`. Returns (found {depot: path},
    missing {depot: reason}). Nothing is rolled back on a partial result: a
    manifest in depotcache/ is harmless until something pins to it."""
    found: Dict[int, str] = {}
    missing: Dict[int, str] = {}
    current_gids = current_gids or {}
    for depot, gid in wanted.items():
        path, why = await resolve_manifest(
            appid, depot, gid, allow_hubcap=allow_hubcap,
            current_gid=current_gids.get(int(depot)),
        )
        if path:
            found[int(depot)] = path
        else:
            missing[int(depot)] = why
    return found, missing


# ---------------------------------------------------------------------------
# Valve's current state (PICS mirror)
# ---------------------------------------------------------------------------

async def steamcmd_app_info(appid: int) -> Optional[dict]:
    """{"buildid": int|None, "depots": {depot: {"gid": int, "oslist": str,
    "osarch": str, "dlcappid": int|None, "sharedinstall": bool}},
    "listofdlc": [int]} for the public branch, or None on any failure."""
    client = await ensure_http_client("manifests")
    try:
        resp = await client.get(STEAMCMD_INFO.format(appid=int(appid)), timeout=25)
        if resp.status_code != 200:
            return None
        payload = resp.json()
        app = payload.get("data", {}).get(str(int(appid)))
        if not isinstance(app, dict):
            return None
    except Exception as exc:
        logger.info(f"LumaDeck: steamcmd.net error for {appid}: {exc}")
        return None
    depots_raw = app.get("depots") or {}
    depots: Dict[int, dict] = {}
    for did, dep in depots_raw.items():
        if not str(did).isdigit() or not isinstance(dep, dict):
            continue
        pub = (dep.get("manifests") or {}).get("public") or {}
        gid = pub.get("gid")
        if not gid or not str(gid).isdigit():
            continue
        cfg = dep.get("config") or {}
        dlc = dep.get("dlcappid")
        depots[int(did)] = {
            "gid": int(gid),
            "oslist": str(cfg.get("oslist", "")),
            "osarch": str(cfg.get("osarch", "")),
            "dlcappid": int(dlc) if str(dlc or "").isdigit() else None,
            "sharedinstall": str(dep.get("sharedinstall", "0")) == "1",
        }
    build = ((depots_raw.get("branches") or {}).get("public") or {}).get("buildid")
    dlcs = (app.get("extended") or {}).get("listofdlc", "")
    return {
        "buildid": int(build) if str(build or "").isdigit() else None,
        "depots": depots,
        "listofdlc": [int(x) for x in str(dlcs).split(",") if x.strip().isdigit()],
    }

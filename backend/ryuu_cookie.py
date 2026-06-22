"""Import the Ryuu `session` cookie from Steam's in-client (CEF/Chromium)
cookie store, so the user doesn't need DevTools / copy-paste (#22).

Steam's browser is CEF (Chromium). Cookies live in a SQLite `Cookies` DB; the
value is in `encrypted_value`, prefixed by a scheme tag:
  - v10 -> AES-128-CBC, key = PBKDF2-HMAC-SHA1(b"peanuts", b"saltysalt", 1, 16),
           IV = 16 * 0x20. Decryptable with no secrets — this is what Chromium
           uses when no OS keyring is available (Game Mode / gamescope).
  - v11 -> key in the OS keyring (GNOME Keyring / KWallet). Not handled here.
Newer Chromium (M104+) prepends a 32-byte SHA256(host) to the plaintext; we
detect and strip it. AES is done via the `openssl` CLI (always present on
SteamOS) so we need no Python crypto dependency.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
from glob import glob

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

_RYUU_HOST_MATCH = "ryuu.lol"
_RYUU_COOKIE_NAME = "session"


def _find_cookie_dbs() -> list:
    """Candidate CEF `Cookies` SQLite DBs under the Steam install."""
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
    ]
    patterns = (
        "config/htmlcache/Cookies",
        "config/htmlcache/Network/Cookies",
        "**/htmlcache/**/Cookies",
    )
    found, seen = [], set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for pat in patterns:
            for p in glob(os.path.join(root, pat), recursive=True):
                rp = os.path.realpath(p)
                if rp not in seen and os.path.isfile(rp):
                    seen.add(rp)
                    found.append(rp)
    return found


def _read_encrypted_session(db_path: str):
    """Copy the (possibly Steam-locked, WAL-mode) Cookies DB to a temp file and
    read the encrypted_value of the ryuu.lol `session` cookie. Returns the raw
    encrypted bytes, or None."""
    tmpdir = tempfile.mkdtemp(prefix="lumadeck_cookies_")
    try:
        local = os.path.join(tmpdir, "Cookies")
        shutil.copy2(db_path, local)
        # Copy WAL/SHM sidecars too so recent (un-checkpointed) writes are seen.
        for ext in ("-wal", "-shm"):
            if os.path.exists(db_path + ext):
                shutil.copy2(db_path + ext, local + ext)
        con = sqlite3.connect(local)
        try:
            rows = con.execute(
                "SELECT host_key, encrypted_value FROM cookies "
                "WHERE name = ? AND host_key LIKE ?",
                (_RYUU_COOKIE_NAME, f"%{_RYUU_HOST_MATCH}%"),
            ).fetchall()
        finally:
            con.close()
        if not rows:
            return None
        # Prefer an exact generator.ryuu.lol host if several matched.
        rows.sort(key=lambda r: 0 if "generator.ryuu.lol" in (r[0] or "") else 1)
        return rows[0][1]
    except Exception as exc:
        logger.warning(f"Ryuu cookie: read failed for {db_path}: {exc}")
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_value(plain: bytes):
    """Return the printable cookie value, stripping the optional 32-byte
    SHA256(host) prefix that Chromium M104+ prepends before encryption."""
    def printable(b: bytes):
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return s if (s and all(32 <= ord(c) < 127 for c in s)) else None

    direct = printable(plain)
    if direct:
        return direct
    if len(plain) > 32:
        return printable(plain[32:])
    return None


def _decrypt_v10(encrypted: bytes):
    """Decrypt a Chromium `v10` (peanuts) cookie value. None on anything else."""
    if not encrypted or encrypted[:3] != b"v10":
        if encrypted and encrypted[:3] == b"v11":
            logger.warning(
                "Ryuu cookie: value is v11 (OS keyring) — cannot decrypt without the keyring"
            )
        return None
    key = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)
    iv = b"\x20" * 16
    ciphertext = encrypted[3:]
    if not ciphertext or len(ciphertext) % 16 != 0:
        return None
    try:
        proc = subprocess.run(
            ["openssl", "enc", "-d", "-aes-128-cbc",
             "-K", key.hex(), "-iv", iv.hex(), "-nopad"],
            input=ciphertext, capture_output=True, timeout=10,
        )
    except Exception as exc:
        logger.warning(f"Ryuu cookie: openssl failed: {exc}")
        return None
    plain = proc.stdout
    if not plain:
        return None
    # Strip PKCS7 padding if present.
    pad = plain[-1]
    if 1 <= pad <= 16 and plain[-pad:] == bytes([pad]) * pad:
        plain = plain[:-pad]
    return _extract_value(plain)


def import_ryuu_cookie_from_browser() -> dict:
    """Locate Steam's CEF cookie DB, extract + decrypt the ryuu.lol `session`
    cookie, and persist it via save_ryu_cookie. Returns {success, message/error}.
    """
    dbs = _find_cookie_dbs()
    if not dbs:
        return {
            "success": False,
            "error": "Steam browser cookie store not found. Open Ryuu in the "
                     "Steam browser and log in first.",
        }

    found_but_undecryptable = False
    for db in dbs:
        enc = _read_encrypted_session(db)
        if enc is None:
            continue
        value = _decrypt_v10(enc)
        if not value:
            found_but_undecryptable = True
            continue
        from api_manifest import save_ryu_cookie
        # save_ryu_cookie prepends "session=" itself.
        save_ryu_cookie(value)
        logger.info(f"Ryuu cookie: imported from {db} ({len(value)} chars)")
        return {"success": True,
                "message": "Ryuu cookie imported from the Steam browser."}

    if found_but_undecryptable:
        return {
            "success": False,
            "error": "Found a Ryuu cookie but couldn't decrypt it (it may be "
                     "keyring-encrypted on this setup). Paste it manually from "
                     "the browser's DevTools instead.",
        }
    return {
        "success": False,
        "error": "No Ryuu session cookie found in the Steam browser. Open "
                 "generator.ryuu.lol in the Steam browser, log in with Discord, "
                 "then try again.",
    }

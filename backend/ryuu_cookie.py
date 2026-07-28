"""Import the Ryuu `session` cookie from Steam's in-client (CEF/Chromium)
cookie store, so the user doesn't need DevTools / copy-paste (#22).

Steam's browser is CEF (Chromium). Cookies live in a SQLite `Cookies` DB; the
value is in `encrypted_value`, prefixed by a scheme tag:
  - v10 -> AES-128-CBC, key = PBKDF2-HMAC-SHA1(b"peanuts", b"saltysalt", 1, 16),
           IV = 16 * 0x20. Decryptable with no secrets — this is what Chromium
           uses when no OS keyring is available (Game Mode / gamescope).
  - v11 -> AES-128-CBC, same KDF/IV, but the password is a random secret stored
           in the OS keyring (GNOME Keyring / KWallet) instead of b"peanuts".
           We read it from the *deck user's* session (Decky runs as root, the
           keyring lives on the deck user's D-Bus) via `secret-tool` and, on
           KDE, `kwallet-query`. See `_keyring_passwords`.
Newer Chromium (M104+) prepends a 32-byte SHA256(host) to the plaintext; we
detect and strip it. AES is done via the `openssl` CLI (always present on
SteamOS) so we need no Python crypto dependency.
"""

from __future__ import annotations

import hashlib
import os
import pwd
import shutil
import sqlite3
import subprocess
import tempfile

from subprocess_env import clean_env

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

_RYUU_HOST_MATCH = "ryuu.lol"
_RYUU_COOKIE_NAME = "session"

# Product names CEF/Chromium may have registered its keyring key under. Steam's
# CEF build is the unknown here, so we try the common ones and accept whichever
# password actually decrypts the cookie to printable text.
_KEYRING_APP_NAMES = ("chrome", "chromium", "Chromium", "steam", "Steam", "cef")
# (wallet folder, entry) pairs KWallet may hold the Chromium key under.
_KWALLET_ENTRIES = (
    ("Chromium Keys", "Chromium Safe Storage"),
    ("Chrome Keys", "Chrome Safe Storage"),
)


def _find_cookie_dbs() -> list:
    """Candidate CEF `Cookies` SQLite DBs. The exact subdir under config/htmlcache
    varies by Chromium build — observed `Default/Cookies` (modern), and older
    `Cookies` / `Network/Cookies`. Search ONLY under config/ (a small tree); never
    walk the whole Steam install, which holds the game library and would make a
    recursive scan crawl (that hang bit the earlier glob-based version).

    Decky runs as root (~ = /root), so list the deck user's Steam paths first —
    the same convention paths.py uses — before falling back to $HOME."""
    home = os.path.expanduser("~")
    roots = [
        "/home/deck/.local/share/Steam",
        "/home/deck/.steam/steam",
        "/home/deck/.steam/root",
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
    ]
    found, seen = [], set()
    for root in roots:
        cfg = os.path.join(root, "config")
        if not os.path.isdir(cfg):
            continue
        for dirpath, _dirs, files in os.walk(cfg):
            if "Cookies" in files:
                rp = os.path.realpath(os.path.join(dirpath, "Cookies"))
                if rp not in seen and os.path.isfile(rp):
                    seen.add(rp)
                    found.append(rp)
    return found


def _read_encrypted_session(db_path: str):
    """Copy the (possibly Steam-locked, WAL-mode) Cookies DB to a temp file and
    read the ryuu.lol `session` cookie. Returns (encrypted_value, expires_utc)
    or None. `expires_utc` is Chromium's microseconds-since-1601 expiry (0 for a
    session cookie); the caller uses it to surface a credential-expiry warning."""
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
                "SELECT host_key, encrypted_value, expires_utc FROM cookies "
                "WHERE name = ? AND host_key LIKE ?",
                (_RYUU_COOKIE_NAME, f"%{_RYUU_HOST_MATCH}%"),
            ).fetchall()
        finally:
            con.close()
        if not rows:
            return None
        # Prefer an exact generator.ryuu.lol host if several matched.
        rows.sort(key=lambda r: 0 if "generator.ryuu.lol" in (r[0] or "") else 1)
        return rows[0][1], rows[0][2]
    except Exception as exc:
        logger.warning(f"Ryuu cookie: read failed for {db_path}: {exc}")
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _chromium_epoch_to_iso(expires_utc):
    """Chromium cookie `expires_utc` is microseconds since 1601-01-01 UTC.
    0 (or anything in the past) means a session cookie / no usable expiry.
    Returns an ISO-8601 string, or None."""
    if not expires_utc:
        return None
    try:
        import datetime
        unix = expires_utc / 1_000_000 - 11_644_473_600
        if unix <= 0:
            return None
        return (datetime.datetime.utcfromtimestamp(unix)
                .replace(microsecond=0).isoformat())
    except Exception:
        return None


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


def _deck_session_env() -> dict:
    """Env for running a keyring query AS the deck user, in the deck user's login
    session (Decky's backend is root and not in that session by default). Mirrors
    desktop_handoff.py's `sudo -u deck env DBUS_SESSION_BUS_ADDRESS=...` pattern."""
    try:
        uid = pwd.getpwnam("deck").pw_uid
    except KeyError:
        uid = 1000
    runtime = f"/run/user/{uid}"
    return {
        "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
        "HOME": "/home/deck",
    }


def _run_as_deck(argv: list) -> bytes:
    """Run `argv` as the deck user with its session bus; return stdout bytes (b''
    on any failure — this is best-effort keyring probing, never fatal)."""
    env = _deck_session_env()
    cmd = ["sudo", "-u", "deck", "env"] + [f"{k}={v}" for k, v in env.items()] + argv
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=10)
        return proc.stdout or b""
    except FileNotFoundError:
        return b""            # sudo / the queried tool isn't installed
    except Exception as exc:
        logger.warning(f"Ryuu cookie: keyring probe failed ({argv[:1]}): {exc}")
        return b""


def _keyring_passwords() -> list:
    """Best-effort list of candidate 'Safe Storage' passwords from the deck user's
    keyring — via secret-tool (Secret Service / GNOME Keyring) and kwallet-query
    (KDE). We don't know which product name Steam's CEF used, so we collect every
    candidate and let the caller try each against the ciphertext."""
    out = []
    for app in _KEYRING_APP_NAMES:
        pw = _run_as_deck(["secret-tool", "lookup", "application", app]).strip()
        if pw and pw not in out:
            out.append(pw)
    for folder, entry in _KWALLET_ENTRIES:
        pw = _run_as_deck(
            ["kwallet-query", "-f", folder, "-r", entry, "kdewallet"]
        ).strip()
        # kwallet-query prints an error line to stdout on a miss; keep only
        # plausible base64-ish secrets (no spaces, reasonable length).
        if pw and b" " not in pw and 8 <= len(pw) <= 64 and pw not in out:
            out.append(pw)
    return out


def _openssl_path() -> str:
    """Absolute path to the openssl binary. Do NOT rely on the subprocess PATH:
    the Decky backend runs with a minimal PATH that often lacks /usr/sbin, yet on
    some distros (e.g. GitHub Codespaces) openssl lives in /usr/sbin — a bare
    "openssl" then raises FileNotFoundError and every cookie fails to "decrypt".
    Resolve it explicitly, checking sbin locations shutil.which would miss."""
    p = shutil.which("openssl")
    if p:
        return p
    for cand in ("/usr/bin/openssl", "/usr/sbin/openssl",
                 "/bin/openssl", "/sbin/openssl", "/usr/local/bin/openssl"):
        if os.path.exists(cand):
            return cand
    return "openssl"  # last resort; will fail loudly in the log below


def _aes_decrypt_value(ciphertext: bytes, password: bytes):
    """Chromium cookie decrypt: key = PBKDF2-HMAC-SHA1(password,'saltysalt',1,16),
    IV = 16*0x20, AES-128-CBC. Returns the printable cookie value or None.

    Every None-return logs WHY: the same code decrypts fine in a shell but was
    silently failing when invoked from Decky's plugin-backend process, and the
    old silent returns hid the cause. Now the LumaDeck log names it."""
    if not ciphertext or len(ciphertext) % 16 != 0:
        logger.warning("Ryuu cookie: bad ciphertext (len=%d, not 16-aligned)"
                       % len(ciphertext or b""))
        return None
    key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1, 16)
    iv = b"\x20" * 16
    ossl = _openssl_path()
    try:
        proc = subprocess.run(
            [ossl, "enc", "-d", "-aes-128-cbc",
             "-K", key.hex(), "-iv", iv.hex(), "-nopad"],
            input=ciphertext, capture_output=True, timeout=10,
            env=clean_env(),
        )
    except Exception as exc:
        logger.warning("Ryuu cookie: openssl (%s) raised: %r" % (ossl, exc))
        return None
    plain = proc.stdout
    if not plain:
        logger.warning("Ryuu cookie: openssl (%s) no output (rc=%s stderr=%r)"
                       % (ossl, proc.returncode, (proc.stderr or b"")[:200]))
        return None
    # Strip PKCS7 padding if present.
    pad = plain[-1]
    if 1 <= pad <= 16 and plain[-pad:] == bytes([pad]) * pad:
        plain = plain[:-pad]
    val = _extract_value(plain)
    if val is None:
        logger.warning("Ryuu cookie: decrypted %d bytes but not printable "
                       "(head=%r)" % (len(plain), plain[:16]))
    return val


def _decrypt_cookie(encrypted: bytes):
    """Decrypt a Chromium cookie value. Returns (value, reason):
      value  = the cookie string, or None if it couldn't be decrypted.
      reason = short tag for the caller's error message when value is None
               ('v11-no-keyring' | 'v11-decrypt-failed' | 'decrypt-failed').
    v10 = fixed 'peanuts' password. v11 = a random password in the OS keyring;
    we read every candidate the keyring exposes and accept the one that decrypts."""
    if not encrypted or len(encrypted) < 3:
        return None, "decrypt-failed"
    tag = encrypted[:3]
    ciphertext = encrypted[3:]

    if tag == b"v10":
        return _aes_decrypt_value(ciphertext, b"peanuts"), "decrypt-failed"

    if tag == b"v11":
        passwords = _keyring_passwords()
        if not passwords:
            logger.warning(
                "Ryuu cookie: value is v11 (OS keyring) but no keyring secret "
                "was readable from the deck session (secret-tool/kwallet-query "
                "missing, keyring locked, or unknown app name)."
            )
            return None, "v11-no-keyring"
        for pw in passwords:
            val = _aes_decrypt_value(ciphertext, pw)
            if val:
                logger.info("Ryuu cookie: decrypted v11 via keyring secret.")
                return val, ""
        logger.warning(
            f"Ryuu cookie: value is v11; tried {len(passwords)} keyring "
            "secret(s), none decrypted it."
        )
        return None, "v11-decrypt-failed"

    # Unknown scheme — try peanuts anyway (older/edge builds sometimes store
    # unversioned AES with the peanuts key).
    return _aes_decrypt_value(encrypted, b"peanuts"), "decrypt-failed"


def _read_all_cookies_for_host(host_match: str, name_prefix: str = "") -> dict:
    """Read + decrypt cookies whose host_key contains `host_match` from Steam's
    CEF cookie store, returning {name: value}. Reuses the copy-WAL read and
    `_decrypt_cookie` of the Ryuu import (v10 'peanuts' AND v11 keyring), so it
    works while Steam's browser is open. Cookies that can't be decrypted on this
    setup are skipped.

    `name_prefix` (optional) restricts the query to cookies whose name starts
    with it — decrypt is one `openssl` subprocess per cookie, so narrowing to
    just the cookie(s) the caller wants avoids decrypting every unrelated
    (Cloudflare/analytics/...) cookie on the host each call. Passing "" reads
    all of them (the original behaviour).

    Used by the LuaTools account harvest (backend/luatools_auth.py) to grab the
    chunked Supabase session cookie (sb-...-auth-token.0 / .1 / ...)."""
    out: dict = {}
    for db_path in _find_cookie_dbs():
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
                if name_prefix:
                    rows = con.execute(
                        "SELECT name, encrypted_value FROM cookies "
                        "WHERE host_key LIKE ? AND name LIKE ?",
                        (f"%{host_match}%", f"{name_prefix}%"),
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT name, encrypted_value FROM cookies "
                        "WHERE host_key LIKE ?",
                        (f"%{host_match}%",),
                    ).fetchall()
            finally:
                con.close()
            for name, enc in rows:
                if name in out:
                    continue  # first DB / first match wins
                value, _reason = _decrypt_cookie(enc)
                if value is not None:
                    out[name] = value
        except Exception as exc:
            logger.warning(f"Cookie harvest: read failed for {db_path}: {exc}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return out


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

    last_reason = ""
    for db in dbs:
        res = _read_encrypted_session(db)
        if res is None:
            continue
        enc, expires_utc = res
        value, reason = _decrypt_cookie(enc)
        if not value:
            last_reason = reason or last_reason
            continue
        from api_manifest import save_ryu_cookie, save_ryu_cookie_expiry
        # save_ryu_cookie prepends "session=" itself.
        save_ryu_cookie(value)
        # Persist the cookie's own expiry so the credential-status check can
        # warn before it lapses (None for a session cookie clears the sidecar).
        save_ryu_cookie_expiry(_chromium_epoch_to_iso(expires_utc))
        logger.info(f"Ryuu cookie: imported from {db} ({len(value)} chars)")
        return {"success": True,
                "message": "Ryuu cookie imported from the Steam browser."}

    if last_reason == "v11-no-keyring":
        return {
            "success": False,
            "error": "Found a Ryuu cookie encrypted by the system keyring, but "
                     "the keyring secret couldn't be read (keyring locked, or "
                     "secret-tool/kwallet-query not installed). Unlock the "
                     "keyring and try again.",
        }
    if last_reason in ("v11-decrypt-failed", "decrypt-failed"):
        return {
            "success": False,
            "error": "Found a Ryuu cookie but couldn't decrypt it on this setup. "
                     "Paste it manually from the browser's DevTools instead.",
        }
    return {
        "success": False,
        "error": "No Ryuu session cookie found in the Steam browser. Open "
                 "generator.ryuu.lol in the Steam browser, log in with Discord, "
                 "then try again.",
    }

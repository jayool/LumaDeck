"""Minimal Chrome DevTools Protocol client over the Steam CEF debug port.

Steam's Gamepad UI runs with CEF remote debugging enabled (Decky depends on it),
exposing a DevTools endpoint on 127.0.0.1:8080. That lets us read and clear the
browser's LIVE cookie store directly:

  * Reading — CEF holds a freshly-set cookie in memory for ~15 s before it
    flushes to the on-disk SQLite store. Polling the disk therefore waits that
    whole flush window; reading via CDP captures a login the instant it lands.
    CDP also returns cookie values already decrypted, so no openssl round-trip.
  * Clearing — deleting the on-disk store does NOT drop CEF's in-memory copy, so
    a plain "delete the session file" logout leaves lua.tools still signed in.
    Deleting through CDP clears the live cookie for real.

Pure stdlib (socket-level WebSocket); no third-party deps. Best-effort: every
entry point returns None / -1 when the debug port isn't reachable, so callers can
fall back to the on-disk cookie scrape.
"""
from __future__ import annotations

import base64
import json
import os
import socket
from urllib.parse import urlparse
from urllib.request import urlopen

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

DEBUG_PORT = 8080
_TIMEOUT = 5


def _pick_target(port: int) -> str | None:
    """WebSocket debugger URL of a usable target (prefer a real page), or None."""
    try:
        data = json.load(urlopen(f"http://127.0.0.1:{port}/json", timeout=3))
    except Exception:
        return None
    targets = [t for t in data if t.get("webSocketDebuggerUrl")]
    if not targets:
        return None
    page = next((t for t in targets if t.get("type") == "page"), None)
    return (page or targets[0])["webSocketDebuggerUrl"]


# --- minimal WebSocket client (one request/response per connection) ---
def _recv_exact(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise ConnectionError("socket closed")
        buf += c
    return buf


def _read_frame(s: socket.socket):
    b0, b1 = _recv_exact(s, 2)
    fin = b0 & 0x80
    op = b0 & 0x0F
    masked = b1 & 0x80
    ln = b1 & 0x7F
    if ln == 126:
        ln = int.from_bytes(_recv_exact(s, 2), "big")
    elif ln == 127:
        ln = int.from_bytes(_recv_exact(s, 8), "big")
    mask = _recv_exact(s, 4) if masked else b""
    data = _recv_exact(s, ln) if ln else b""
    if masked:
        data = bytes(d ^ mask[i % 4] for i, d in enumerate(data))
    return fin, op, data


def _send_text(s: socket.socket, text: str) -> None:
    p = text.encode()
    h = bytearray([0x81])  # FIN + text
    n = len(p)
    if n < 126:
        h.append(0x80 | n)
    elif n < 65536:
        h.append(0x80 | 126)
        h += n.to_bytes(2, "big")
    else:
        h.append(0x80 | 127)
        h += n.to_bytes(8, "big")
    mask = os.urandom(4)
    h += mask
    s.sendall(bytes(h) + bytes(b ^ mask[i % 4] for i, b in enumerate(p)))


def _call(ws_url: str, method: str, params: dict) -> dict:
    u = urlparse(ws_url)
    path = u.path + (("?" + u.query) if u.query else "")
    s = socket.create_connection((u.hostname, u.port or 80), timeout=_TIMEOUT)
    try:
        s.settimeout(_TIMEOUT)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall(
            (f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
             f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
             f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += s.recv(4096)
        if b" 101 " not in resp.split(b"\r\n")[0]:
            raise ConnectionError("ws handshake failed")
        _send_text(s, json.dumps({"id": 1, "method": method, "params": params}))
        buf = b""
        while True:
            fin, op, data = _read_frame(s)
            if op == 0x8:
                raise ConnectionError("ws closed")
            buf += data
            if fin:
                msg = json.loads(buf.decode("utf-8", "replace"))
                buf = b""
                if msg.get("id") == 1:
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    return msg.get("result", {})
    finally:
        s.close()


def get_cookies(port: int = DEBUG_PORT):
    """Live CEF cookies (values already decrypted) as a list of dicts, or None if
    the debug port isn't reachable."""
    ws = _pick_target(port)
    if not ws:
        return None
    try:
        return _call(ws, "Storage.getCookies", {}).get("cookies", [])
    except Exception as exc:
        logger.info(f"CDP get_cookies failed: {exc}")
        return None


def delete_cookies_matching(name_prefix: str, host_substr: str,
                            port: int = DEBUG_PORT) -> int:
    """Delete every live cookie whose name starts with `name_prefix` and whose
    domain contains `host_substr`. Returns the number deleted (0 if none), or -1
    if the debug port isn't reachable. Best-effort."""
    ws = _pick_target(port)
    if not ws:
        return -1
    try:
        cookies = _call(ws, "Storage.getCookies", {}).get("cookies", [])
    except Exception as exc:
        logger.info(f"CDP delete: getCookies failed: {exc}")
        return -1
    deleted = 0
    for c in cookies:
        name = c.get("name", "")
        domain = c.get("domain", "")
        if name.startswith(name_prefix) and host_substr in domain:
            try:
                _call(ws, "Network.deleteCookies",
                      {"name": name, "domain": domain, "path": c.get("path", "/")})
                deleted += 1
            except Exception as exc:
                logger.info(f"CDP delete {name}: {exc}")
    return deleted

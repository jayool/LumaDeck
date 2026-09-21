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
    # /json normally answers a LIST of target objects, but not always: while CEF
    # is starting (or if something else is on 8080) it can answer an object, and
    # iterating that yields its KEYS — strings, which have no .get. That raised
    # "'str' object has no attribute 'get'" outside the try above, so it escaped
    # _pick_target AND get_cookies and blew up the whole harvest poll, skipping
    # the on-disk fallback that would have found the session anyway.
    if not isinstance(data, list):
        return None
    targets = [t for t in data
               if isinstance(t, dict) and t.get("webSocketDebuggerUrl")]
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


def _call(ws_url: str, method: str, params: dict, timeout: float = _TIMEOUT) -> dict:
    u = urlparse(ws_url)
    path = u.path + (("?" + u.query) if u.query else "")
    s = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
    try:
        s.settimeout(timeout)
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


def list_targets(port: int = DEBUG_PORT) -> list:
    """Every target /json lists with a debugger URL (dicts), [] when the port
    isn't reachable or answers something that is not a list."""
    try:
        data = json.load(urlopen(f"http://127.0.0.1:{port}/json", timeout=3))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [t for t in data
            if isinstance(t, dict) and t.get("webSocketDebuggerUrl")]


def find_target(title: str | None = None, url: str | None = None,
                port: int = DEBUG_PORT) -> dict | None:
    """The first target whose title equals `title` and/or whose URL equals
    `url` (both compared as listed by /json), or None."""
    for t in list_targets(port):
        if title is not None and str(t.get("title", "")) != title:
            continue
        if url is not None and str(t.get("url", "")) != url:
            continue
        return t
    return None


def evaluate(ws_url: str, expression: str, timeout: float = _TIMEOUT,
             await_promise: bool = True):
    """Runtime.evaluate `expression` in the target and return its value (as
    returned by value). Raises RuntimeError when the expression throws or the
    protocol answers an error, ConnectionError/socket.timeout on transport."""
    res = _call(ws_url, "Runtime.evaluate",
                {"expression": expression, "returnByValue": True,
                 "awaitPromise": await_promise}, timeout=timeout)
    exc = res.get("exceptionDetails")
    if exc:
        text = exc.get("text") or ""
        e = exc.get("exception") or {}
        raise RuntimeError(f"{text} {e.get('description') or e.get('value') or ''}".strip())
    return (res.get("result") or {}).get("value")


def get_cookies(port: int = DEBUG_PORT):
    """Live CEF cookies (values already decrypted) as a list of dicts, or None if
    the debug port isn't reachable."""
    ws = _pick_target(port)
    if not ws:
        return None
    try:
        cookies = _call(ws, "Storage.getCookies", {}).get("cookies", [])
    except Exception as exc:
        logger.info(f"CDP get_cookies failed: {exc}")
        return None
    # Keep the documented contract (a list of dicts) so callers can .get() every
    # entry without guarding — see the note in _pick_target.
    if not isinstance(cookies, list):
        return None
    return [c for c in cookies if isinstance(c, dict)]


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


# --- off-screen BrowserView -------------------------------------------------

_MAIN_WINDOW_JS = (
    "((g.SteamUIStore&&g.SteamUIStore.WindowStore&&g.SteamUIStore.WindowStore.GamepadUIMainWindowInstance)"
    "||(g.DFL&&g.DFL.Router&&g.DFL.Router.WindowStore&&g.DFL.Router.WindowStore.GamepadUIMainWindowInstance))"
)

_CREATE_VIEW_JS = """(function(){try{
  var g=window;
  if(g[%(slot)s]){try{g[%(slot)s].Destroy();}catch(e){} g[%(slot)s]=undefined;}
  var main=%(main)s;
  if(!main||typeof main.CreateBrowserView!=='function')return 'unavailable: GamepadUIMainWindowInstance.CreateBrowserView not found';
  var view=main.CreateBrowserView(%(name)s);
  g[%(slot)s]=view;
  try{view.WIDTH=1280;view.HEIGHT=720;view.m_browserView.SetBounds(-10000,-10000,1280,720);view.m_browserView.SetVisible(true);}catch(e){}
  view.m_browserView.LoadURL(%(placeholder)s);
  return 'ok';
}catch(e){return 'error: '+String(e);}})()"""

_DESTROY_VIEW_JS = """(function(){try{
  var g=window;var view=g[%(slot)s];
  if(!view)return 'none';
  try{view.Destroy();}catch(e){}
  g[%(slot)s]=undefined;
  return 'ok';
}catch(e){return 'error: '+String(e);}})()"""

# What the page looks like right now: ready state, title, URL and whether a
# Cloudflare challenge is on screen (its title, its script host, its widget).
_PAGE_STATE_JS = """(function(){try{
  var h=String(document.documentElement&&document.documentElement.innerHTML||'').slice(0,40000);
  var cf=/Just a moment|chl_page|_cf_chl_opt|cf-turnstile|challenge-running|challenge-error-text/i.test(h);
  return JSON.stringify({rs:document.readyState,title:String(document.title||''),href:String(location.href||''),cf:cf});
}catch(e){return JSON.stringify({rs:'',title:'',href:'',cf:false,err:String(e)});}})()"""

_FETCH_JS = """fetch(%(path)s,{credentials:'include'}).then(function(r){
  return r.text().then(function(t){return JSON.stringify({s:r.status,t:t});});
})"""


def page_state(ws_url: str) -> dict:
    raw = evaluate(ws_url, _PAGE_STATE_JS, timeout=5, await_promise=False)
    try:
        d = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def fetch_in_page(ws_url: str, path: str, timeout: float = 25.0):
    """Run fetch(path) INSIDE the page (same origin, its cookies, its TLS —
    i.e. as the browser, which is what gets past Cloudflare). Returns
    (status, text). Raises on transport / JS errors."""
    raw = evaluate(ws_url, _FETCH_JS % {"path": json.dumps(path)},
                   timeout=timeout, await_promise=True)
    d = json.loads(raw) if isinstance(raw, str) else {}
    return int(d.get("s") or 0), str(d.get("t") or "")


def _norm_url(u: str) -> str:
    return (u or "").split("#", 1)[0].split("?", 1)[0].rstrip("/")


class HiddenView:
    """An off-screen Steam BrowserView we create through SharedJSContext, find
    on the debug port by a unique placeholder URL, navigate, and drive with
    Runtime.evaluate. It never replaces what the user sees (a visible
    NavigateToExternalWeb would pop the current page). Same mechanics SLSDeck
    uses for SteamDB. Always close() it — it is a live CEF view."""

    def __init__(self, name: str = "lumadeck_view", port: int = DEBUG_PORT):
        self.name = name
        self.port = port
        self.slot = f"LUMADECK_VIEW_{name}"
        self.ws: str | None = None

    def _shared_ws(self) -> str | None:
        t = find_target(title="SharedJSContext", port=self.port)
        return t["webSocketDebuggerUrl"] if t else None

    def open(self, url: str, wait_s: float = 8.0) -> str | None:
        """Create the view and start loading `url`. Returns None on success or
        the reason it could not (string)."""
        import time as _time
        shared = self._shared_ws()
        if not shared:
            return "SharedJSContext not found on the CEF debug port"
        placeholder = f"data:text/plain,{self.name}_{int(_time.time() * 1000)}_{os.urandom(4).hex()}"
        js = _CREATE_VIEW_JS % {"slot": json.dumps(self.slot), "main": _MAIN_WINDOW_JS,
                                "name": json.dumps(self.name), "placeholder": json.dumps(placeholder)}
        try:
            r = evaluate(shared, js, timeout=6, await_promise=False)
        except Exception as exc:
            return f"CreateBrowserView failed: {exc}"
        if r != "ok":
            return f"CreateBrowserView: {r}"
        deadline = _time.time() + wait_s
        target = None
        while _time.time() < deadline:
            target = find_target(url=placeholder, port=self.port)
            if target:
                break
            _time.sleep(0.2)
        if not target:
            self.close()
            return "the new view never appeared on the debug port"
        self.ws = target["webSocketDebuggerUrl"]
        try:
            _call(self.ws, "Page.setWebLifecycleState", {"state": "active"}, timeout=3)
        except Exception:
            pass
        try:
            _call(self.ws, "Page.navigate", {"url": url, "transitionType": "address_bar"}, timeout=6)
        except Exception as exc:
            self.close()
            return f"Page.navigate failed: {exc}"
        return None

    def wait_ready(self, wait_s: float = 20.0, expect_url: str | None = None) -> dict:
        """Poll the page until it is loaded, on `expect_url` (path compared,
        query ignored — a challenge bounces through the same URL with
        __cf_chl_tk params) and not showing a Cloudflare challenge. Returns
        page_state() plus "state": ready | challenge | timeout | error. A JS
        challenge solves itself in ~5 s and the page reloads; an interactive
        one (Turnstile) never does — that is 'challenge', and only a visible
        tab the user clicks through fixes it."""
        import time as _time
        deadline = _time.time() + wait_s
        last: dict = {}
        want = _norm_url(expect_url) if expect_url else None
        while _time.time() < deadline:
            try:
                st = page_state(self.ws or "")
            except Exception as exc:
                st = {"err": str(exc)}
            last = st
            href = str(st.get("href", ""))
            on_target = (_norm_url(href) == want) if want else ("steamdb.info" in href)
            if st.get("rs") == "complete" and not st.get("cf") and on_target:
                return st | {"state": "ready"}
            _time.sleep(0.5)
        if last.get("cf"):
            return last | {"state": "challenge"}
        return last | {"state": "error" if last.get("err") else "timeout"}

    def navigate(self, url: str, wait_s: float = 20.0) -> dict:
        """Load `url` in the view (a real navigation, so a JS challenge can
        run and solve itself) and wait for it. Returns wait_ready()'s dict."""
        if not self.ws:
            return {"state": "error", "err": "view not open"}
        try:
            _call(self.ws, "Page.navigate", {"url": url, "transitionType": "address_bar"}, timeout=6)
        except Exception as exc:
            return {"state": "error", "err": f"Page.navigate failed: {exc}"}
        return self.wait_ready(wait_s, expect_url=url)

    def html(self) -> str:
        """The current document's HTML, as the browser has it."""
        if not self.ws:
            raise RuntimeError("view not open")
        v = evaluate(self.ws, "document.documentElement.outerHTML", timeout=15, await_promise=False)
        return v if isinstance(v, str) else ""

    def fetch(self, path: str, timeout: float = 25.0):
        if not self.ws:
            raise RuntimeError("view not open")
        return fetch_in_page(self.ws, path, timeout)

    def close(self) -> None:
        shared = self._shared_ws()
        self.ws = None
        if not shared:
            return
        try:
            evaluate(shared, _DESTROY_VIEW_JS % {"slot": json.dumps(self.slot)},
                     timeout=4, await_promise=False)
        except Exception as exc:
            logger.info(f"CDP HiddenView close: {exc}")

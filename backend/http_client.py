"""Shared async HTTP client using Python stdlib (no external deps).

Provides a drop-in replacement for the previous httpx-based client.
All public functions keep the same signatures so callers need no changes.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, AsyncIterator, Dict, Optional

from config import HTTP_TIMEOUT_SECONDS, USER_AGENT

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# ---------------------------------------------------------------------------
# Response wrappers
# ---------------------------------------------------------------------------

class NativeResponse:
    """Mimics the subset of httpx.Response used by the backend."""

    def __init__(self, status_code: int, headers: Dict[str, str], data: bytes, url: str):
        self.status_code = status_code
        self.headers = headers
        self._data = data
        self.url = url

    @property
    def content(self) -> bytes:
        """Raw response bytes (httpx.Response.content parity)."""
        return self._data

    @property
    def text(self) -> str:
        return self._data.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self._data)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise urllib.error.HTTPError(
                self.url, self.status_code,
                f"HTTP {self.status_code}", self.headers, None,  # type: ignore[arg-type]
            )


class _ErrorResponseAdapter:
    """Adapts an HTTPError to look like a normal urlopen response."""

    def __init__(self, exc: urllib.error.HTTPError):
        self._exc = exc
        self.status: int = exc.code
        self.url: str = exc.url or ""

    def getheaders(self) -> list:
        if self._exc.headers:
            return list(self._exc.headers.items())
        return []

    def read(self, amt: int = -1) -> bytes:
        return self._exc.read(amt) if amt != -1 else self._exc.read()

    def close(self) -> None:
        self._exc.close()


class _StreamResponse:
    """Wraps an open urllib response for async chunked reading."""

    def __init__(self, response: Any):
        self._resp = response
        self.status_code: int = response.status
        self.headers: Dict[str, str] = {k: v for k, v in response.getheaders()}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise urllib.error.HTTPError(
                self._resp.url, self.status_code,
                f"HTTP {self.status_code}", self.headers, None,  # type: ignore[arg-type]
            )

    async def aiter_bytes(self, chunk_size: int = 65536) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        while True:
            chunk = await loop.run_in_executor(None, self._resp.read, chunk_size)
            if not chunk:
                break
            yield chunk


class _StreamContext:
    """Async context manager returned by NativeAsyncClient.stream()."""

    def __init__(self, url: str, headers: Dict[str, str], timeout: float, ssl_ctx: ssl.SSLContext):
        self._url = url
        self._headers = headers
        self._timeout = timeout
        self._ssl_ctx = ssl_ctx
        self._resp: Any = None

    async def __aenter__(self) -> _StreamResponse:
        loop = asyncio.get_running_loop()
        self._resp = await loop.run_in_executor(None, self._open)
        return _StreamResponse(self._resp)

    def _open(self) -> Any:
        req = urllib.request.Request(self._url, method="GET")
        req.add_header("User-Agent", USER_AGENT)
        for k, v in self._headers.items():
            req.add_header(k, v)
        ctx = self._ssl_ctx if self._url.startswith("https") else None
        try:
            return urllib.request.urlopen(req, timeout=self._timeout, context=ctx)
        except urllib.error.HTTPError as exc:
            # Wrap so callers can inspect status_code without raising
            return _ErrorResponseAdapter(exc)

    async def __aexit__(self, *args: Any) -> None:
        if self._resp:
            self._resp.close()


# ---------------------------------------------------------------------------
# SSL context helper
# ---------------------------------------------------------------------------

# Decky uses PyInstaller-bundled Python 3.11 which may not find system CA certs.
_SYSTEM_CERT_FILES = [
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/cert.pem",
    "/etc/ca-certificates/extracted/tls-ca-bundle.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/usr/share/ca-certificates/mozilla/",
    "/etc/ssl/certs/",
]


def _make_ssl_context() -> ssl.SSLContext:
    """Create SSL context, loading system CA certs if the default bundle fails."""
    ctx = ssl.create_default_context()
    # Test if default context can actually verify (PyInstaller may have empty bundle)
    try:
        ctx.load_default_certs()
    except Exception:
        pass

    # Try certifi as additional source (if installed)
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
        logger.info(f"SSL: loaded certs from certifi ({certifi.where()})")
        return ctx
    except Exception:
        pass

    # Explicitly load system cert files to cover PyInstaller edge cases
    for cert_path in _SYSTEM_CERT_FILES:
        if os.path.isfile(cert_path):
            try:
                ctx.load_verify_locations(cafile=cert_path)
                logger.info(f"SSL: loaded certs from {cert_path}")
                return ctx
            except Exception:
                continue
        elif os.path.isdir(cert_path):
            try:
                ctx.load_verify_locations(capath=cert_path)
                logger.info(f"SSL: loaded certs from directory {cert_path}")
                return ctx
            except Exception:
                continue

    # Try Python's own default verify paths as last resort before disabling
    try:
        paths = ssl.get_default_verify_paths()
        if paths.cafile and os.path.isfile(paths.cafile):
            ctx.load_verify_locations(cafile=paths.cafile)
            logger.info(f"SSL: loaded certs from default path {paths.cafile}")
            return ctx
        if paths.capath and os.path.isdir(paths.capath):
            ctx.load_verify_locations(capath=paths.capath)
            logger.info(f"SSL: loaded certs from default dir {paths.capath}")
            return ctx
    except Exception:
        pass

    # Absolute last resort — disable verification with loud warning
    logger.warning("SSL: SECURITY WARNING — no system CA certs found, disabling verification. HTTPS connections are vulnerable to MITM attacks.")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class NativeAsyncClient:
    """Async HTTP client backed by Python stdlib urllib."""

    def __init__(self, timeout: float = 30):
        self._timeout = timeout
        self._ssl_ctx = _make_ssl_context()

    # -- GET ----------------------------------------------------------------

    async def get(
        self, url: str, *, timeout: float | None = None,
        follow_redirects: bool = True, headers: Dict[str, str] | None = None,
        **_: Any,
    ) -> NativeResponse:
        t = timeout if timeout is not None else self._timeout
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_request, "GET", url, t, follow_redirects, headers or {},
        )

    # -- HEAD ---------------------------------------------------------------

    async def head(
        self, url: str, *, timeout: float | None = None,
        follow_redirects: bool = True, **_: Any,
    ) -> NativeResponse:
        t = timeout if timeout is not None else self._timeout
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_request, "HEAD", url, t, follow_redirects, {},
        )

    # -- STREAM -------------------------------------------------------------

    def stream(
        self, method: str, url: str, *,
        follow_redirects: bool = True, timeout: float | None = None,
        headers: Dict[str, str] | None = None, **_: Any,
    ) -> _StreamContext:
        t = timeout if timeout is not None else self._timeout
        return _StreamContext(url, headers or {}, t, self._ssl_ctx)

    # -- CLOSE --------------------------------------------------------------

    async def aclose(self) -> None:
        pass  # stdlib needs no teardown

    # -- internal -----------------------------------------------------------

    def _sync_request(
        self, method: str, url: str, timeout: float,
        follow_redirects: bool, headers: Dict[str, str],
    ) -> NativeResponse:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", USER_AGENT)
        for k, v in headers.items():
            req.add_header(k, v)
        ctx = self._ssl_ctx if url.startswith("https") else None
        try:
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
            data = resp.read() if method != "HEAD" else b""
            return NativeResponse(resp.status, {k: v for k, v in resp.getheaders()}, data, resp.url)
        except urllib.error.HTTPError as exc:
            data = b""
            try:
                data = exc.read()
            except Exception:
                pass
            hdrs = {k: v for k, v in exc.headers.items()} if exc.headers else {}
            return NativeResponse(exc.code, hdrs, data, url)


# ---------------------------------------------------------------------------
# Public singleton (same API as before)
# ---------------------------------------------------------------------------

_CLIENT: Optional[NativeAsyncClient] = None


async def ensure_http_client(context: str = "") -> NativeAsyncClient:
    global _CLIENT
    if _CLIENT is None:
        prefix = f"{context}: " if context else ""
        logger.info(f"{prefix}Initializing native HTTP client...")
        _CLIENT = NativeAsyncClient(timeout=HTTP_TIMEOUT_SECONDS)
        logger.info(f"{prefix}Native HTTP client ready")
    return _CLIENT


async def get_http_client() -> NativeAsyncClient:
    return await ensure_http_client()


async def close_http_client(context: str = "") -> None:
    global _CLIENT
    if _CLIENT is None:
        return
    try:
        await _CLIENT.aclose()
    except Exception:
        pass
    finally:
        _CLIENT = None
        prefix = f"{context}: " if context else ""
        logger.info(f"{prefix}HTTP client closed")

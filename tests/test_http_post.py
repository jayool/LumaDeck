"""NativeAsyncClient.post — the method whose absence caused issue #42.

The native client replaced an httpx one but never got a `post`. The single
caller (the LuaTools token refresh, luatools_auth.py) therefore raised
AttributeError on every attempt; the refresh's `except Exception` swallowed it
and fell back to the expired access token. Since a LuaTools access token lives
exactly 1 hour, every user's session died after an hour and stayed dead.

These tests run against a real loopback HTTP server, so they exercise the actual
urllib request rather than a mock of it.

    python -m unittest discover -s tests
"""
import asyncio
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import http_client  # noqa: E402


class _Echo(BaseHTTPRequestHandler):
    """Echoes back what it received, so the test can assert on the real wire."""

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        payload = json.dumps({
            "method": self.command,
            "path": self.path,
            "content_type": self.headers.get("Content-Type"),
            "apikey": self.headers.get("apikey"),
            "body": body.decode(),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class PostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), _Echo)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.client = http_client.NativeAsyncClient(timeout=10)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, *args, **kwargs):
        return asyncio.run(self.client.post(*args, **kwargs))

    def test_post_exists(self):
        """The bug itself: the method has to be there and be callable."""
        self.assertTrue(callable(getattr(http_client.NativeAsyncClient, "post", None)))

    def test_sends_json_body_and_content_type(self):
        """Shape of the LuaTools refresh call: a JSON body plus an apikey header."""
        r = self._post(f"{self.url}/auth/v1/token",
                       headers={"apikey": "anon-key"},
                       json={"refresh_token": "abc123"})
        self.assertEqual(r.status_code, 200)
        got = r.json()
        self.assertEqual(got["method"], "POST")
        self.assertEqual(json.loads(got["body"]), {"refresh_token": "abc123"})
        self.assertEqual(got["content_type"], "application/json")
        self.assertEqual(got["apikey"], "anon-key")

    def test_params_are_merged_into_the_query_string(self):
        """The refresh URL carries ?grant_type=refresh_token; params must not
        replace a query string that's already on the URL."""
        r = self._post(f"{self.url}/token?grant_type=refresh_token",
                       params={"extra": "1"}, json={})
        path = r.json()["path"]
        self.assertIn("grant_type=refresh_token", path)
        self.assertIn("extra=1", path)

    def test_raw_data_body_is_sent_unwrapped(self):
        r = self._post(f"{self.url}/x", data="raw=1",
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        got = r.json()
        self.assertEqual(got["body"], "raw=1")
        self.assertEqual(got["content_type"], "application/x-www-form-urlencoded")

    def test_error_status_is_returned_not_raised(self):
        """A 401 must come back as a response so the refresh can log the code
        and keep the old token, exactly as `get` behaves."""
        r = asyncio.run(self.client.get(f"{self.url}/nope"))
        self.assertEqual(r.status_code, 401)

    def test_get_still_sends_no_body(self):
        """Guard the shared _sync_request: adding an optional body must not turn
        every GET into a request with an empty payload."""
        import urllib.request
        seen = {}
        real = urllib.request.Request

        def spy(url, *a, **kw):
            seen["data"] = kw.get("data", (a[0] if a else None))
            return real(url, *a, **kw)

        urllib.request.Request = spy
        try:
            asyncio.run(self.client.get(f"{self.url}/nope"))
        finally:
            urllib.request.Request = real
        self.assertIsNone(seen["data"])


if __name__ == "__main__":
    unittest.main()

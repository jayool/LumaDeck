"""LuaTools session lifecycle — the defects behind issue #42.

Three separate bugs met in the same symptom ("session timed out", nothing to do
about it):

  * the refresh could never run (no POST on the client) — covered by
    tests/test_http_post.py;
  * `get_luatools_status` answered "does the session file exist", so Settings
    said "Connected" to a user whose token was three weeks dead;
  * the session was mirrored into the settings credential store on every save
    but never restored, so each LumaDeck update logged the user out.

    python -m unittest discover -s tests
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import luatools_auth  # noqa: E402


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class SessionTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luatools_test_")
        patcher = mock.patch.object(
            luatools_auth, "data_path", lambda name: os.path.join(self.tmp, name))
        patcher.start()
        self.addCleanup(patcher.stop)
        # _save_session mirrors into the settings store; that path isn't under test
        # here and would touch the real filesystem.
        mirror = mock.patch("api_manifest._mirror_cred", lambda **kw: None)
        mirror.start()
        self.addCleanup(mirror.stop)

    def write_session(self, **fields):
        session = {"access_token": "tok", "refresh_token": "ref",
                   "expires_at": 4102444800}  # year 2100
        session.update(fields)
        luatools_auth._save_session(session)
        return session

    def read_session(self):
        return luatools_auth._load_session()

    def status(self):
        return asyncio.run(luatools_auth.get_luatools_status())


class StatusHonestyTest(SessionTestBase):
    """`connected` must mean "I hold a usable token", not "a file exists"."""

    def test_no_session_is_not_connected(self):
        s = self.status()
        self.assertFalse(s["connected"])
        self.assertFalse(s["expired"])

    def test_live_token_is_connected_without_touching_the_network(self):
        self.write_session()
        with mock.patch.object(luatools_auth, "ensure_http_client") as http:
            s = self.status()
        http.assert_not_called()  # far-future expires_at → no refresh
        self.assertTrue(s["connected"])
        self.assertFalse(s["expired"])

    def test_stale_token_that_refreshes_is_connected(self):
        self.write_session(expires_at=1)
        client = mock.AsyncMock()
        client.post.return_value = _Resp(200, {"access_token": "fresh",
                                               "refresh_token": "ref2",
                                               "expires_in": 3600})
        with mock.patch.object(luatools_auth, "ensure_http_client",
                               mock.AsyncMock(return_value=client)):
            s = self.status()
        self.assertTrue(s["connected"])
        self.assertFalse(s["expired"])
        self.assertEqual(self.read_session()["access_token"], "fresh")

    def test_refresh_200_without_expires_at_derives_one(self):
        """Supabase's token endpoint returns `expires_in`, not `expires_at` — the
        JS client adds the latter. Saving the reply verbatim would leave the new
        session looking already-stale and refresh on every single call."""
        self.write_session(expires_at=1)
        client = mock.AsyncMock()
        client.post.return_value = _Resp(200, {"access_token": "fresh",
                                               "refresh_token": "ref2",
                                               "expires_in": 3600})
        with mock.patch.object(luatools_auth, "ensure_http_client",
                               mock.AsyncMock(return_value=client)):
            self.status()
        saved = self.read_session()
        import time
        self.assertGreater(saved["expires_at"], time.time() + 3000)

    def test_dead_refresh_token_reports_expired_not_connected(self):
        """THE #42 SYMPTOM: this is the state that used to render 'Connected'."""
        self.write_session(expires_at=1)
        client = mock.AsyncMock()
        client.post.return_value = _Resp(400, {})
        with mock.patch.object(luatools_auth, "ensure_http_client",
                               mock.AsyncMock(return_value=client)):
            s = self.status()
        self.assertFalse(s["connected"])
        self.assertTrue(s["expired"])

    def test_network_failure_does_not_claim_expired(self):
        """An offline Deck must not nag for a re-login it can't complete: only a
        definitive rejection (4xx / 401) counts as expired."""
        self.write_session(expires_at=1)
        client = mock.AsyncMock()
        client.post.side_effect = OSError("network is unreachable")
        with mock.patch.object(luatools_auth, "ensure_http_client",
                               mock.AsyncMock(return_value=client)):
            s = self.status()
        self.assertFalse(s["expired"])

    def test_server_error_does_not_claim_expired(self):
        self.write_session(expires_at=1)
        client = mock.AsyncMock()
        client.post.return_value = _Resp(503, {})
        with mock.patch.object(luatools_auth, "ensure_http_client",
                               mock.AsyncMock(return_value=client)):
            s = self.status()
        self.assertFalse(s["expired"])


class RejectionMarkTest(SessionTestBase):
    """A 401 marks the session, it does not delete it — a single 401 can be
    Cloudflare, and deleting would also bin a refresh token that may still work."""

    def test_mark_keeps_the_session_file_and_the_refresh_token(self):
        self.write_session()
        luatools_auth._mark_session_rejected()
        saved = self.read_session()
        self.assertIsNotNone(saved)
        self.assertEqual(saved["refresh_token"], "ref")
        self.assertTrue(saved[luatools_auth._REJECTED_KEY])

    def test_mark_survives_a_reload(self):
        self.write_session()
        luatools_auth._mark_session_rejected()
        self.assertTrue(self.status()["expired"])

    def test_a_working_call_clears_the_mark(self):
        self.write_session()
        luatools_auth._mark_session_rejected()
        luatools_auth._clear_session_rejected()
        self.assertNotIn(luatools_auth._REJECTED_KEY, self.read_session())
        self.assertTrue(self.status()["connected"])

    def test_marking_with_no_session_is_a_no_op(self):
        luatools_auth._mark_session_rejected()
        self.assertIsNone(self.read_session())


class RestoreSessionTest(SessionTestBase):
    """The mirror was written on every save and read back never."""

    def test_restores_when_the_data_dir_was_wiped(self):
        raw = json.dumps({"access_token": "tok", "refresh_token": "ref"})
        self.assertTrue(luatools_auth.restore_session(raw))
        self.assertEqual(self.read_session()["access_token"], "tok")

    def test_never_overwrites_a_live_session(self):
        """A session in place is always newer than the mirror; restoring over it
        could hand back an already-spent refresh token."""
        self.write_session(access_token="current")
        self.assertFalse(luatools_auth.restore_session(
            json.dumps({"access_token": "older", "refresh_token": "old"})))
        self.assertEqual(self.read_session()["access_token"], "current")

    def test_rejects_junk(self):
        for raw in ("", "not json", "[]", '"a string"', "{}",
                    '{"refresh_token": "ref"}'):
            with self.subTest(raw=raw):
                self.assertFalse(luatools_auth.restore_session(raw))
                self.assertIsNone(self.read_session())


class RestoreWiringTest(unittest.TestCase):
    """restore_credentials_from_settings must actually call it — the whole defect
    was that the LuaTools branch was missing from that function."""

    def test_credential_restore_reaches_luatools(self):
        import api_manifest
        with mock.patch.object(api_manifest, "_read_cred_store",
                               lambda: {"luatools_session": '{"access_token": "x"}'}), \
             mock.patch.object(luatools_auth, "restore_session",
                               return_value=True) as restore:
            api_manifest.restore_credentials_from_settings()
        restore.assert_called_once_with('{"access_token": "x"}')


class HarvestRobustnessTest(unittest.TestCase):
    """`/json` answering an object instead of a list raised "'str' object has no
    attribute 'get'" out of _pick_target, which escaped get_cookies too and killed
    the whole harvest poll — including the on-disk fallback. Seen 3x in a real log."""

    def test_object_response_returns_none_instead_of_raising(self):
        import cef_cdp
        import io
        with mock.patch.object(cef_cdp, "urlopen",
                               lambda *a, **k: io.BytesIO(b'{"error": "nope"}')):
            self.assertIsNone(cef_cdp._pick_target(8080))

    def test_scalar_response_returns_none_instead_of_raising(self):
        """A number or a bare string isn't even iterable — this is the case the
        list guard covers that the per-entry dict check can't."""
        import cef_cdp
        import io
        with mock.patch.object(cef_cdp, "urlopen",
                               lambda *a, **k: io.BytesIO(b'5')):
            self.assertIsNone(cef_cdp._pick_target(8080))

    def test_list_with_junk_entries_is_filtered(self):
        import cef_cdp
        import io
        body = b'["junk", {"type": "page", "webSocketDebuggerUrl": "ws://x/1"}]'
        with mock.patch.object(cef_cdp, "urlopen",
                               lambda *a, **k: io.BytesIO(body)):
            self.assertEqual(cef_cdp._pick_target(8080), "ws://x/1")


if __name__ == "__main__":
    unittest.main()

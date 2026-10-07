"""Ryuu as a first-class provider (2026-10-07).

- Search by name uses Steam's store search: no credential. Hubcap's /search
  needed a valid Hubcap key and was the one feature a Ryuu-only setup lacked.
- A download that Ryuu rejects (401/403 with a cookie) ends in its own
  terminal state, so the game page can say "log in again" instead of
  "Not available on any API"; both credential flags travel.
- The credential status checks the Ryuu session live (home page GET, once an
  hour per cookie): a session Ryuu dropped early reads as expired even if the
  cookie's date is fine.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import api_manifest  # noqa: E402
import downloads  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def in_days(n):
    """What the cookie importer writes: naive UTC ISO-8601 (no offset)."""
    from datetime import datetime, timedelta
    return (datetime.utcnow() + timedelta(days=n)).replace(microsecond=0).isoformat()


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    async def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


class StoreSearch(unittest.TestCase):
    STORE = {"total": 4, "items": [
        {"type": "app", "id": 1942280, "name": "Brotato"},
        {"type": "app", "id": 2178320, "name": "Brotato Soundtrack"},
        {"type": "app", "id": 2311330, "name": "Brotato Demo"},
        {"type": "bundle", "id": 999, "name": "Brotato Bundle"},
    ]}

    def test_results_come_from_the_store_without_any_key(self):
        client = FakeClient(FakeResp(200, self.STORE))

        async def fake_client(ctx=""):
            return client
        with mock.patch.object(api_manifest, "ensure_http_client", fake_client), \
             mock.patch.object(api_manifest, "_get_hubcap_key", lambda: ""):
            res = run(api_manifest.search_games("brotato"))
        self.assertTrue(res["success"], res)
        self.assertEqual(res["results"], [{"appid": 1942280, "name": "Brotato"}])
        url, kw = client.calls[0]
        self.assertTrue(url.startswith("https://store.steampowered.com/api/storesearch/?"))
        self.assertIn("term=brotato", url)
        self.assertNotIn("Authorization", (kw.get("headers") or {}))

    def test_short_query_is_refused_before_any_request(self):
        res = run(api_manifest.search_games("b"))
        self.assertFalse(res["success"])

    def test_store_error_is_reported(self):
        async def fake_client(ctx=""):
            return FakeClient(FakeResp(503, {}))
        with mock.patch.object(api_manifest, "ensure_http_client", fake_client):
            res = run(api_manifest.search_games("brotato"))
        self.assertFalse(res["success"])
        self.assertIn("503", res["error"])

    def test_old_name_still_answers(self):
        async def fake_client(ctx=""):
            return FakeClient(FakeResp(200, self.STORE))
        with mock.patch.object(api_manifest, "ensure_http_client", fake_client):
            res = run(api_manifest.search_hubcap("brotato"))
        self.assertTrue(res["success"])


class TerminalFailure(unittest.TestCase):
    def test_generic_when_no_credential_was_rejected(self):
        st = downloads._terminal_failure(False, False)
        self.assertEqual(st["error"], "Not available on any API")
        self.assertNotIn("errorCode", st)
        self.assertFalse(st["hubcapExpired"])
        self.assertFalse(st["ryuuExpired"])

    def test_ryuu_rejection_has_its_own_code(self):
        st = downloads._terminal_failure(False, True)
        self.assertEqual(st["errorCode"], "ryuu_session_expired")
        self.assertTrue(st["ryuuExpired"])
        self.assertFalse(st["hubcapExpired"])

    def test_both_rejected_both_flags_travel(self):
        st = downloads._terminal_failure(True, True)
        self.assertEqual(st["errorCode"], "hubcap_key_expired")
        self.assertTrue(st["hubcapExpired"])
        self.assertTrue(st["ryuuExpired"])


class LiveSessionCheck(unittest.TestCase):
    def setUp(self):
        api_manifest._ryuu_live_cache.update({"value": None, "at": 0.0, "logged_in": None})
        self.checks = []

    def patch_check(self, verdict):
        import ryuu_cookie

        def check(value):
            self.checks.append(value)
            return verdict
        p = mock.patch.object(ryuu_cookie, "_session_logged_in", check)
        p.start()
        self.addCleanup(p.stop)

    def test_bare_value_is_extracted_from_the_stored_cookie(self):
        self.assertEqual(api_manifest._ryuu_cookie_value("session=abc; other=1"), "abc")
        self.assertEqual(api_manifest._ryuu_cookie_value("abc"), "abc")
        self.assertEqual(api_manifest._ryuu_cookie_value(""), "")

    def test_one_check_per_cookie_per_hour(self):
        self.patch_check(True)
        self.assertIs(run(api_manifest.ryuu_session_live("session=abc")), True)
        self.assertIs(run(api_manifest.ryuu_session_live("session=abc")), True)
        self.assertEqual(self.checks, ["abc"])
        # a new cookie is checked again
        self.assertIs(run(api_manifest.ryuu_session_live("session=def")), True)
        self.assertEqual(self.checks, ["abc", "def"])

    def test_network_failure_is_not_cached(self):
        self.patch_check(None)
        self.assertIsNone(run(api_manifest.ryuu_session_live("session=abc")))
        self.assertIsNone(run(api_manifest.ryuu_session_live("session=abc")))
        self.assertEqual(len(self.checks), 2)

    def test_download_rejection_marks_the_session_dead(self):
        self.patch_check(True)
        with mock.patch.object(api_manifest, "load_ryu_cookie", lambda: "session=abc"):
            api_manifest.note_ryuu_rejected()
        self.assertIs(run(api_manifest.ryuu_session_live("session=abc")), False)
        self.assertEqual(self.checks, [])

    def _status(self, verdict, iso):
        self.patch_check(verdict)
        with mock.patch.object(api_manifest, "_get_hubcap_key", lambda: ""), \
             mock.patch.object(api_manifest, "load_ryu_cookie", lambda: "session=abc"), \
             mock.patch.object(api_manifest, "load_ryu_cookie_expiry", lambda: iso):
            return run(api_manifest.get_credential_status())["ryuu"]

    def test_dead_session_reads_expired_even_with_a_future_date(self):
        ryuu = self._status(False, in_days(20))
        self.assertEqual(ryuu["state"], "expired")
        self.assertIs(ryuu["live"], False)

    def test_live_session_without_a_date_reads_ok(self):
        ryuu = self._status(True, "")
        self.assertEqual(ryuu["state"], "ok")
        self.assertIsNone(ryuu["days_left"])

    def test_unreachable_check_keeps_the_date_verdict(self):
        ryuu = self._status(None, in_days(20))
        self.assertEqual(ryuu["state"], "ok")
        self.assertIsNone(ryuu["live"])


if __name__ == "__main__":
    unittest.main()

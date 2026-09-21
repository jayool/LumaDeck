"""steamdb_reader.py: answer classification, cache TTL, and the read order
cache -> direct -> browser with the Cloudflare challenge handling.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import steamdb_reader as sr  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "steamdb")
with open(os.path.join(FIX, "PatchnotesRSS_2545360.xml"), encoding="utf-8") as _f:
    RSS = _f.read()

CHALLENGE_403 = """<!DOCTYPE html><html><head><title>Just a moment...</title>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></head>
<body><div id="challenge-running"></div></body></html>"""


def run(coro):
    return asyncio.run(coro)


class Classify(unittest.TestCase):
    def test_feed_is_ok(self):
        self.assertEqual(sr.classify(200, RSS), "ok")

    def test_cloudflare_403_is_challenge(self):
        self.assertEqual(sr.classify(403, CHALLENGE_403), "challenge")

    def test_challenge_markers_win_even_on_200(self):
        self.assertEqual(sr.classify(200, "<html><script src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1'>"), "challenge")

    def test_bot_management_script_on_a_normal_page_is_not_a_challenge(self):
        page = ("<html><head><title>Balatro · SteamDB</title></head><body><table><tr></tr></table>"
                "<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></body></html>")
        self.assertEqual(sr.classify(200, page), "ok")

    def test_http_error_and_empty(self):
        self.assertEqual(sr.classify(500, "<html>boom</html>"), "http_error")
        self.assertEqual(sr.classify(404, ""), "http_error")
        self.assertEqual(sr.classify(200, "   "), "empty")

    def test_paths(self):
        self.assertEqual(sr.feed_path(2379780), "/api/PatchnotesRSS/?appid=2379780")
        self.assertEqual(sr.depot_path(2379781), "/depot/2379781/manifests/")
        self.assertEqual(sr.build_path(17459173), "/patchnotes/17459173/")
        self.assertEqual(sr.app_url(2379780), "https://steamdb.info/app/2379780/")


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "steamdb")
        self.t = 1000.0
        self.now = lambda: self.t

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_and_ttl(self):
        path = sr.feed_path(1)
        self.assertIsNone(sr.cache_get(path, 3600, self.dir, self.now))
        sr.cache_put(path, 200, RSS, self.dir, self.now)
        self.assertEqual(sr.cache_get(path, 3600, self.dir, self.now), (200, RSS))
        self.t += 3601
        self.assertIsNone(sr.cache_get(path, 3600, self.dir, self.now))
        self.assertEqual(sr.cache_get(path, 7200, self.dir, self.now), (200, RSS))

    def test_one_file_per_path(self):
        a, b = sr._cache_file(self.dir, sr.depot_path(1)), sr._cache_file(self.dir, sr.depot_path(2))
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith(".json"))
        self.assertNotIn("/", os.path.basename(a)[:-5].replace("_", ""))

    def test_corrupt_file_is_a_miss(self):
        os.makedirs(self.dir)
        with open(sr._cache_file(self.dir, "/x/"), "w") as f:
            f.write("{not json")
        self.assertIsNone(sr.cache_get("/x/", 10, self.dir, self.now))


class FakeView:
    """Stands in for cef_cdp.HiddenView / ExistingView."""

    def __init__(self, answers, state="ready"):
        self.answers = answers          # path -> (status, text) or Exception
        self.state = state
        self.opened = []
        self.closed = 0
        self.fetched = []

    def open(self, url, wait_s=8.0):
        self.opened.append(url)
        return None

    def wait_ready(self, wait_s=20.0):
        return {"state": self.state, "title": "Just a moment..." if self.state == "challenge" else "SteamDB"}

    def fetch(self, path, timeout=25.0):
        self.fetched.append(path)
        a = self.answers[path]
        if isinstance(a, Exception):
            raise a
        return a

    def close(self):
        self.closed += 1


class ReadOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "steamdb")
        self.t = 5000.0
        self.now = lambda: self.t
        sr._direct_blocked_until = 0.0
        self.direct_calls = []

    def tearDown(self):
        sr._direct_blocked_until = 0.0
        self.tmp.cleanup()

    def direct(self, status, text):
        async def f(url):
            self.direct_calls.append(url)
            return status, text
        return f

    def reader(self, direct, view):
        return sr.Reader(2379780, cache_dir=self.dir, direct=direct,
                         view_factory=lambda appid: (view, False), now=self.now)

    def test_direct_ok_is_used_and_cached(self):
        view = FakeView({})
        r = self.reader(self.direct(200, RSS), view)
        f = run(r.get(sr.feed_path(2379780), sr.TTL_FEED))
        self.assertEqual((f.outcome, f.transport), ("ok", "direct"))
        self.assertEqual(self.direct_calls, ["https://steamdb.info/api/PatchnotesRSS/?appid=2379780"])
        self.assertEqual(view.opened, [])
        # second read: cache, no network
        f2 = run(r.get(sr.feed_path(2379780), sr.TTL_FEED))
        self.assertEqual((f2.outcome, f2.transport), ("ok", "cache"))
        self.assertEqual(len(self.direct_calls), 1)
        run(r.close())

    def test_challenge_on_direct_falls_to_browser_and_backs_off(self):
        path = sr.feed_path(2379780)
        view = FakeView({path: (200, RSS), sr.depot_path(2379781): (200, "<table><tr></tr></table>")})
        r = self.reader(self.direct(403, CHALLENGE_403), view)
        f = run(r.get(path, sr.TTL_FEED))
        self.assertEqual((f.outcome, f.transport), ("ok", "browser"))
        self.assertEqual(view.opened, ["https://steamdb.info/app/2379780/"])
        # the failed direct attempt is on record, then the browser one
        self.assertEqual([x.transport for x in r.fetches], ["direct", "browser"])
        self.assertEqual(r.fetches[0].outcome, "challenge")
        # direct is now skipped for an hour: the next read goes straight to the view
        f2 = run(r.get(sr.depot_path(2379781), sr.TTL_DEPOT))
        self.assertEqual((f2.outcome, f2.transport), ("ok", "browser"))
        self.assertEqual(len(self.direct_calls), 1)
        self.assertEqual(view.fetched, [path, sr.depot_path(2379781)])
        self.assertFalse(r.needs_user)
        run(r.close())
        self.assertEqual(view.closed, 1)
        # and the good answers were cached
        self.assertIsNotNone(sr.cache_get(path, sr.TTL_FEED, self.dir, self.now))

    def test_interactive_challenge_reports_needs_user_and_caches_nothing(self):
        path = sr.feed_path(2379780)
        view = FakeView({path: (200, RSS)}, state="challenge")
        r = self.reader(self.direct(403, CHALLENGE_403), view)
        f = run(r.get(path, sr.TTL_FEED))
        self.assertEqual((f.outcome, f.transport), ("needs_user", "browser"))
        self.assertTrue(r.needs_user)
        self.assertEqual(view.fetched, [])
        self.assertEqual(view.closed, 1)
        self.assertIsNone(sr.cache_get(path, sr.TTL_FEED, self.dir, self.now))
        # a second read in the same session does not open the view again
        f2 = run(r.get(sr.depot_path(1), sr.TTL_DEPOT))
        self.assertEqual(f2.outcome, "needs_user")
        self.assertEqual(len(view.opened), 1)
        run(r.close())

    def test_challenge_answered_to_the_in_page_fetch_is_needs_user(self):
        path = sr.feed_path(2379780)
        view = FakeView({path: (403, CHALLENGE_403)})
        r = self.reader(self.direct(403, CHALLENGE_403), view)
        f = run(r.get(path, sr.TTL_FEED))
        self.assertEqual(f.outcome, "needs_user")
        run(r.close())

    def test_http_error_from_browser_is_reported_not_cached(self):
        path = sr.depot_path(999)
        view = FakeView({path: (404, "<html>nope</html>")})
        r = sr.Reader(1, cache_dir=self.dir, use_direct=False,
                      view_factory=lambda appid: (view, False), now=self.now)
        f = run(r.get(path, sr.TTL_DEPOT))
        self.assertEqual((f.outcome, f.status, f.transport), ("http_error", 404, "browser"))
        self.assertIsNone(sr.cache_get(path, sr.TTL_DEPOT, self.dir, self.now))
        run(r.close())

    def test_view_open_failure_is_an_error_with_reason(self):
        class Broken(FakeView):
            def open(self, url, wait_s=8.0):
                return "SharedJSContext not found on the CEF debug port"
        view = Broken({})
        r = sr.Reader(1, cache_dir=self.dir, use_direct=False,
                      view_factory=lambda appid: (view, False), now=self.now)
        f = run(r.get(sr.feed_path(1), sr.TTL_FEED))
        self.assertEqual(f.outcome, "error")
        self.assertIn("SharedJSContext", f.error)
        self.assertEqual(f.summary()["bytes"], 0)
        run(r.close())


if __name__ == "__main__":
    unittest.main()

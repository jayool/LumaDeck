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
    """Stands in for cef_cdp.HiddenView. `answers` maps a path to
    (status, text) for /api/ paths (read with fetch) and to ("ready", html)
    / ("challenge", title) / ("timeout", "") for pages (read by navigation)."""

    ws = "ws://fake"

    def __init__(self, answers, state="ready"):
        self.answers = answers
        self.state = state              # what the first (app page) load ends in
        self.opened = []
        self.navigated = []
        self.closed = 0
        self.fetched = []
        self._current = None

    def open(self, url, wait_s=8.0):
        self.opened.append(url)
        return None

    def wait_ready(self, wait_s=20.0, expect_url=None):
        return {"state": self.state, "title": "Just a moment..." if self.state == "challenge" else "SteamDB",
                "href": expect_url or ""}

    def navigate(self, url, wait_s=20.0):
        self.navigated.append(url)
        path = url[len(sr.BASE):]
        a = self.answers[path]
        if isinstance(a, Exception):
            raise a
        state, payload = a
        self._current = payload if state == "ready" else ""
        return {"state": state, "title": payload if state == "challenge" else "SteamDB", "href": url}

    def wait_settled(self, count_js, wait_s=15.0):
        return 1

    def html(self):
        return self._current or ""

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
                         view_factory=lambda appid: view, now=self.now)

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
        view = FakeView({path: (200, RSS), sr.depot_path(2379781): ("ready", "<html><table><tr></tr></table></html>")})
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
        # the feed is fetch()ed in-page; the depot page is a real navigation
        self.assertEqual(view.fetched, [path])
        self.assertEqual(view.navigated, [sr.BASE + sr.depot_path(2379781)])
        self.assertEqual(f2.text, "<html><table><tr></tr></table></html>")
        self.assertFalse(r.needs_user)
        self.assertIsNone(r.challenge_url)
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
        self.assertEqual(r.challenge_url, sr.BASE + path)
        run(r.close())

    def test_page_stuck_on_challenge_is_needs_user_with_its_url(self):
        # the app page loads, the depot page does not: only THAT url helps the user
        path = sr.depot_path(2379781)
        view = FakeView({path: ("challenge", "Just a moment...")})
        r = sr.Reader(2379780, cache_dir=self.dir, use_direct=False,
                      view_factory=lambda appid: view, now=self.now)
        f = run(r.get(path, sr.TTL_DEPOT))
        self.assertEqual((f.outcome, f.status, f.transport), ("needs_user", 403, "browser"))
        self.assertEqual(r.challenge_url, "https://steamdb.info/depot/2379781/manifests/")
        self.assertIsNone(sr.cache_get(path, sr.TTL_DEPOT, self.dir, self.now))
        run(r.close())
        self.assertEqual(view.closed, 1)

    def test_bare_403_on_direct_backs_off_too(self):
        path = sr.depot_path(2379781)
        view = FakeView({path: ("ready", "<html><table></table></html>")})
        r = self.reader(self.direct(403, ""), view)
        run(r.get(path, sr.TTL_DEPOT))
        run(r.get(sr.depot_path(2379781), sr.TTL_DEPOT))  # cache now, but direct must be blocked anyway
        self.assertGreater(sr._direct_blocked_until, self.t)
        self.assertEqual(len(self.direct_calls), 1)
        run(r.close())

    def test_list_that_never_fills_is_empty_and_not_cached(self):
        class Shell(FakeView):
            def wait_settled(self, count_js, wait_s=15.0):
                return 0
        path = "/app/2215260/patchnotes/"
        view = Shell({path: ("ready", "<html><tbody id='js-builds'></tbody></html>")})
        import cef_cdp
        keep, keep_sleep = cef_cdp.evaluate, sr.LIST_RETRY_SLEEP_S
        cef_cdp.evaluate = lambda ws, js, **k: "ok"
        sr.LIST_RETRY_SLEEP_S = 0.0
        try:
            r = sr.Reader(2215260, cache_dir=self.dir, use_direct=False,
                          view_factory=lambda appid: view, now=self.now)
            f = run(r.get(path, sr.TTL_FEED, "document.querySelectorAll('#js-builds tr').length", "(1)"))
            self.assertEqual((f.outcome, f.transport), ("empty", "browser"))
            self.assertIn("did not fill", f.error)
            self.assertEqual(r.view_state.get("attempts"), [0, 0, 0, 0, 0])
            self.assertIsNone(sr.cache_get(path, sr.TTL_FEED, self.dir, self.now))
            run(r.close())
        finally:
            cef_cdp.evaluate, sr.LIST_RETRY_SLEEP_S = keep, keep_sleep

    def test_validate_turns_a_200_into_empty_and_caches_nothing(self):
        path = "/depot/1/manifests/"
        view = FakeView({path: ("ready", "<html><body>Access denied</body></html>")})
        r = sr.Reader(256290, cache_dir=self.dir, use_direct=False,
                      view_factory=lambda appid: view, now=self.now)
        f = run(r.get(path, sr.TTL_FEED, validate=lambda t: "js-builds" in t))
        self.assertEqual(f.outcome, "empty")
        self.assertIn("Access denied", f.error)
        self.assertIsNone(sr.cache_get(path, sr.TTL_FEED, self.dir, self.now))
        run(r.close())

    def test_builds_page_re_requests_the_list_until_it_fills(self):
        rows = ('<tbody id="js-builds"><tr data-date="1740421318"><td><a href="/patchnotes/17459173/">x</a></td>'
                '<td>Mon</td><td>18:21</td><td>t</td><td></td><td></td><td>17459173</td></tr></tbody>')

        class LateView(FakeView):
            """The list is empty on load and fills only after the 2nd re-request."""
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.clicks = 0
                self.polls = 0

            def wait_settled(self, count_js, wait_s=15.0):
                self.polls += 1
                return 1 if self.clicks >= 2 else 0

        page = sr.patchnotes_path(1)
        view = LateView({page: ("ready", "<html>" + rows + "</html>")})
        real_eval = sr.cef_cdp.evaluate if hasattr(sr, "cef_cdp") else None
        import cef_cdp
        keep = cef_cdp.evaluate
        cef_cdp.evaluate = lambda ws, js, **k: (setattr(view, "clicks", view.clicks + 1), "ok")[1]
        keep_sleep = sr.LIST_RETRY_SLEEP_S
        sr.LIST_RETRY_SLEEP_S = 0.0
        try:
            r = sr.Reader(1, cache_dir=self.dir, use_direct=False, view_factory=lambda appid: view, now=self.now)
            f = run(r.builds_page())
            self.assertEqual((f.outcome, f.path), ("ok", page))
            self.assertEqual(r.view_state.get("attempts"), [0, 0, 1])
            self.assertEqual(view.clicks, 2)
            run(r.close())
        finally:
            cef_cdp.evaluate = keep
            sr.LIST_RETRY_SLEEP_S = keep_sleep
        del real_eval

    def test_page_timeout_is_an_error_not_cached(self):
        path = sr.depot_path(999)
        view = FakeView({path: ("timeout", "")})
        r = sr.Reader(1, cache_dir=self.dir, use_direct=False,
                      view_factory=lambda appid: view, now=self.now)
        f = run(r.get(path, sr.TTL_DEPOT))
        self.assertEqual((f.outcome, f.transport), ("error", "browser"))
        self.assertIn("timeout", f.error)
        self.assertIsNone(sr.cache_get(path, sr.TTL_DEPOT, self.dir, self.now))
        run(r.close())

    def test_view_open_failure_is_an_error_with_reason(self):
        class Broken(FakeView):
            def open(self, url, wait_s=8.0):
                return "SharedJSContext not found on the CEF debug port"
        view = Broken({})
        r = sr.Reader(1, cache_dir=self.dir, use_direct=False,
                      view_factory=lambda appid: view, now=self.now)
        f = run(r.get(sr.feed_path(1), sr.TTL_FEED))
        self.assertEqual(f.outcome, "error")
        self.assertIn("SharedJSContext", f.error)
        self.assertEqual(f.summary()["bytes"], 0)
        run(r.close())


if __name__ == "__main__":
    unittest.main()

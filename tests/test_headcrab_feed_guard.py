"""Tests for the res/updates.yaml body guard in headcrab_compat.

Same bug, same shape, on both sides of the stack: an HTTP 200 means the transfer
worked, not that the feed arrived, and lumalinux's C++ side had the identical hole
(src/update.cpp, fixed alongside this). Here the consequence is quieter but not
nothing — a garbage body makes `_supports_build()` answer "unknown", and
`check_headcrab_compat()` requires a positive True before offering the Steam
update, so the offer silently disappears until a good fetch lands.

The load-bearing case is the REAL feed: it opens with a header comment that itself
contains the word `SafeModeHashes`, so a bare substring test accepts an error page
that quotes it, and a `startswith` on the whole text rejects the genuine article.
Both wrong answers are pinned below.
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import headcrab_compat as hc  # noqa: E402


# The real file's shape: comments first (including the word we key on, without a
# colon), then the top-level key at column 0.
REAL_FEED = """\
# res/updates.yaml — runtime-fetched config shared by lumalinux + LumaDeck.
#
# SafeModeHashes is the single source of truth and the ONLY thing lumalinux's
# runtime reads (src/update.cpp).

SafeModeHashes:
  20260611150000:
    - abc123 # steam_version: 1781041600
"""

GARBAGE = {
    "empty body": "",
    "whitespace only": "\n\n  \n",
    "API error JSON": '{\n  "message": "Not Found"\n}\n',
    "HTML error page": "<!DOCTYPE html>\n<html><body>Down</body></html>\n",
    "CDN error": "Error 503\n\nGuru Meditation:\n\nXID: 1\n",
    "HTML quoting the key": "<html><p>SafeModeHashes is the truth</p></html>",
}


class LooksLikeFeedTests(unittest.TestCase):
    def test_accepts_the_real_feed_shape(self):
        self.assertTrue(hc._looks_like_feed(REAL_FEED))

    def test_accepts_upstream_shape_with_the_key_on_line_one(self):
        self.assertTrue(hc._looks_like_feed("SafeModeHashes:\n  20260611150000:\n"))

    def test_rejects_every_garbage_body(self):
        for name, body in GARBAGE.items():
            with self.subTest(body=name):
                self.assertFalse(hc._looks_like_feed(body))

    def test_the_two_obvious_implementations_are_both_wrong(self):
        # Pinned so nobody "simplifies" the guard into either of them.
        self.assertFalse(REAL_FEED.startswith("SafeModeHashes:"))
        self.assertIn("SafeModeHashes", GARBAGE["HTML quoting the key"])

    def test_agrees_with_the_cpp_guard_on_the_key(self):
        # src/update.cpp anchors on the same 15-byte key at column 0. If one side
        # ever widens what it accepts, the two stop agreeing about what the feed is.
        self.assertTrue(hc._looks_like_feed("SafeModeHashes:"))
        self.assertFalse(hc._looks_like_feed(" SafeModeHashes:"))


class _Resp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _Client:
    def __init__(self, resp):
        self._resp = resp

    async def get(self, url, **kwargs):
        return self._resp


class UpdatesTextTests(unittest.TestCase):
    def setUp(self):
        self._cache_dir = hc._CACHE_DIR
        self._ll_cache = hc._LL_CACHE_FILE
        hc._CACHE_DIR = tempfile.mkdtemp()
        hc._LL_CACHE_FILE = os.path.join(hc._CACHE_DIR, "lumalinux_updates.yaml")
        self._client = hc.ensure_http_client
        self.addCleanup(self._restore)

    def _restore(self):
        hc._CACHE_DIR = self._cache_dir
        hc._LL_CACHE_FILE = self._ll_cache
        hc.ensure_http_client = self._client

    def _serve(self, status, text):
        async def factory(context=""):
            return _Client(_Resp(status, text))
        hc.ensure_http_client = factory

    def _fetch(self):
        return asyncio.run(hc._lumalinux_updates_text())

    def _cached(self):
        try:
            with open(hc._LL_CACHE_FILE, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def test_a_good_feed_is_returned_and_cached(self):
        self._serve(200, REAL_FEED)
        self.assertEqual(self._fetch(), REAL_FEED)
        self.assertEqual(self._cached(), REAL_FEED)

    def test_a_200_with_garbage_does_not_overwrite_a_good_cache(self):
        # The whole point: one bad response must not cost us the cache.
        self._serve(200, REAL_FEED)
        self._fetch()
        for name, body in GARBAGE.items():
            with self.subTest(body=name):
                self._serve(200, body)
                self.assertEqual(self._fetch(), REAL_FEED)
                self.assertEqual(self._cached(), REAL_FEED)

    def test_a_garbage_cache_is_discarded_rather_than_parsed(self):
        # An install carrying a cache poisoned before the guard existed.
        os.makedirs(hc._CACHE_DIR, exist_ok=True)
        with open(hc._LL_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write('{"message": "Not Found"}')
        self._serve(503, "")
        self.assertIsNone(self._fetch())

    def test_no_cache_and_a_bad_body_is_none(self):
        self._serve(200, "<html>down</html>")
        self.assertIsNone(self._fetch())


class SupportsBuildTests(unittest.TestCase):
    """The consequence the guard prevents, asserted end to end."""

    def test_garbage_reads_as_unknown_which_suppresses_the_steam_offer(self):
        # Not a regression in _supports_build — it is fail-open by design. This
        # pins WHY the guard matters: unknown is not True, and check_headcrab_compat
        # requires True before offering the Steam update.
        self.assertIsNone(hc._supports_build('{"message": "Not Found"}', "20260611150000", 1781041600))

    def test_the_real_feed_answers_the_question(self):
        self.assertTrue(hc._supports_build(REAL_FEED, "20260611150000", 1781041600))

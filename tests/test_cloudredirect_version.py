"""Unit tests for the CloudRedirect update signal.

Two pieces, both replacing a content-hash diff that fired on every upstream
rebuild of an unchanged version:

  * `components.read_cloudredirect_version` — the version CloudRedirect compiles
    into its own .so;
  * `update_checks.get_latest_release_with_asset` — which release to compare it
    against, given that CloudRedirect cuts Windows-only releases.

The release fixtures mirror the real asset layout, measured asset by asset
against GitHub: v2.6.1 and v2.6.2 ship CloudRedirect.exe and no
cloud_redirect.so. That run of two is why "the latest release" is the wrong
question and this module exists.

Runs anywhere (no network):
    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import components  # noqa: E402
import update_checks as uc  # noqa: E402


def _so(payload: bytes, case: unittest.TestCase) -> str:
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
    case.addCleanup(os.remove, path)
    return path


class ReadVersionTests(unittest.TestCase):
    """The string is CR_VERSION_STRING, compiled in by CloudRedirect's
    CMakeLists and also exported as CR_GetVersion(). Only the X.Y.Z may reach
    the compare — the build metadata after it differs between rebuilds of the
    same version, which is exactly the noise we are removing."""

    def test_reads_a_modern_build(self):
        blob = b"junk[CR] DoInit: version=2.6.5+870afdb-dirty finding steamclient"
        self.assertEqual(components.read_cloudredirect_version(_so(blob, self)), "2.6.5")

    def test_git_sha_and_dirty_flag_are_dropped(self):
        a = _so(b"version=2.6.5+870afdb-dirty", self)
        b = _so(b"version=2.6.5+aaaaaaa", self)
        self.assertEqual(components.read_cloudredirect_version(a),
                         components.read_cloudredirect_version(b))

    def test_reads_a_build_made_without_git(self):
        # Every release before v2.5.4 reports "+unknown".
        self.assertEqual(
            components.read_cloudredirect_version(_so(b"version=2.1.5+unknown", self)),
            "2.1.5")

    def test_label_before_the_plus_is_dropped(self):
        # v2.5.0 shipped as "2.5.0-Final+unknown".
        self.assertEqual(
            components.read_cloudredirect_version(_so(b"version=2.5.0-Final+unknown", self)),
            "2.5.0")

    def test_no_version_string_is_none(self):
        self.assertIsNone(components.read_cloudredirect_version(_so(b"\x00" * 4096, self)))

    def test_missing_file_is_none(self):
        self.assertIsNone(components.read_cloudredirect_version("/nonexistent/cloud_redirect.so"))


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp):
        self._resp = resp

    async def get(self, url, **kwargs):
        return self._resp


def _release(tag, assets, draft=False, prerelease=False):
    return {
        "tag_name": tag, "draft": draft, "prerelease": prerelease,
        "html_url": f"https://example.invalid/{tag}",
        "assets": [{"name": name} for name in assets],
    }


WIN = ["CloudRedirect.exe", "cloud_redirect.dll"]
BOTH = WIN + ["cloud_redirect.so", "cloudredirect.flatpak"]
ASSET = "cloud_redirect.so"


class LatestReleaseWithAssetTests(unittest.TestCase):
    def setUp(self):
        # Never touch the user's real release cache.
        self._cache_dir = uc._CACHE_DIR
        uc._CACHE_DIR = tempfile.mkdtemp()
        self._client = uc.ensure_http_client
        self.addCleanup(self._restore)

    def _restore(self):
        uc._CACHE_DIR = self._cache_dir
        uc.ensure_http_client = self._client

    def _serve(self, resp):
        async def factory(context=""):
            return _Client(resp)
        uc.ensure_http_client = factory

    def _lookup(self):
        return asyncio.run(uc.get_latest_release_with_asset(
            "Selectively11", "CloudRedirect", ASSET, force=True))

    def test_picks_the_newest_release_that_ships_the_asset(self):
        self._serve(_Resp(200, [_release("v2.6.5", BOTH), _release("v2.6.4", BOTH)]))
        self.assertEqual(self._lookup()["tag"], "v2.6.5")

    def test_skips_windows_only_releases(self):
        # The real state right after v2.6.2 was cut: the two newest releases have
        # no Linux build, so the answer is v2.6.0. Naming v2.6.2 would announce a
        # version that does not exist for Linux, and applying it could not clear
        # the offer.
        self._serve(_Resp(200, [
            _release("v2.6.2", WIN), _release("v2.6.1", WIN), _release("v2.6.0", BOTH),
        ]))
        self.assertEqual(self._lookup()["tag"], "v2.6.0")

    def test_skips_drafts_and_prereleases(self):
        self._serve(_Resp(200, [
            _release("v2.6.5", BOTH, draft=True),
            _release("v2.6.4", BOTH, prerelease=True),
            _release("v2.6.3", BOTH),
        ]))
        self.assertEqual(self._lookup()["tag"], "v2.6.3")

    def test_no_match_and_no_cache_is_none(self):
        self._serve(_Resp(200, [_release("v2.6.2", WIN), _release("v2.6.1", WIN)]))
        self.assertIsNone(self._lookup())

    def test_http_error_and_no_cache_is_none(self):
        self._serve(_Resp(503))
        self.assertIsNone(self._lookup())

    def test_falls_back_to_a_stale_cache_on_error(self):
        self._serve(_Resp(200, [_release("v2.6.5", BOTH)]))
        self._lookup()
        self._serve(_Resp(503))
        self.assertEqual(self._lookup()["tag"], "v2.6.5")

    def test_falls_back_to_a_stale_cache_when_nothing_matches(self):
        # Deliberate: if the newest Linux release scrolled past the page, the last
        # one we saw beats None — None reads as "up to date" and hides an update.
        self._serve(_Resp(200, [_release("v2.6.5", BOTH)]))
        self._lookup()
        self._serve(_Resp(200, [_release("v2.9.9", WIN)]))
        self.assertEqual(self._lookup()["tag"], "v2.6.5")

    def test_cache_key_does_not_collide_with_the_plain_latest_lookup(self):
        # get_latest_release and this ask different questions about the same
        # repo and must not share a cache file.
        self.assertNotEqual(
            uc._cache_path("Selectively11", "CloudRedirect"),
            uc._cache_path("Selectively11", "CloudRedirect", ASSET),
        )


class VerdictTests(unittest.TestCase):
    """has_update_from is shared with the plain-latest path; these pin that the
    CloudRedirect side reaches the same verdicts."""

    @staticmethod
    def _verdict(installed, latest_tag):
        latest = ({"tag": latest_tag, "tag_normalised": latest_tag.lstrip("v"), "url": ""}
                  if latest_tag else None)
        return asyncio.run(uc.has_update_from(installed, latest))["has_update"]

    def test_behind_is_an_update(self):
        self.assertTrue(self._verdict("2.6.3", "v2.6.5"))

    def test_current_is_not(self):
        self.assertFalse(self._verdict("2.6.5", "v2.6.5"))

    def test_ahead_of_a_stale_latest_is_not(self):
        self.assertFalse(self._verdict("2.6.5", "v2.6.3"))

    def test_unknown_installed_is_not(self):
        self.assertFalse(self._verdict(None, "v2.6.5"))

    def test_unknown_latest_is_not(self):
        self.assertFalse(self._verdict("2.6.5", None))


if __name__ == "__main__":
    unittest.main()

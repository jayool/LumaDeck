"""Unit tests for the CloudRedirect update signal.

Two pieces:

  * `components.read_cloudredirect_version` — the version CloudRedirect compiles
    into its own .so (replacing a content-hash diff that fired on every upstream
    rebuild of an unchanged version);
  * `components.check_cloudredirect_update` — that version against the build
    lumalinux ships. Upstream was deleted on 2026-10-16, so there is no release
    to look up any more: "latest" is a constant and the check never touches the
    network.

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


class ShippedBuildTests(unittest.TestCase):
    """check_cloudredirect_update compares the .so on disk against the build
    lumalinux ships, with no network in the loop."""

    def _check(self, so_version):
        import paths
        path = _so(b"\x00[CR] DoInit: version=" + so_version + b" finding steamclient.so\x00", self) \
            if so_version is not None else "/nonexistent/cloud_redirect.so"
        saved = paths.get_cloudredirect_so_path
        paths.get_cloudredirect_so_path = lambda: path
        self.addCleanup(setattr, paths, "get_cloudredirect_so_path", saved)
        return asyncio.run(components.check_cloudredirect_update())

    def test_the_apps_older_so_is_an_update(self):
        # The sign-in app deploys its own 2.6.5; Update brings 2.6.6 back.
        verdict = self._check(b"2.6.5+abc1234")
        self.assertTrue(verdict["has_update"])
        self.assertEqual(verdict["latest"], components._CR_SHIPPED_VERSION)

    def test_the_shipped_build_is_current(self):
        verdict = self._check(b"2.6.6+3434d9d")
        self.assertFalse(verdict["has_update"])

    def test_no_so_is_not_an_update(self):
        self.assertFalse(self._check(None)["has_update"])

    def test_never_touches_the_network(self):
        async def boom(*args, **kwargs):
            raise AssertionError("network call")
        saved = uc.ensure_http_client
        uc.ensure_http_client = boom
        self.addCleanup(setattr, uc, "ensure_http_client", saved)
        self._check(b"2.6.5")


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

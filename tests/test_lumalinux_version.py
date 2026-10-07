"""lumalinux's installed version comes from liblumalinux.so on disk, like
CloudRedirect's, so the update shows whether or not Steam has loaded it
(status.json, written by the loaded .so, was the only source before: no load,
no version, no update offer). The .so carries "lumalinux/v0.22.1" (gmrc
User-Agent) and "lumalinux v0.22.1 preinit" (first log line); measured on a
real build 2026-10-07.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import components  # noqa: E402


def _so(payload: bytes, case: unittest.TestCase) -> str:
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
    case.addCleanup(os.remove, path)
    return path


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ReadVersion(unittest.TestCase):
    def test_user_agent_string(self):
        blob = b"\x00/.config/lumalinux/keys.txt\x00lumalinux/v0.22.1\x00"
        self.assertEqual(components.read_lumalinux_version(_so(blob, self)), "0.22.1")

    def test_preinit_string(self):
        blob = b"\x00lumalinux v0.21.0 preinit \xe2\x80\x94 hooks install\x00"
        self.assertEqual(components.read_lumalinux_version(_so(blob, self)), "0.21.0")

    def test_no_string_is_none(self):
        self.assertIsNone(components.read_lumalinux_version(_so(b"\x00nothing here\x00", self)))

    def test_missing_file_is_none(self):
        self.assertIsNone(components.read_lumalinux_version("/nonexistent/liblumalinux.so"))


class InstalledVersion(unittest.TestCase):
    def test_disk_wins_over_status_json(self):
        path = _so(b"lumalinux/v0.22.1\x00", self)
        with mock.patch("paths.get_lumalinux_so_path", lambda: path):
            self.assertEqual(components.installed_lumalinux_version("0.20.0"), "0.22.1")

    def test_status_json_is_the_fallback(self):
        path = _so(b"no version\x00", self)
        with mock.patch("paths.get_lumalinux_so_path", lambda: path):
            self.assertEqual(components.installed_lumalinux_version("0.20.0"), "0.20.0")
        with mock.patch("paths.get_lumalinux_so_path", lambda: None):
            self.assertIsNone(components.installed_lumalinux_version(None))

    def test_update_offered_while_not_loaded(self):
        """status.json absent (Steam has not loaded lumalinux) but the .so on
        disk is behind the latest release: that is exactly when the offer
        matters."""
        path = _so(b"lumalinux/v0.21.0\x00", self)
        latest = {"tag": "v0.22.1", "tag_normalised": "0.22.1", "url": "u"}

        async def fake_latest(owner, repo, force=False):
            return latest
        with mock.patch("paths.get_lumalinux_so_path", lambda: path), \
             mock.patch("update_checks.get_latest_release", fake_latest):
            res = run(components.check_lumalinux_update(None))
        self.assertEqual(res["installed"], "0.21.0")
        self.assertTrue(res["has_update"])


if __name__ == "__main__":
    unittest.main()

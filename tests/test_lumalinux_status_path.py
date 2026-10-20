"""lumalinux's status.json can exist in two places at once (the 32-bit
client's library writes under /run/user, the 64-bit client's under ~/.cache);
the one whose writer still runs is the live one (backend/paths.py
find_lumalinux_status_path)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import paths  # noqa: E402


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


class StatusPathTests(unittest.TestCase):
    def test_live_writer_beats_an_earlier_stale_file(self):
        with tempfile.TemporaryDirectory() as d:
            stale = os.path.join(d, "run", "lumalinux", "status.json")
            fresh = os.path.join(d, "cache", "lumalinux", "status.json")
            _write(stale, {"pid": 999999999, "version": "old"})      # no such process
            _write(fresh, {"pid": os.getpid(), "version": "new"})     # this test process
            with mock.patch.object(paths, "lumalinux_status_candidates", return_value=[stale, fresh]):
                self.assertEqual(paths.find_lumalinux_status_path(), fresh)
                self.assertEqual((paths.read_lumalinux_status() or {}).get("version"), "new")

    def test_first_existing_when_nothing_is_live(self):
        with tempfile.TemporaryDirectory() as d:
            stale = os.path.join(d, "run", "lumalinux", "status.json")
            _write(stale, {"pid": 999999999})
            with mock.patch.object(paths, "lumalinux_status_candidates",
                                   return_value=[os.path.join(d, "missing.json"), stale]):
                self.assertEqual(paths.find_lumalinux_status_path(), stale)
                self.assertIsNone(paths.read_lumalinux_status())   # stale, as before

    def test_single_live_file_as_before(self):
        with tempfile.TemporaryDirectory() as d:
            live = os.path.join(d, "run", "lumalinux", "status.json")
            _write(live, {"pid": os.getpid(), "version": "v"})
            with mock.patch.object(paths, "lumalinux_status_candidates", return_value=[live]):
                self.assertEqual(paths.find_lumalinux_status_path(), live)

    def test_none_when_nothing_exists(self):
        with mock.patch.object(paths, "lumalinux_status_candidates", return_value=["/nonexistent/a.json"]):
            self.assertIsNone(paths.find_lumalinux_status_path())


if __name__ == "__main__":
    unittest.main()

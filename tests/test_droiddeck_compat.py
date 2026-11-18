"""Hermetic tests for LumaDeck's DroidDeck compatibility detection."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import droiddeck_compat as dd
import paths


class TestDroidDeckCompat(unittest.TestCase):
    def test_does_not_detect_regular_linux(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertFalse(dd.is_droiddeck({}, home))

    def test_decky_marker(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home, "homebrew", "services").mkdir(parents=True)
            Path(home, ".droiddeck-decky-enabled").touch()
            self.assertTrue(dd.is_droiddeck({}, home))

    def test_explicit_override(self):
        self.assertTrue(dd.is_droiddeck({"LUMADECK_DROIDDECK": "1"}))
        self.assertFalse(dd.is_droiddeck({"LUMADECK_DROIDDECK": "0", "DD_STEAM_CLIENT_ARCH": "arm64"}))

    def test_x64_process_detection(self):
        with tempfile.TemporaryDirectory() as proc:
            Path(proc, "123").mkdir()
            Path(proc, "123", "cmdline").write_bytes(b"/root/.droiddeck-x64/.local/share/Steam/steamrt64/steam\0")
            self.assertEqual(dd.selected_client({}, proc), "x86_64")

    def test_arm64_process_detection(self):
        with tempfile.TemporaryDirectory() as proc:
            Path(proc, "123").mkdir()
            Path(proc, "123", "cmdline").write_bytes(b"/root/.local/share/Steam/steamrtarm64/steam\0")
            self.assertEqual(dd.selected_client({}, proc), "arm64")

    def test_client_home_priority(self):
        self.assertEqual(dd.steam_roots("/root", {"DD_STEAM_CLIENT_ARCH": "arm64"}, None)[0],
                         "/root/.local/share/Steam")
        self.assertEqual(dd.steam_roots("/root", {"DD_STEAM_CLIENT_ARCH": "x86_64"}, None)[0],
                         "/root/.droiddeck-x64/.local/share/Steam")

    def test_override_root_requires_absolute_path(self):
        self.assertEqual(dd.steam_roots("/root", {"LUMADECK_STEAM_ROOT": "/custom"}, None)[0],
                         "/custom")
        self.assertNotIn("relative", dd.steam_roots("/root", {"LUMADECK_STEAM_ROOT": "relative"}, None))

    def test_architecture_detection_arm64(self):
        with tempfile.TemporaryDirectory() as proc:
            Path(proc, "123").mkdir()
            Path(proc, "123", "cmdline").write_bytes(b"/root/.local/share/Steam/steamrtarm64/steam\0")
            self.assertEqual(paths.detect_steam_client_arch(proc, steam_root=proc),
                             paths.STEAM_CLIENT_ARM64)

    def test_architecture_detection_x64(self):
        with tempfile.TemporaryDirectory() as proc:
            Path(proc, "123").mkdir()
            Path(proc, "123", "cmdline").write_bytes(b"/root/.droiddeck-x64/.local/share/Steam/steamrt64/steam\0")
            self.assertEqual(paths.detect_steam_client_arch(proc, steam_root=proc),
                             paths.STEAM_CLIENT_64)

    def test_droiddeck_fallback_is_arm64(self):
        with tempfile.TemporaryDirectory() as proc:
            with patch.object(paths, "_is_droiddeck", return_value=True), \
                 patch.object(paths, "_dd_client", return_value="arm64"):
                self.assertEqual(paths.detect_steam_client_arch(proc, steam_root=proc),
                                 paths.STEAM_CLIENT_ARM64)


if __name__ == "__main__":
    unittest.main()

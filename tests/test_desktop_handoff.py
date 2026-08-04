"""Phase 2 — the desktop session-select arg differs by lineage.

`steamos-session-select` reaches the desktop session with 'plasma' on SteamOS
(HoloISO) but 'desktop' on the ChimeraOS gamescope-session lineage (CachyOS
Handheld, Bazzite). desktop_handoff picks the right one, defaulting to the
tested SteamOS value.

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import desktop_handoff as dh  # noqa: E402
import platform_info as p     # noqa: E402


class TestDesktopArgByLineage(unittest.TestCase):
    def test_steamos_uses_plasma(self):
        self.assertEqual(dh._desktop_arg_for("steamos"), "plasma")

    def test_chimeraos_lineage_uses_desktop(self):
        self.assertEqual(dh._desktop_arg_for("cachyos"), "desktop")
        self.assertEqual(dh._desktop_arg_for("bazzite"), "desktop")
        self.assertEqual(dh._desktop_arg_for("chimeraos"), "desktop")

    def test_unknown_defaults_to_plasma(self):
        # SteamOS-default: only switch to 'desktop' for a POSITIVELY known lineage.
        self.assertEqual(dh._desktop_arg_for("unknown"), "plasma")
        self.assertEqual(dh._desktop_arg_for(""), "plasma")

    def test_live_arg_is_valid_and_never_raises(self):
        arg = dh._desktop_session_arg()
        self.assertIn(arg, ("plasma", "desktop"))


class TestSessionFamilyPublic(unittest.TestCase):
    def test_session_family_matches_pure_helper(self):
        # Public wrapper is consistent with the pure classifier on the live distro.
        self.assertEqual(p.session_family(), p._session_family(p._distro_id(p._read_os_release())))

    def test_pure_classifier(self):
        self.assertEqual(p._session_family("steamos"), "steamos")
        self.assertEqual(p._session_family("cachyos"), "cachyos")
        self.assertEqual(p._session_family("fedora"), "unknown")


if __name__ == "__main__":
    unittest.main()

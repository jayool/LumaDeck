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


class TestTerminalResolver(unittest.TestCase):
    """The hand-off must open in a terminal that actually exists — konsole is
    KDE-only and breaks the hand-off on GNOME-family distros (ChimeraOS,
    Bazzite-GNOME). _terminal_exec_prefix resolves a DE-agnostic one."""

    def _with_which(self, present):
        import shutil
        orig = shutil.which
        shutil.which = lambda n: ("/usr/bin/" + n) if n in present else None
        self.addCleanup(lambda: setattr(shutil, "which", orig))

    def test_konsole_first_on_kde(self):
        self._with_which({"konsole", "xterm"})
        self.assertEqual(dh._terminal_exec_prefix(), "konsole --hold -e")

    def test_falls_through_to_gnome_family(self):
        self._with_which({"gnome-terminal"})
        self.assertEqual(dh._terminal_exec_prefix(), "gnome-terminal --")
        self._with_which({"ptyxis"})
        self.assertEqual(dh._terminal_exec_prefix(), "ptyxis --")

    def test_none_when_no_terminal(self):
        self._with_which(set())
        self.assertIsNone(dh._terminal_exec_prefix())  # -> caller runs headless

    def test_konsole_is_tried_first(self):
        self.assertEqual(dh._TERMINALS[0][0], "konsole")


class TestGameModeArg(unittest.TestCase):
    def test_gamemode_arg_is_gamescope_and_used_in_both_payloads(self):
        self.assertEqual(dh._GAMEMODE_ARG, "gamescope")
        self.assertIn("steamos-session-select gamescope", dh._REAL_PAYLOAD)
        # The quick-install payload is built in run_desktop_handoff_quick_install;
        # its game-mode line uses the same constant.
        import inspect
        src = inspect.getsource(dh.run_desktop_handoff_quick_install)
        self.assertIn("steamos-session-select {_GAMEMODE_ARG}", src)


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

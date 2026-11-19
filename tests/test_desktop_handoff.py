"""Phase 2 — the desktop session-select arg differs by lineage.

`steamos-session-select` reaches the desktop session with 'plasma' on SteamOS
(HoloISO) AND on CachyOS Handheld — its gamescope-session-cachyos is a
Valve/SteamOS fork (verified against CachyOS/gamescope-session @cachyos:
usr/bin/steamos-session-select accepts only plasma/gamescope/persistent/oneshot,
NOT 'desktop'). The ChimeraOS gamescope-session-plus lineage (Bazzite) uses
'desktop'. desktop_handoff picks the right one, defaulting to the tested SteamOS
value ('plasma') for anything not positively a ChimeraOS lineage.

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

    def test_cachyos_uses_plasma_valve_fork(self):
        # CachyOS Handheld's gamescope-session is a Valve/SteamOS fork; its
        # steamos-session-select has NO 'desktop' case. Verified from source.
        self.assertEqual(dh._desktop_arg_for("cachyos"), "plasma")

    def test_chimeraos_lineage_uses_desktop(self):
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
    def test_gamemode_arg_is_gamescope_and_used_in_the_payload(self):
        self.assertEqual(dh._GAMEMODE_ARG, "gamescope")
        self.assertIn("steamos-session-select gamescope", dh._REAL_PAYLOAD)


class TestSessionFamilyPublic(unittest.TestCase):
    def test_session_family_matches_pure_helper(self):
        # Public wrapper is consistent with the pure classifier on the live distro.
        self.assertEqual(p.session_family(), p._session_family(p._distro_id(p._read_os_release())))

    def test_pure_classifier(self):
        self.assertEqual(p._session_family("steamos"), "steamos")
        self.assertEqual(p._session_family("cachyos"), "cachyos")
        self.assertEqual(p._session_family("fedora"), "unknown")




class DowngradeTargetTests(unittest.TestCase):
    """LumaDeck decides the build downgrade.sh lands on (2026-11-19, both client
    lines): the newest build lumalinux's whitelist annotates for the running
    client's arch below the installed one that both the latest lumalinux
    release and the latest SLSsteam for that arch hook. The 64-bit client
    downgrades along its own steamrt64 line."""

    LL = """SafeModeHashes:
  20261119000000:
    # steam_version: 1791918634
    - 0d01ab4fe889f87314c8416d18a2152b130a93231bb19cd6f0ed2ebd7a7ab90a
    # steam_version: 1792618285
    - c770a8b13872fed128dd357eabc1d715260fadd9b16c627ae3395406e6ea37d4
    # steam_version: 1794266161
    # arch: steamrt64
    - 53bdabbbb63fff0146a459f1f40dc9208661f329810557c462404ba52318bf11
    # steam_version: 1794536281
    # arch: steamrt64
    - dab8df0daa27ffa6594ef5d6bc8cf707f37990220628f1f249fb30f4d88ade91
    # steam_version: 1795048523
    # arch: steamrt64
    - c6b5784ae84a7d63ae1d238045eab33c92eb947d4556de5328e51272973c113c
"""
    SLS = """SafeModeHashes:
  20261014151919:
    - 0d01ab4fe889f87314c8416d18a2152b130a93231bb19cd6f0ed2ebd7a7ab90a #ubuntu12_32
    - 53bdabbbb63fff0146a459f1f40dc9208661f329810557c462404ba52318bf11 #steamrt64
  20261112130346:
    - 53bdabbbb63fff0146a459f1f40dc9208661f329810557c462404ba52318bf11 #steamrt64
    - dab8df0daa27ffa6594ef5d6bc8cf707f37990220628f1f249fb30f4d88ade91 #steamrt64
"""

    def test_64bit_picks_the_newest_hooked_steamrt64_build_below_current(self):
        r = dh.pick_downgrade_target(self.LL, "20261119000000", self.SLS, 1795048523, "steamrt64")
        self.assertEqual(r["target"], 1794536281)
        self.assertEqual(r["hash"][:8], "dab8df0d")
        self.assertTrue(r["possible"])

    def test_64bit_skips_a_build_the_latest_slssteam_dropped(self):
        sls = self.SLS.replace("    - dab8df0daa27ffa6594ef5d6bc8cf707f37990220628f1f249fb30f4d88ade91 #steamrt64\n", "")
        r = dh.pick_downgrade_target(self.LL, "20261119000000", sls, 1795048523, "steamrt64")
        self.assertEqual(r["target"], 1794266161)
        self.assertTrue(r["possible"])

    def test_32bit_follows_its_own_line(self):
        import slssteam_version
        saved = slssteam_version.LAST_32BIT_TAG
        slssteam_version.LAST_32BIT_TAG = "20261014151919"
        try:
            r = dh.pick_downgrade_target(self.LL, "20261119000000", self.SLS, 1792618285, "ubuntu12_32")
        finally:
            slssteam_version.LAST_32BIT_TAG = saved
        self.assertEqual(r["target"], 1791918634)
        self.assertTrue(r["possible"])

    def test_nothing_below_current_is_not_possible(self):
        r = dh.pick_downgrade_target(self.LL, "20261119000000", self.SLS, 1794266161, "steamrt64")
        self.assertIs(r["possible"], False)
        self.assertIsNone(r["target"])

    def test_unknown_slssteam_support_is_unknown_not_refused(self):
        # A 64-bit hash SLSsteam's feed lists nowhere reads None (fail-open).
        sls = self.SLS.replace("dab8df0daa27ffa6594ef5d6bc8cf707f37990220628f1f249fb30f4d88ade91", "f" * 64)
        sls = sls.replace("53bdabbbb63fff0146a459f1f40dc9208661f329810557c462404ba52318bf11", "e" * 64)
        r = dh.pick_downgrade_target(self.LL, "20261119000000", sls, 1795048523, "steamrt64")
        self.assertIsNone(r["possible"])
        self.assertEqual(r["target"], 1794536281)

    def test_no_whitelist_is_unknown(self):
        r = dh.pick_downgrade_target(None, None, self.SLS, 1795048523, "steamrt64")
        self.assertIsNone(r["possible"])

    def test_payload_carries_build_and_line(self):
        pl = dh._real_payload(1794536281, "steamrt64")
        self.assertIn("| TARGET_VERSION=1794536281 CLIENT_LINE=steamrt64 bash", pl)
        self.assertIn("| bash", dh._real_payload())
        self.assertNotIn("TARGET_VERSION", dh._real_payload())


if __name__ == "__main__":
    unittest.main()

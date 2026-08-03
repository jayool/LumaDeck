"""Characterization tests for paths.py's Steam-root candidate list.

Phase-1 hook #1: `_STEAM_PATHS` is now built from platform_info.real_home()
instead of a hardcoded /home/deck. These tests pin the NON-REGRESSION guarantee:
with the real home resolving to /home/deck (the SteamOS/Deck case), the built
list is BYTE-IDENTICAL to the list paths.py hardcoded before this change.

The golden list below is the pre-change literal. If a change makes the SteamOS
assertion fail, the Deck path has regressed — do not "update" the golden,
investigate.

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths  # noqa: E402


# The exact _STEAM_PATHS literal from before the platform_info hook, with
# expanduser("~") == /root (Decky-as-root). This is the frozen oracle.
def _golden_steamos(expanded_home="/root"):
    return [
        "/home/deck/.local/share/Steam",
        "/home/deck/.steam/steam",
        os.path.join(expanded_home, ".steam/steam"),
        os.path.join(expanded_home, ".local/share/Steam"),
        "/opt/steam/steam",
        "/usr/local/steam",
    ]


class TestSteamPathsNonRegression(unittest.TestCase):
    def test_deck_home_reproduces_historical_list_exactly(self):
        # SteamOS: real home is /home/deck, Decky runs as root so ~ == /root.
        built = paths._build_steam_paths("/home/deck", "/root")
        self.assertEqual(built, _golden_steamos("/root"))

    def test_deck_home_with_nonroot_expanded_home(self):
        # Dev/non-root case: ~ is a real home; the tail entries follow it, but
        # the /home/deck leads (and /opt, /usr/local) are unchanged.
        built = paths._build_steam_paths("/home/deck", "/home/dev")
        self.assertEqual(built, _golden_steamos("/home/dev"))


class TestSteamPathsGeneralization(unittest.TestCase):
    def test_non_deck_user_uses_resolved_home(self):
        built = paths._build_steam_paths("/home/jayo", "/root")
        self.assertEqual(built[0], "/home/jayo/.local/share/Steam")
        self.assertEqual(built[1], "/home/jayo/.steam/steam")
        # Fixed system locations are still present and unchanged.
        self.assertIn("/opt/steam/steam", built)
        self.assertIn("/usr/local/steam", built)

    def test_structure_is_stable_length_and_tail(self):
        built = paths._build_steam_paths("/home/whoever", "/root")
        self.assertEqual(len(built), 6)
        self.assertEqual(built[-2:], ["/opt/steam/steam", "/usr/local/steam"])


class TestRealHomeFallback(unittest.TestCase):
    def test_real_home_never_raises_and_is_nonempty(self):
        # _real_home is guarded: any platform_info failure -> "/home/deck".
        h = paths._real_home()
        self.assertTrue(h)
        self.assertTrue(h.startswith("/"))


if __name__ == "__main__":
    unittest.main()

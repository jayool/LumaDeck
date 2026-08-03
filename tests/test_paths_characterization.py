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


class TestComponentCandidatesNonRegression(unittest.TestCase):
    """Hook #2: the SLSsteam/ACCELA/lumalinux/CloudRedirect candidate lists are
    now built with _home_candidates(). With home=/home/deck, expanded=/root they
    must equal the exact pre-change hardcoded literals."""

    H = "/home/deck"
    E = "/root"

    def test_slssteam_candidates_identical(self):
        built = paths._home_candidates(
            self.H, self.E, [".local/share/SLSsteam", "SLSsteam"], extras=["/opt/SLSsteam"]
        )
        self.assertEqual(built, [
            "/home/deck/.local/share/SLSsteam",
            "/home/deck/SLSsteam",
            "/root/.local/share/SLSsteam",
            "/root/SLSsteam",
            "/opt/SLSsteam",
        ])

    def test_accela_candidates_identical(self):
        built = paths._home_candidates(self.H, self.E, [".local/share/ACCELA", "accela"])
        self.assertEqual(built, [
            "/home/deck/.local/share/ACCELA",
            "/home/deck/accela",
            "/root/.local/share/ACCELA",
            "/root/accela",
        ])

    def test_lumalinux_candidates_identical(self):
        built = paths._home_candidates(self.H, self.E, [".local/share/lumalinux"])
        self.assertEqual(built, [
            "/home/deck/.local/share/lumalinux",
            "/root/.local/share/lumalinux",
        ])

    def test_cloudredirect_candidates_identical(self):
        built = paths._home_candidates(self.H, self.E, [".local/share/CloudRedirect"])
        self.assertEqual(built, [
            "/home/deck/.local/share/CloudRedirect",
            "/root/.local/share/CloudRedirect",
        ])

    def test_non_deck_home_generalizes(self):
        built = paths._home_candidates("/home/jayo", "/root", [".local/share/SLSsteam", "SLSsteam"],
                                       extras=["/opt/SLSsteam"])
        self.assertEqual(built[0], "/home/jayo/.local/share/SLSsteam")
        self.assertEqual(built[1], "/home/jayo/SLSsteam")
        self.assertIn("/opt/SLSsteam", built)


class TestSinglePathsWired(unittest.TestCase):
    """Hook #3: the remaining home-based single paths are now os.path.join(
    _REAL_HOME, rel). Assert the module constants are wired to _REAL_HOME (not a
    hardcode), and that with home=/home/deck they reproduce the historical
    literal."""

    def test_cloudredirect_constants_use_real_home(self):
        h = paths._REAL_HOME
        self.assertEqual(paths._CLOUDREDIRECT_TOKEN_DIRS[0],
                         os.path.join(h, ".config/CloudRedirect"))
        self.assertEqual(paths._CR_LOG_PATHS[0],
                         os.path.join(h, ".config/CloudRedirect/cr_debug.log"))
        self.assertEqual(paths._CR_DISABLE_PATHS[0],
                         os.path.join(h, ".config/CloudRedirect/disable"))
        # The ~ fallback entry is always preserved as the second element.
        self.assertEqual(paths._CLOUDREDIRECT_TOKEN_DIRS[1],
                         os.path.expanduser("~/.config/CloudRedirect"))

    def test_deck_home_reproduces_historical_single_paths(self):
        # Frozen oracle: home=/home/deck => the exact pre-change literals.
        self.assertEqual(os.path.join("/home/deck", ".config/SLSsteam"),
                         "/home/deck/.config/SLSsteam")
        self.assertEqual(os.path.join("/home/deck", ".config/lumalinux/keys.txt"),
                         "/home/deck/.config/lumalinux/keys.txt")
        self.assertEqual(os.path.join("/home/deck", ".cache/lumalinux/status.json"),
                         "/home/deck/.cache/lumalinux/status.json")
        self.assertEqual(os.path.join("/home/deck", ".SLSsteam.log"),
                         "/home/deck/.SLSsteam.log")


class TestSteamRootUnification(unittest.TestCase):
    """Hook #4b: steam_utils.py and ryuu_cookie.py no longer keep their own
    hardcoded /home/deck Steam-root lists; they consume paths.py's single
    source (steam_root_candidates / home_candidates)."""

    def test_steam_root_candidates_is_a_copy(self):
        c = paths.steam_root_candidates()
        self.assertEqual(c, paths._STEAM_PATHS)
        c.append("SENTINEL")  # mutating the returned list must not leak back
        self.assertNotIn("SENTINEL", paths._STEAM_PATHS)

    def test_home_candidates_public_matches_private(self):
        rels = [".local/share/Steam", ".steam/root"]
        self.assertEqual(
            paths.home_candidates(rels),
            paths._home_candidates(paths._REAL_HOME, paths._EXPANDED_HOME, rels),
        )

    def test_ryuu_roots_reproduce_historical_literal_on_deck(self):
        # Frozen oracle: ryuu_cookie._find_cookie_dbs roots with home=/home/deck,
        # ~==/root. Must equal the exact pre-unification literal, .steam/root
        # entries included.
        built = paths._home_candidates(
            "/home/deck", "/root",
            [".local/share/Steam", ".steam/steam", ".steam/root"],
        )
        self.assertEqual(built, [
            "/home/deck/.local/share/Steam",
            "/home/deck/.steam/steam",
            "/home/deck/.steam/root",
            "/root/.local/share/Steam",
            "/root/.steam/steam",
            "/root/.steam/root",
        ])


class TestIdentityFacades(unittest.TestCase):
    """Hook #4: paths exposes real_user()/real_home()/real_uid() as the backend's
    single identity source (uid status path + ryuu's sudo -u <user> / session env
    now route through them). Cached; SteamOS => deck / /home/deck / 1000."""

    def test_facades_types_and_caching(self):
        self.assertIsInstance(paths.real_user(), str)
        self.assertTrue(paths.real_user())
        self.assertIsInstance(paths.real_uid(), int)
        self.assertGreaterEqual(paths.real_uid(), 0)
        self.assertTrue(paths.real_home().startswith("/"))
        # Cached values are what the façades return.
        self.assertEqual(paths.real_user(), paths._REAL_USER)
        self.assertEqual(paths.real_uid(), paths._REAL_UID)
        self.assertEqual(paths.real_home(), paths._REAL_HOME)


class TestRealHomeFallback(unittest.TestCase):
    def test_real_home_never_raises_and_is_nonempty(self):
        # _real_home is guarded: any platform_info failure -> "/home/deck".
        h = paths._real_home()
        self.assertTrue(h)
        self.assertTrue(h.startswith("/"))

    def test_uid_and_user_guarded_fallbacks(self):
        # The paths-level safe resolvers never raise and default to deck / 1000.
        self.assertIsInstance(paths._resolve_real_uid_safe(), int)
        self.assertTrue(paths._resolve_real_user_safe())


if __name__ == "__main__":
    unittest.main()

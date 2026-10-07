"""slssteam_ops._find_game_dir_fallback: the folder it returns gets deleted
by uninstall_game_full, so it may only ever be an EXACT match (Valve's
installdir or the game's name). A folder that merely shares a prefix with
the name, or that contains the appid in its name, belongs to some other game.

    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import downloads  # noqa: E402
import slssteam_ops  # noqa: E402
import steam_utils  # noqa: E402

APP = 1942280


class GameDirFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.common = os.path.join(self.tmp, "steamapps", "common")
        os.makedirs(self.common)
        self.name = ""
        self._orig = []

        def patch(mod, attr, value):
            self._orig.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, value)

        async def api(appid):
            # Decky calls uninstall from a running loop, where this strategy
            # cannot run (run_until_complete raises); stubbed empty here.
            return ""
        patch(steam_utils, "detect_steam_install_path", lambda: self.tmp)
        patch(downloads, "_fetch_installdir_from_api", api)
        patch(downloads, "_get_loaded_app_name", lambda appid: self.name)
        patch(downloads, "_get_app_name_from_applist", lambda appid: "")

    def tearDown(self):
        for mod, attr, value in self._orig:
            setattr(mod, attr, value)

    def folder(self, name):
        p = os.path.join(self.common, name)
        os.makedirs(p)
        return p

    def test_exact_name_ignoring_case(self):
        want = self.folder("Brotato")
        self.name = "brotato"
        self.assertEqual(slssteam_ops._find_game_dir_fallback(APP), want)

    def test_a_prefix_match_is_not_the_game(self):
        self.folder("Brotato Demo")
        self.folder("Brotato Soundtrack")
        self.name = "Brotato"
        self.assertEqual(slssteam_ops._find_game_dir_fallback(APP), "")

    def test_the_appid_in_a_folder_name_is_not_the_game(self):
        self.folder(f"app_{APP}")
        self.folder(f"Other Game {APP}")
        self.name = "Brotato"
        self.assertEqual(slssteam_ops._find_game_dir_fallback(APP), "")

    def test_nothing_known_nothing_found(self):
        self.folder("Brotato")
        self.assertEqual(slssteam_ops._find_game_dir_fallback(APP), "")


if __name__ == "__main__":
    unittest.main()

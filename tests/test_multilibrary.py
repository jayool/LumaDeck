"""Multi-library (non-default drive) behaviour of the game list.

See docs/dev-multi-library.md, defect D2.

`get_installed_lua_scripts()` computes `hasGameFiles` against the default Steam
root only (downloads.py:1676), while `.acf` files live in the library the game was
installed into. GameCard.tsx:38 derives the installed state from that flag, so a
game on a second library renders GREYED OUT.

The failing case is marked @unittest.expectedFailure. It does not fail the suite
today; when D2 is fixed unittest reports an UNEXPECTED SUCCESS and the suite DOES
fail, so the decorator cannot be left behind.

    python -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import downloads  # noqa: E402
import steam_utils  # noqa: E402

APPID = 480
NAME = "Fake Game"

# A real, fully-installed manifest as Steam writes it.
ACF = '''"AppState"
{
\t"appid"\t\t"%d"
\t"Universe"\t\t"1"
\t"name"\t\t"%s"
\t"StateFlags"\t\t"4"
\t"installdir"\t\t"%s"
\t"SizeOnDisk"\t\t"12345678"
\t"InstalledDepots"
\t{
\t\t"481"
\t\t{
\t\t\t"manifest"\t\t"111"
\t\t\t"size"\t\t"12345678"
\t\t}
\t}
}
''' % (APPID, NAME, NAME)


class MultiLibraryGameList(unittest.TestCase):
    """Two Steam libraries; the .lua always lives in the install root (it is
    per-install), the .acf in whichever library holds the game."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lumadeck_multilib_")
        self._orig = (downloads.detect_steam_install_path,
                      steam_utils.detect_steam_install_path,
                      downloads._ensure_accela_mark,
                      downloads._preload_app_names_cache)

    def tearDown(self):
        (downloads.detect_steam_install_path,
         steam_utils.detect_steam_install_path,
         downloads._ensure_accela_mark,
         downloads._preload_app_names_cache) = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self, acf_in):
        root = os.path.join(self.tmp, "Steam")
        lib2 = os.path.join(self.tmp, "sdcard")
        os.makedirs(os.path.join(root, "steamapps"))
        os.makedirs(os.path.join(root, "config", "stplug-in"))
        os.makedirs(os.path.join(lib2, "steamapps"))
        with open(os.path.join(root, "config", "stplug-in", "%d.lua" % APPID),
                  "w", encoding="utf-8") as fh:
            fh.write("addappid(%d)\n" % APPID)
        with open(os.path.join(root, "config", "libraryfolders.vdf"),
                  "w", encoding="utf-8") as fh:
            fh.write('"libraryfolders"\n{\n'
                     '\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n'
                     '\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % (root, lib2))
        target = {"root": root, "lib2": lib2}[acf_in]
        with open(os.path.join(target, "steamapps",
                               "appmanifest_%d.acf" % APPID), "w",
                  encoding="utf-8") as fh:
            fh.write(ACF)

        downloads.detect_steam_install_path = lambda: root
        steam_utils.detect_steam_install_path = lambda: root
        downloads._ensure_accela_mark = lambda *a, **k: None   # no subprocesses
        downloads._preload_app_names_cache = lambda: None
        return root, lib2

    def _has_game_files(self, acf_in):
        self._build(acf_in)
        res = downloads.get_installed_lua_scripts()
        self.assertTrue(res.get("success"), res)
        entry = next((s for s in res.get("scripts", [])
                      if s.get("appid") == APPID), None)
        self.assertIsNotNone(entry, "the game is missing from the list entirely")
        return entry["hasGameFiles"]

    @unittest.expectedFailure
    def test_game_in_second_library_is_seen_as_installed(self):
        """D2: a game on the SD card / second partition must not render greyed out."""
        self.assertTrue(self._has_game_files("lib2"))

    def test_game_in_root_library_is_seen_as_installed(self):
        """Control: the single-library case works today."""
        self.assertTrue(self._has_game_files("root"))


if __name__ == "__main__":
    unittest.main()

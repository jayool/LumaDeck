"""The one-off sweep that removes orphan .acf stubs (issue #41).

See docs/dev-multi-library.md, defect D4. An older lumalinux seeded a stub into
the DEFAULT library before the user picked a drive; installing anywhere else
orphaned it, and after the next Steam restart Steam honoured the orphan and
reported the game as not installed.

The sweep only ever removes a stub-shaped manifest whose game is provably
installed in a DIFFERENT library. These tests pin both halves: that it removes
that one, and that it leaves everything else alone.

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

STUB = '''"AppState"
{
\t"appid"\t\t"%d"
\t"name"\t\t"Fake Game"
\t"StateFlags"\t\t"1"
\t"installdir"\t\t"Fake Game"
\t"LastUpdated"\t\t"0"
\t"SizeOnDisk"\t\t"0"
\t"UpdateResult"\t\t"0"
}
''' % APPID

REAL = '''"AppState"
{
\t"appid"\t\t"%d"
\t"name"\t\t"Fake Game"
\t"StateFlags"\t\t"4"
\t"installdir"\t\t"Fake Game"
\t"LastUpdated"\t\t"1750000000"
\t"SizeOnDisk"\t\t"12345678"
\t"InstalledDepots"
\t{
\t\t"481"
\t\t{
\t\t\t"manifest"\t\t"111"
\t\t}
\t}
}
''' % APPID

# Steam's shape for an install it has QUEUED but not started: StateFlags=1 like
# our stub, but with a real LastUpdated. Must never be mistaken for a stub.
QUEUED = '''"AppState"
{
\t"appid"\t\t"%d"
\t"name"\t\t"Fake Game"
\t"StateFlags"\t\t"1"
\t"installdir"\t\t"Fake Game"
\t"LastUpdated"\t\t"1750000000"
\t"SizeOnDisk"\t\t"0"
}
''' % APPID


class OrphanStubSweep(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lumadeck_sweep_")
        self._orig = (downloads.detect_steam_install_path,
                      steam_utils.detect_steam_install_path,
                      downloads.real_home)
        self.root = os.path.join(self.tmp, "Steam")
        self.lib2 = os.path.join(self.tmp, "sdcard")
        os.makedirs(os.path.join(self.root, "steamapps"))
        os.makedirs(os.path.join(self.root, "config"))
        os.makedirs(os.path.join(self.lib2, "steamapps"))
        downloads.detect_steam_install_path = lambda: self.root
        steam_utils.detect_steam_install_path = lambda: self.root
        downloads.real_home = lambda: self.tmp        # kill-switch marker lookup
        os.environ.pop("LUMA_NO_ACF_SWEEP", None)

    def tearDown(self):
        (downloads.detect_steam_install_path,
         steam_utils.detect_steam_install_path,
         downloads.real_home) = self._orig
        os.environ.pop("LUMA_NO_ACF_SWEEP", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------
    def _libraries(self, *paths):
        with open(os.path.join(self.root, "config", "libraryfolders.vdf"),
                  "w", encoding="utf-8") as fh:
            fh.write('"libraryfolders"\n{\n')
            for i, p in enumerate(paths):
                fh.write('\t"%d"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n' % (i, p))
            fh.write("}\n")

    def _put(self, lib, text, appid=APPID):
        path = os.path.join(lib, "steamapps", "appmanifest_%d.acf" % appid)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _exists(self, lib, appid=APPID):
        return os.path.exists(
            os.path.join(lib, "steamapps", "appmanifest_%d.acf" % appid))

    # -- the case the sweep exists for --------------------------------------
    def test_removes_the_orphan_stub_when_the_game_lives_elsewhere(self):
        self._libraries(self.root, self.lib2)
        stub = self._put(self.root, STUB)
        self._put(self.lib2, REAL)

        res = downloads.sweep_orphan_stubs()

        self.assertEqual(res["removed"], [stub])
        self.assertFalse(self._exists(self.root), "the orphan stub must go")
        self.assertTrue(self._exists(self.lib2), "the real manifest must stay")

    # -- everything it must NOT touch ---------------------------------------
    def test_leaves_a_lone_stub_alone(self):
        """No real manifest anywhere: cosmetic only, and unprovable as ours."""
        self._libraries(self.root, self.lib2)
        self._put(self.root, STUB)
        self.assertEqual(downloads.sweep_orphan_stubs()["removed"], [])
        self.assertTrue(self._exists(self.root))

    def test_leaves_two_stubs_alone(self):
        """The appid IS in two libraries, but NEITHER copy is a real install.
        This is what exercises the "a real manifest must exist elsewhere" guard —
        the lone-stub case above never reaches it (it stops at "fewer than two
        entries"), which mutation testing caught."""
        self._libraries(self.root, self.lib2)
        self._put(self.root, STUB)
        self._put(self.lib2, STUB)
        self.assertEqual(downloads.sweep_orphan_stubs()["removed"], [])
        self.assertTrue(self._exists(self.root))
        self.assertTrue(self._exists(self.lib2))

    def test_leaves_a_queued_install_alone(self):
        """StateFlags=1 like our stub, but a real LastUpdated — Steam's, not ours."""
        self._libraries(self.root, self.lib2)
        self._put(self.root, QUEUED)
        self._put(self.lib2, REAL)
        self.assertEqual(downloads.sweep_orphan_stubs()["removed"], [])
        self.assertTrue(self._exists(self.root))

    def test_leaves_two_real_manifests_alone(self):
        self._libraries(self.root, self.lib2)
        self._put(self.root, REAL)
        self._put(self.lib2, REAL)
        self.assertEqual(downloads.sweep_orphan_stubs()["removed"], [])
        self.assertTrue(self._exists(self.root))
        self.assertTrue(self._exists(self.lib2))

    def test_does_nothing_with_a_single_library(self):
        self._libraries(self.root)
        self._put(self.root, STUB)
        res = downloads.sweep_orphan_stubs()
        self.assertEqual(res["reason"], "single_library")
        self.assertTrue(self._exists(self.root))

    def test_survives_an_unparseable_manifest(self):
        self._libraries(self.root, self.lib2)
        self._put(self.root, "this is not a vdf file at all {{{")
        self._put(self.lib2, REAL)
        res = downloads.sweep_orphan_stubs()
        self.assertTrue(res["success"])
        self.assertEqual(res["removed"], [])
        self.assertTrue(self._exists(self.root))

    def test_survives_a_missing_library_directory(self):
        """An SD card that isn't mounted must cost us that library, not the run."""
        self._libraries(self.root, self.lib2, os.path.join(self.tmp, "gone"))
        stub = self._put(self.root, STUB)
        self._put(self.lib2, REAL)
        res = downloads.sweep_orphan_stubs()
        self.assertTrue(res["success"])
        self.assertEqual(res["removed"], [stub])

    def test_removes_a_read_only_stub(self):
        """A legacy DDL-era write could have chmod'd it 0444."""
        self._libraries(self.root, self.lib2)
        stub = self._put(self.root, STUB)
        os.chmod(stub, 0o444)
        self._put(self.lib2, REAL)
        self.assertEqual(downloads.sweep_orphan_stubs()["removed"], [stub])

    def test_skips_an_appid_with_a_download_in_flight(self):
        self._libraries(self.root, self.lib2)
        self._put(self.root, STUB)
        self._put(self.lib2, REAL)

        class _Busy:
            def done(self):
                return False
        downloads.DOWNLOAD_TASKS[APPID] = _Busy()
        try:
            self.assertEqual(downloads.sweep_orphan_stubs()["removed"], [])
            self.assertTrue(self._exists(self.root))
        finally:
            downloads.DOWNLOAD_TASKS.pop(APPID, None)

    def test_kill_switch_env(self):
        self._libraries(self.root, self.lib2)
        self._put(self.root, STUB)
        self._put(self.lib2, REAL)
        os.environ["LUMA_NO_ACF_SWEEP"] = "1"
        res = downloads.sweep_orphan_stubs()
        self.assertEqual(res["reason"], "disabled")
        self.assertTrue(self._exists(self.root))

    def test_kill_switch_marker_file(self):
        self._libraries(self.root, self.lib2)
        self._put(self.root, STUB)
        self._put(self.lib2, REAL)
        marker_dir = os.path.join(self.tmp, ".config", "lumalinux")
        os.makedirs(marker_dir, exist_ok=True)
        open(os.path.join(marker_dir, "no_acf_sweep"), "w").close()
        res = downloads.sweep_orphan_stubs()
        self.assertEqual(res["reason"], "disabled")
        self.assertTrue(self._exists(self.root))


if __name__ == "__main__":
    unittest.main()

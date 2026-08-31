"""get_steam_libraries: a library that isn't there must not be listed.

libraryfolders.vdf can outlive the drive it names — an SD card popped out leaves
its mount point behind as an empty directory. Before this guard such an entry
rode through with freeBytes/totalBytes at 0 (statvfs fails and is swallowed), so
it painted a phantom drive in LumaDeck's Settings and sent every library-aware
lookup hunting for games in a path that does not exist.

    python -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import steam_utils  # noqa: E402


class SteamLibraries(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lumadeck_libs_")
        self.root = os.path.join(self.tmp, "Steam")
        os.makedirs(os.path.join(self.root, "steamapps"))
        os.makedirs(os.path.join(self.root, "config"))
        self._orig = steam_utils.detect_steam_install_path
        steam_utils.detect_steam_install_path = lambda: self.root

    def tearDown(self):
        steam_utils.detect_steam_install_path = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, *paths):
        with open(os.path.join(self.root, "config", "libraryfolders.vdf"),
                  "w", encoding="utf-8") as fh:
            fh.write('"libraryfolders"\n{\n')
            for i, p in enumerate(paths):
                fh.write('\t"%d"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n' % (i, p))
            fh.write("}\n")

    def _paths(self):
        return [l["path"] for l in steam_utils.get_steam_libraries()]

    def test_a_real_library_is_listed(self):
        sd = os.path.join(self.tmp, "sdcard")
        os.makedirs(os.path.join(sd, "steamapps"))
        self._write(self.root, sd)
        self.assertEqual(self._paths(), [self.root, sd])

    def test_a_path_that_does_not_exist_is_skipped(self):
        self._write(self.root, os.path.join(self.tmp, "never_existed"))
        self.assertEqual(self._paths(), [self.root])

    def test_a_mount_point_left_behind_by_a_popped_sd_is_skipped(self):
        """The directory survives the card; steamapps/ does not. The path
        existing is not enough — this is the case a plain os.path.exists misses."""
        ghost = os.path.join(self.tmp, "run_media_mmcblk0p1")
        os.makedirs(ghost)                       # mount point, no steamapps/
        self._write(self.root, ghost)
        self.assertEqual(self._paths(), [self.root])

    def test_the_default_library_still_survives_alone(self):
        self._write(self.root)
        self.assertEqual(self._paths(), [self.root])


if __name__ == "__main__":
    unittest.main()

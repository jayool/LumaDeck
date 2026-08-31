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

    def _write(self, *paths, where="config", apps=None):
        """apps: {library_path: {appid: size}} to embed in the entries."""
        apps = apps or {}
        target = os.path.join(self.root, where)
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, "libraryfolders.vdf"),
                  "w", encoding="utf-8") as fh:
            fh.write('"libraryfolders"\n{\n')
            for i, p in enumerate(paths):
                fh.write('\t"%d"\n\t{\n\t\t"path"\t\t"%s"\n' % (i, p))
                fh.write('\t\t"apps"\n\t\t{\n')
                for appid, size in (apps.get(p) or {}).items():
                    fh.write('\t\t\t"%s"\t\t"%s"\n' % (appid, size))
                fh.write('\t\t}\n\t}\n')
            fh.write("}\n")

    def _lib(self, name):
        d = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(d, "steamapps"), exist_ok=True)
        return d

    def _paths(self):
        return [l["path"] for l in steam_utils.get_steam_libraries()]

    def test_a_real_library_is_listed(self):
        sd = self._lib("sdcard")
        self._write(self.root, sd)
        self.assertEqual(self._paths(), [self.root, sd])

    # -- both copies of the file ---------------------------------------------
    def test_a_library_only_in_the_steamapps_copy_is_found(self):
        """The copy Steam actually LOADS. Reading config/ alone would miss it."""
        sd = self._lib("sdcard")
        self._write(self.root, sd, where="steamapps")
        self.assertEqual(self._paths(), [self.root, sd])

    def test_a_library_only_in_the_config_copy_is_found(self):
        sd = self._lib("sdcard")
        self._write(self.root, sd, where="config")
        self.assertEqual(self._paths(), [self.root, sd])

    def test_the_union_does_not_duplicate(self):
        sd = self._lib("sdcard")
        self._write(self.root, sd, where="steamapps")
        self._write(self.root, sd, where="config")
        self.assertEqual(self._paths(), [self.root, sd])

    def test_each_copy_can_contribute_a_different_library(self):
        """Neither file can hide a library from us — that is the point of the union."""
        a, b = self._lib("libA"), self._lib("libB")
        self._write(self.root, a, where="steamapps")
        self._write(self.root, b, where="config")
        self.assertEqual(sorted(self._paths()), sorted([self.root, a, b]))

    def test_the_root_is_first_even_when_listed_last(self):
        """Settings labels entry 0 as the default library; after a union the file
        order alone no longer guarantees which one that is."""
        sd = self._lib("sdcard")
        self._write(sd, self.root)
        self.assertEqual(self._paths()[0], self.root)

    def test_apps_are_merged_across_the_two_copies(self):
        sd = self._lib("sdcard")
        self._write(self.root, sd, where="steamapps", apps={sd: {"111": "1"}})
        self._write(self.root, sd, where="config", apps={sd: {"222": "2"}})
        libs = {l["path"]: l for l in steam_utils.get_steam_libraries()}
        self.assertEqual(libs[sd]["gameCount"], 2)

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

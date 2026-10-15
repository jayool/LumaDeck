"""remove_game_dlcs only touches the game's entry under DlcData:.

It used to take the first `<appid>:` line anywhere in config.yaml and then
swallow the lines after it until the next one at indent <= 2: the same appid
under FakeAppIds: or AppTokens: would go instead, together with whatever
followed it. uninstall_game_full only got away with it by calling
remove_fake_app_id and remove_game_token first (nosotros.md §4.1-2).

    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import slssteam_ops  # noqa: E402

CONFIG = """# SLSsteam
AdditionalApps:
  - 1794680
  - 504230

FakeAppIds:
  1794680: 480
  504230: 480

AppTokens:
  1794680: "aa"
  504230: "bb"

DlcData:
  1794680:
    2230760: "Legacy of the Moonspell"
    2313550: "Tides of the Foscari"
  504230:
    1070560: "Steam Linux Runtime"

ManifestIds:
  1794681: 6354157889980277978

DisableUpdates: no
"""


class RemoveGameDlcsScoped(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "config.yaml")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(CONFIG)
        self.patches = [
            mock.patch.object(slssteam_ops, "_config_path", return_value=self.path),
            mock.patch.object(slssteam_ops, "_commit_config", lambda src, dst: os.replace(src, dst)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _read(self):
        with open(self.path, encoding="utf-8") as fh:
            return fh.read()

    def test_only_the_dlcdata_entry_goes(self):
        r = slssteam_ops.remove_game_dlcs(1794680)
        self.assertTrue(r["success"])
        out = self._read()
        self.assertEqual(out, CONFIG.replace(
            '  1794680:\n    2230760: "Legacy of the Moonspell"\n    2313550: "Tides of the Foscari"\n', ""))
        # the same appid elsewhere is untouched, and so is the other game's DLC
        self.assertIn("  1794680: 480\n", out)
        self.assertIn('  1794680: "aa"\n', out)
        self.assertIn('  504230:\n    1070560: "Steam Linux Runtime"\n', out)
        self.assertIn("ManifestIds:\n  1794681: 6354157889980277978\n", out)

    def test_last_entry_of_the_block(self):
        slssteam_ops.remove_game_dlcs(504230)
        out = self._read()
        self.assertNotIn("1070560", out)
        self.assertIn('  1794680:\n    2230760: "Legacy of the Moonspell"\n', out)
        self.assertIn("  504230: 480\n", out)
        self.assertIn("ManifestIds:\n  1794681: 6354157889980277978\n", out)

    def test_absent_game_leaves_the_file_alone(self):
        before = os.stat(self.path).st_mtime_ns
        r = slssteam_ops.remove_game_dlcs(2379780)
        self.assertTrue(r["success"])
        self.assertEqual(self._read(), CONFIG)
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)

    def test_whole_file_scan_bug_is_gone(self):
        # Before: the first `1794680:` line was the FakeAppIds one; that line
        # and the `504230: 480` after it were dropped, DlcData untouched.
        slssteam_ops.remove_game_dlcs(1794680)
        out = self._read()
        self.assertIn("FakeAppIds:\n  1794680: 480\n  504230: 480\n", out)
        self.assertNotIn("Moonspell", out)


if __name__ == "__main__":
    unittest.main()

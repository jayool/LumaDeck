"""pins.py: version pin bookkeeping and the .acf "update required" flag.

    python -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pins  # noqa: E402

ACF = '''"AppState"
{
\t"appid"\t\t"2379780"
\t"Universe"\t\t"1"
\t"name"\t\t"Balatro"
\t"StateFlags"\t\t"%s"
\t"installdir"\t\t"Balatro"
\t"buildid"\t\t"17459173"
\t"InstalledDepots"
\t{
\t\t"2379781"
\t\t{
\t\t\t"manifest"\t\t"3512319404653808464"
\t\t\t"size"\t\t"66662933"
\t\t}
\t}
}
'''


class MarkUpdateRequired(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.acf = os.path.join(self.tmp, "appmanifest_2379780.acf")
        self._find_acf = pins.find_acf
        pins.find_acf = lambda appid: self.acf if os.path.isfile(self.acf) else None

    def tearDown(self):
        pins.find_acf = self._find_acf

    def _write(self, flags):
        with open(self.acf, "w", encoding="utf-8") as f:
            f.write(ACF % flags)

    def _read(self):
        with open(self.acf, encoding="utf-8") as f:
            return f.read()

    def test_fully_installed_becomes_update_required(self):
        self._write("4")
        self.assertTrue(pins.mark_update_required(2379780))
        self.assertEqual(self._read(), ACF % "6")   # only that value changed

    def test_already_flagged_is_left_alone(self):
        self._write("6")
        before = self._read()
        self.assertTrue(pins.mark_update_required(2379780))
        self.assertEqual(self._read(), before)

    def test_other_bits_are_preserved(self):
        self._write("1028")                         # FullyInstalled | UpdatePaused
        self.assertTrue(pins.mark_update_required(2379780))
        self.assertIn('"StateFlags"\t\t"1030"', self._read())

    def test_never_touches_buildid_or_depots(self):
        self._write("4")
        pins.mark_update_required(2379780)
        txt = self._read()
        self.assertIn('"buildid"\t\t"17459173"', txt)
        self.assertIn('"manifest"\t\t"3512319404653808464"', txt)

    def test_no_acf(self):
        self.assertFalse(pins.mark_update_required(2379780))

    def test_no_stateflags_line(self):
        with open(self.acf, "w", encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"2379780"\n}\n')
        before = self._read()
        self.assertFalse(pins.mark_update_required(2379780))
        self.assertEqual(self._read(), before)


class FrozenVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._path = pins._STATE_PATH
        pins._STATE_PATH = os.path.join(self.tmp, "pins.json")

    def tearDown(self):
        pins._STATE_PATH = self._path

    def test_version_stored_normalised_and_cleared(self):
        pins.set_frozen(2379780, True, "fix-1", version={
            "buildid": 21512016, "date": "2026-01-15", "label": "Version 1.4.201",
            "gids": {2379781: 1872122861877006892}})
        v = pins.version_info(2379780)
        self.assertEqual(v["buildid"], "21512016")
        self.assertEqual(v["date"], "2026-01-15")
        self.assertEqual(v["gids"], {"2379781": "1872122861877006892"})
        self.assertTrue(pins.is_frozen(2379780))
        pins.set_frozen(2379780, False)
        self.assertIsNone(pins.version_info(2379780))
        with open(pins._STATE_PATH, encoding="utf-8") as f:
            self.assertIsNone(json.load(f)["apps"]["2379780"]["version"])

    def test_freeze_without_version_keeps_previous(self):
        pins.set_frozen(2379780, True, None, version={"buildid": "1", "gids": {}})
        pins.set_frozen(2379780, True, None)          # e.g. the user toggle
        self.assertEqual(pins.version_info(2379780)["buildid"], "1")

    def test_not_frozen_has_no_version(self):
        self.assertIsNone(pins.version_info(2379780))


if __name__ == "__main__":
    unittest.main()

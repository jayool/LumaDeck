"""lift_freeze: the "Let Steam update" button.

Strips exactly the BootStrapper* lines and our `# lumalinux` signature from
steam.cfg, keeps anything else, deletes the file when nothing else remains, and
reports the freeze gone. Exercised by hand on a Deck on 2026-10-14 (`rm
steam.cfg` + start: Steam updated itself); this pins the in-place version.

    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import steam_freeze as sf  # noqa: E402

OUR_PIN = "# lumalinux\nBootStrapperInhibitAll=enable\nBootStrapperForceSelfUpdate=disable\n"


class LiftFreeze(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self._tmp.name, "steam.cfg")
        p = mock.patch.object(sf, "_steam_cfg_path", return_value=self.cfg)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def write(self, text):
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(text)

    def test_our_pin_alone_removes_the_file(self):
        self.write(OUR_PIN)
        self.assertTrue(sf.read_freeze()["frozen"])
        self.assertTrue(sf.read_freeze()["mine"])
        r = sf.lift_freeze()
        self.assertTrue(r["success"] and r["lifted"])
        self.assertFalse(os.path.exists(self.cfg))
        self.assertFalse(sf.read_freeze()["frozen"])

    def test_other_content_is_kept(self):
        self.write("keep=me\n" + OUR_PIN + "also=kept\n")
        r = sf.lift_freeze()
        self.assertTrue(r["success"] and r["lifted"])
        with open(self.cfg, encoding="utf-8") as f:
            self.assertEqual(f.read(), "keep=me\nalso=kept\n")
        self.assertFalse(sf.read_freeze()["frozen"])

    def test_foreign_pin_is_lifted_too(self):
        self.write("BootStrapperInhibitAll=enable\nBootStrapperForceSelfUpdate=disable\n")
        self.assertFalse(sf.read_freeze()["mine"])
        r = sf.lift_freeze()
        self.assertTrue(r["success"] and r["lifted"])
        self.assertFalse(os.path.exists(self.cfg))

    def test_no_file_is_a_no_op(self):
        r = sf.lift_freeze()
        self.assertTrue(r["success"])
        self.assertFalse(r["lifted"])


if __name__ == "__main__":
    unittest.main()

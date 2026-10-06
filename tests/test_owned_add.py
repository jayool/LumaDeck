"""Adding DLC to a game the account OWNS (RESEARCH §21 run E).

Pure pieces, no Steam: the .lua filter that keeps only the DLC depots, and the
`owned` flag in pins.json that uninstall and the game page read.

    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import downloads  # noqa: E402
import pins  # noqa: E402

APP = 262060
KEY = "ab" * 32
LUA = f"""-- Darkest Dungeon
addappid({APP})
addappid(262065,1,"{KEY}")
setManifestid(262065,"111",10)
addappid(702540)
addappid(702541,1,"{KEY}")
--setManifestid(702541,"222",20)
addappid(702542,1,"{KEY}")
setManifestid(702542,"4258374143576351227",40024569)
addtoken({APP},"deadbeef")
-- SHARED DEPOTS
addappid(228989,1,"{KEY}")
"""


class OwnedLuaFilter(unittest.TestCase):
    def test_keeps_dlc_depots_drops_base_and_shared(self):
        text, dropped = downloads._filter_lua_for_owned_base(LUA, APP, {702541, 702542})
        self.assertEqual(sorted(dropped), [228989, 262065])
        self.assertIn(f"addappid({APP})\n", text)              # base AppID line (keyless) stays
        self.assertIn("addappid(702540)\n", text)              # DLC AppID line stays
        self.assertIn('addappid(702541,1,', text)
        self.assertIn('--setManifestid(702541,"222",20)', text)  # commented pin of a DLC depot stays
        self.assertIn('setManifestid(702542,', text)
        self.assertNotIn("262065", text)                       # base depot: key AND pin gone
        self.assertNotIn("228989", text)                       # shared redist gone
        self.assertIn('addtoken(262060,"deadbeef")', text)     # untouched
        self.assertIn("-- SHARED DEPOTS", text)

    def test_no_dlc_depots_drops_everything_keyed(self):
        text, dropped = downloads._filter_lua_for_owned_base(LUA, APP, set())
        self.assertEqual(sorted(dropped), [228989, 262065, 702541, 702542])
        self.assertNotIn(",1,", text)


class OwnedFlag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = pins._STATE_PATH
        pins._STATE_PATH = os.path.join(self.tmp, "pins.json")

    def tearDown(self):
        pins._STATE_PATH = self._orig

    def test_set_and_clear(self):
        self.assertFalse(pins.is_owned(APP))
        pins.set_owned(APP, True)
        self.assertTrue(pins.is_owned(APP))
        pins.set_frozen(APP, True, reason="user")          # other fields do not disturb it
        self.assertTrue(pins.is_owned(APP))
        pins.set_owned(APP, False)
        self.assertFalse(pins.is_owned(APP))
        self.assertTrue(pins.is_frozen(APP))


if __name__ == "__main__":
    unittest.main()

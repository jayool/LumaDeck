"""Ryuu's .lua lists the game's own `addappid(<app>)` LAST; Hubcap lists it
first. steamidra_lite (SteaMidra verbatim) takes the first addappid() as the
game's AppID, so a Ryuu zip installed its keys under the first depot's id
(measured 2026-10-07, app 2379780). LumaDeck now puts the app line first.

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import downloads  # noqa: E402

RYUU = (
    'addappid(2379781,0,"16261e41d3e864018778d4a1d81658521a67d9ffb8543ea7e3e21f0685721af1")\n'
    'setManifestid(2379781,"3512319404653808464")\n'
    'addappid(2379782,0,"d0d563bdb51d625d0ed3a3234be0282f8d9a25d81dce599cdcace7b88c3b4719")\n'
    'setManifestid(2379782,"1898957422191678575")\n'
    'addappid(2379780)'
)
HUBCAP = (
    'addappid(2379780)\n'
    'addappid(2379781,0,"16261e41d3e864018778d4a1d81658521a67d9ffb8543ea7e3e21f0685721af1")\n'
    'setManifestid(2379781,"3512319404653808464",66662933)\n'
)


class AppLineFirst(unittest.TestCase):
    def test_ryuu_order_is_rewritten(self):
        out = downloads._app_line_first(RYUU, 2379780)
        lines = out.splitlines()
        self.assertEqual(lines[0], "addappid(2379780)")
        self.assertEqual(lines.count("addappid(2379780)"), 1)
        # every keyed line and pin survives, in order
        self.assertEqual(lines[1:], RYUU.splitlines()[:-1])

    def test_hubcap_order_is_untouched(self):
        self.assertEqual(downloads._app_line_first(HUBCAP, 2379780), HUBCAP)

    def test_keyed_app_depot_first_is_untouched(self):
        # Brotato from Ryuu: the first addappid is the app id with a key (a
        # depot whose id equals the app id); steamidra already reads it right.
        lua = ('addappid(1942280,0,"bf5b1b4f28c4d1839b85a86e3bfdabc5435f8cc848ca968aec505c86c6ecb52e")\n'
               'addappid(1942281,0,"414b")\nsetManifestid(1942281,"5289220193624029472")\n')
        self.assertEqual(downloads._app_line_first(lua, 1942280), lua)

    def test_missing_app_line_is_added(self):
        lua = 'addappid(11,0,"aa")\nsetManifestid(11,"1")\n'
        out = downloads._app_line_first(lua, 10)
        self.assertEqual(out, "addappid(10)\n" + lua)

    def test_steamidra_reads_the_app_from_the_rewritten_lua(self):
        """The regexes steamidra_lite uses, applied to the rewritten text."""
        import re
        out = downloads._app_line_first(RYUU, 2379780)
        general = re.compile(r"^\s*addappid\s*\(\s*(\d+)", re.MULTILINE)
        keyed = re.compile(r"^\s*addappid\s*\(\s*(\d+)\s*,\s*\d\s*,\s*(?:\"|\')(\S+)(?:\"|\')\s*\)", re.MULTILINE)
        self.assertEqual(general.search(out).group(1), "2379780")
        self.assertEqual([d for d, _ in keyed.findall(out)], ["2379781", "2379782"])


if __name__ == "__main__":
    unittest.main()

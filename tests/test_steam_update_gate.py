"""The soft gate behind "Let Steam update" (backend/steam_update_gate.py).

Fixtures are the real shapes of 2026-10-14: lumalinux's feed annotating
1788291500 / 1788652215 on bc54101b and 1791918634 on 0d01ab4f; SLSsteam's feed
listing bc54101b under its 20260903114323 tag and (in the "fixed" variant) 0d01ab4f
under a newer tag. Valve's stable build is 1791918634.

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import steam_update_gate as g  # noqa: E402

OLD = "bc54101b290f9a5b4a0713c9084494a5f05097826f66a661dbe322c469b764a2"
NEW = "0d01ab4fe889f87314c8416d18a2152b130a93231bb19cd6f0ed2ebd7a7ab90a"
GROUP = "20260922150000"

LL_FEED = f"""\
SafeModeHashes:
  {GROUP}:
    # steam_version: 1788652215
    # steam_version: 1788291500
    - {OLD}
    # steam_version: 1791918634
    - {NEW}
  20260611150000:
    - 64b86a11264c1f51e5573a7c25f7862d550622fab7595d89d511f8053b6217d9
"""

SLS_BROKEN = f"""\
SafeModeHashes:
  20260815201341: #tag 20260815201341
    - {OLD} #ubuntu12_32 & steamdeck_stable - 20260902

  20260903114323: #tag 20260903114323
    - {OLD} #ubuntu12_32 & steamdeck_stable - 20260902
    - 237495b4bf3d5ed8fb1fabfad86154428fb2e6f47b8169bcb154f6e25bcc1abd #ubuntu12_32 - 20260903
"""

SLS_FIXED = SLS_BROKEN + f"""
  20261015120000: #tag 20261015120000
    - {NEW} #ubuntu12_32 & steamdeck_stable - 20261014
"""

MANIFEST = '"ubuntu12"\n{\n\t"version"\t\t"1791918634"\n\t"bins"\n\t{\n\t\t"file"\t\t"x"\n\t}\n}\n'


class Parsing(unittest.TestCase):
    def test_manifest_version(self):
        self.assertEqual(g.parse_manifest_version(MANIFEST), 1791918634)
        self.assertIsNone(g.parse_manifest_version("nope"))
        self.assertIsNone(g.parse_manifest_version(None))

    def test_slssteam_tag_for_hash_picks_the_newest_tag(self):
        self.assertEqual(g.slssteam_tag_for_hash(SLS_BROKEN, OLD), "20260903114323")
        self.assertEqual(g.slssteam_tag_for_hash(SLS_FIXED, NEW), "20261015120000")
        self.assertIsNone(g.slssteam_tag_for_hash(SLS_BROKEN, NEW))
        self.assertIsNone(g.slssteam_tag_for_hash(None, NEW))


class Evaluate(unittest.TestCase):
    """Today's Deck: pinned at 1788291500, Valve stable 1791918634."""

    def test_slssteam_not_fixed_yet(self):
        r = g.evaluate(1791918634, LL_FEED, GROUP, SLS_BROKEN, "20261001163836")
        self.assertEqual(r["state"], "not_yet")
        self.assertEqual(r["blocker"], "slssteam")
        self.assertEqual(r["hash"], NEW)
        self.assertTrue(r["lumalinux_ready"])

    def test_slssteam_released_but_not_installed(self):
        r = g.evaluate(1791918634, LL_FEED, GROUP, SLS_FIXED, "20261001163836")
        self.assertEqual(r["state"], "update_slssteam")
        self.assertEqual(r["slssteam_required"], "20261015120000")

    def test_everything_ready(self):
        r = g.evaluate(1791918634, LL_FEED, GROUP, SLS_FIXED, "20261015120000")
        self.assertEqual(r["state"], "ready")
        self.assertIsNone(r["blocker"])

    def test_unknown_installed_slssteam_counts_as_ready(self):
        # No recorded tag: "we don't know" must not block (Components can't offer
        # the SLSsteam update either; the user updates by hand if needed).
        r = g.evaluate(1791918634, LL_FEED, GROUP, SLS_FIXED, None)
        self.assertEqual(r["state"], "ready")

    def test_lumalinux_feed_has_no_hash_for_the_build(self):
        r = g.evaluate(1799999999, LL_FEED, GROUP, SLS_FIXED, "20261015120000")
        self.assertEqual(r["state"], "not_yet")
        self.assertEqual(r["blocker"], "lumalinux")

    def test_lumalinux_release_group_does_not_cover_it(self):
        # Annotated, but under a group the latest release does not carry.
        feed = LL_FEED.replace(f"  {GROUP}:", "  20270101000000:")
        r = g.evaluate(1791918634, feed, GROUP, SLS_FIXED, "20261015120000")
        self.assertEqual(r["state"], "not_yet")
        self.assertEqual(r["blocker"], "lumalinux")

    def test_no_manifest_or_feeds_is_unknown(self):
        self.assertEqual(g.evaluate(None, LL_FEED, GROUP, SLS_FIXED, "x")["state"], "unknown")
        self.assertEqual(g.evaluate(1791918634, None, GROUP, SLS_FIXED, "x")["state"], "unknown")
        self.assertEqual(g.evaluate(1791918634, LL_FEED, GROUP, None, "x")["state"], "unknown")


if __name__ == "__main__":
    unittest.main()

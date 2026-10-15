"""Two build labels, one steamclient.so: the pin counts as reached.

Valve relabelled the Deck stable client from 1788291500 to 1788652215 on
2026-09-05 without changing steamclient.so (bc54101b…). headcrab.sh carries the
new label, headcrab's pinned manifest (what downgrade.sh stages) the old one. The
first live downgrade (2026-10-14) would therefore have landed on 1788291500 with a
target of 1788652215 — "behind the pin" — and install_via_setup's catch-up lift
would have removed the pin at once, sending Steam straight back up.

res/updates.yaml now annotates both labels on the bc54101b entry; these tests pin
the lookup and the normalisation that reads it.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import headcrab_compat as hc  # noqa: E402

OLD = "bc54101b290f9a5b4a0713c9084494a5f05097826f66a661dbe322c469b764a2"
NEW = "0d01ab4fe889f87314c8416d18a2152b130a93231bb19cd6f0ed2ebd7a7ab90a"

# The shape of the real group: prose comments, two labels on one hash, then a
# second build with its own label.
FEED = f"""\
SafeModeHashes:
  20260922150000:
    # v0.22.0 pattern set.
    # steam_version: 1788652215
    # caps: shader=ok reconcile=ok gmrc=ok
    # Same binary Valve served as 1788291500 on 2026-09-02.
    # steam_version: 1788291500
    - {OLD}
    # steam_version: 1791918634
    # caps: shader=ok reconcile=ok gmrc=ok
    - {NEW}
  20260611150000:
    - 64b86a11264c1f51e5573a7c25f7862d550622fab7595d89d511f8053b6217d9
    # steam_version: 1782344391   (build d8f6, 2026-06-19)
    - f5eb8bd3e98ac34b9f4610d9303cc4fbd931c672cb2d21b126e687bab95d9a95
"""


class HashForBuild(unittest.TestCase):
    def test_both_labels_map_to_the_one_hash(self):
        self.assertEqual(hc._hash_for_build(FEED, 1788652215), OLD)
        self.assertEqual(hc._hash_for_build(FEED, 1788291500), OLD)

    def test_the_next_build_has_its_own_hash(self):
        self.assertEqual(hc._hash_for_build(FEED, 1791918634), NEW)

    def test_trailing_prose_after_the_label_is_fine(self):
        self.assertEqual(hc._hash_for_build(FEED, 1782344391),
                         "f5eb8bd3e98ac34b9f4610d9303cc4fbd931c672cb2d21b126e687bab95d9a95")

    def test_unknown_build_or_missing_feed_is_none(self):
        self.assertIsNone(hc._hash_for_build(FEED, 999))
        self.assertIsNone(hc._hash_for_build(None, 1788652215))
        self.assertIsNone(hc._hash_for_build(FEED, None))

    def test_share_binary(self):
        self.assertTrue(hc.builds_share_binary(FEED, 1788291500, 1788652215))
        self.assertFalse(hc.builds_share_binary(FEED, 1791918634, 1788652215))
        self.assertIsNone(hc.builds_share_binary(FEED, 999, 1788652215))


class CompatNormalisation(unittest.TestCase):
    def _compat(self, installed, target, feed=FEED):
        async def _text():
            return feed

        async def _target():
            return target

        async def _group():
            return "20260922150000"

        with mock.patch.object(hc, "current_steam_build", return_value=installed), \
             mock.patch.object(hc, "headcrab_target", _target), \
             mock.patch.object(hc, "_lumalinux_updates_text", _text), \
             mock.patch.object(hc, "latest_release_group", _group):
            return asyncio.run(hc.check_headcrab_compat())

    def test_downgraded_deck_counts_as_at_the_pin(self):
        # The 2026-10-14 case: manifest says 1788291500, headcrab.sh says 1788652215.
        c = self._compat(1788291500, 1788652215)
        self.assertTrue(c["compatible"])
        self.assertEqual(c["target"], 1788291500)   # so nothing reads "behind the pin"
        self.assertEqual(c["current_build"], 1788291500)

    def test_a_genuinely_newer_target_is_untouched(self):
        c = self._compat(1788652215, 1791918634)
        self.assertFalse(c["compatible"])
        self.assertEqual(c["target"], 1791918634)

    def test_unknown_hashes_change_nothing(self):
        c = self._compat(1788291500, 1788652215, feed="SafeModeHashes:\n  1:\n    - abc\n")
        self.assertFalse(c["compatible"])
        self.assertEqual(c["target"], 1788652215)


if __name__ == "__main__":
    unittest.main()

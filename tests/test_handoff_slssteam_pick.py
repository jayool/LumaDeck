"""Fix in Desktop must install an SLSsteam that hooks the client it downgrades to
(backend/desktop_handoff.slssteam_override_for_target). Real feed of 2026-10-14.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import desktop_handoff as dh  # noqa: E402

OLD = "bc54101b290f9a5b4a0713c9084494a5f05097826f66a661dbe322c469b764a2"
NEW = "0d01ab4fe889f87314c8416d18a2152b130a93231bb19cd6f0ed2ebd7a7ab90a"
SLS_REAL = f"""\
SafeModeHashes:
  20260903114323: #tag 20260903114323
    - {OLD} #ubuntu12_32 & steamdeck_stable - 20260902
  20261014151919: #tag 20261014151919
    - {NEW} #ubuntu12_32 & steamdeck_stable 20261014
"""


class Pick(unittest.TestCase):
    def test_target_hooked_by_latest_needs_no_override(self):
        self.assertEqual(dh.slssteam_override_for_target(SLS_REAL, NEW), {"url": None, "tag": None})

    def test_target_dropped_by_latest_pins_the_release_that_hooks_it(self):
        p = dh.slssteam_override_for_target(SLS_REAL, OLD)
        self.assertEqual(p["tag"], "20260903114323")
        self.assertEqual(p["url"], "https://github.com/AceSLS/SLSsteam/releases/download/20260903114323/SLSsteam-Any-release.7z")

    def test_orphan_target_is_refused(self):
        self.assertIn("error", dh.slssteam_override_for_target(SLS_REAL, "ec96ee3c" + "0" * 56))

    def test_unknown_hash_or_feed_is_refused(self):
        self.assertIn("error", dh.slssteam_override_for_target(SLS_REAL, None))
        self.assertIn("error", dh.slssteam_override_for_target(None, OLD))

    def test_payload_carries_the_env_only_when_pinned(self):
        self.assertIn("| {sls_env} bash", dh._REAL_PAYLOAD)
        self.assertIn("|  bash", dh._REAL_PAYLOAD.replace("{sls_env}", ""))
        self.assertIn("| SLSSTEAM_7Z_URL=x bash", dh._REAL_PAYLOAD.replace("{sls_env}", "SLSSTEAM_7Z_URL=x"))


if __name__ == "__main__":
    unittest.main()

"""Fix in Desktop is refused when the latest SLSsteam no longer hooks the client it
would downgrade to (backend/desktop_handoff.downgrade_target_ok). Real feed of
2026-10-14: 20261014151919 lists only 0d01ab4f, so downgrading to bc54101b and
then installing the latest SLSsteam breaks Steam; the fix there is Update.
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
SLS_MORNING = SLS_REAL.split("  20261014151919")[0]   # before Ace's release


class Target(unittest.TestCase):
    def test_before_aces_release_the_old_client_is_fine(self):
        # This morning: latest SLSsteam (20260903 group) hooks bc54101b -> downgrade allowed.
        self.assertIsNone(dh.downgrade_target_ok(SLS_MORNING, OLD))

    def test_after_aces_release_the_old_client_is_refused(self):
        self.assertIn("update the components", dh.downgrade_target_ok(SLS_REAL, OLD))

    def test_target_hooked_by_latest_is_fine(self):
        self.assertIsNone(dh.downgrade_target_ok(SLS_REAL, NEW))

    def test_unknown_hash_or_feed_is_refused(self):
        self.assertIsNotNone(dh.downgrade_target_ok(SLS_REAL, None))
        self.assertIsNotNone(dh.downgrade_target_ok(None, OLD))

    def test_payload_runs_setup_sh_plain(self):
        self.assertIn("| bash", dh._REAL_PAYLOAD)
        self.assertNotIn("sls_env", dh._REAL_PAYLOAD)


if __name__ == "__main__":
    unittest.main()

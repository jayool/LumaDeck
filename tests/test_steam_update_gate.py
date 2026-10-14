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


# SLSsteam's real feed on 2026-10-14 16:00: 20261014151919 opened a new group that
# lists ONLY the new client. The old client bc54101b stays under 20260903114323.
# (SLS_FIXED above is the hypothetical "both listed" shape; this is what shipped.)
SLS_REAL = SLS_BROKEN + f"""
  20261014151919: #tag 20261014151919
    - {NEW} #ubuntu12_32 & steamdeck_stable 20261014
"""


class SupportRule(unittest.TestCase):
    """A release hooks a hash iff the newest group tagged at or before the release
    lists it. 20261001163836 (group 20260903114323) hooks bc54101b; 20261014151919
    does not — that is the combination that crash-looped Steam today."""

    def test_groups_parse_in_order(self):
        tags = [t for t, _ in g.slssteam_groups(SLS_REAL)]
        self.assertEqual(tags, ["20260815201341", "20260903114323", "20261014151919"])

    def test_release_between_groups_uses_the_previous_group(self):
        self.assertEqual(g.slssteam_group_for_release(SLS_REAL, "20261001163836"), "20260903114323")
        self.assertEqual(g.slssteam_group_for_release(SLS_REAL, "20261014151919"), "20261014151919")
        self.assertIsNone(g.slssteam_group_for_release(SLS_REAL, "20250101000000"))

    def test_newer_release_can_drop_an_old_client(self):
        self.assertTrue(g.slssteam_supports(SLS_REAL, "20261001163836", OLD))
        self.assertFalse(g.slssteam_supports(SLS_REAL, "20261001163836", NEW))
        self.assertFalse(g.slssteam_supports(SLS_REAL, "20261014151919", OLD))
        self.assertTrue(g.slssteam_supports(SLS_REAL, "20261014151919", NEW))

    def test_latest(self):
        self.assertEqual(g.slssteam_latest_group(SLS_REAL), "20261014151919")
        self.assertFalse(g.slssteam_latest_supports(SLS_REAL, OLD))
        self.assertTrue(g.slssteam_latest_supports(SLS_REAL, NEW))
        self.assertIsNone(g.slssteam_latest_supports(None, NEW))
        self.assertIsNone(g.slssteam_latest_supports(SLS_REAL, None))

    def test_evaluate_with_the_real_feed(self):
        # Jayo's Deck 15:55: pinned on bc54101b, SLSsteam 20261001 -> update it.
        r = g.evaluate(1791918634, LL_FEED, GROUP, SLS_REAL, "20261001163836")
        self.assertEqual(r["state"], "ready")
        self.assertTrue(r["slssteam_update_pending"])
        self.assertEqual(r["slssteam_required"], "20261014151919")
        # After the update: ready, nothing pending.
        r2 = g.evaluate(1791918634, LL_FEED, GROUP, SLS_REAL, "20261014151919")
        self.assertEqual((r2["state"], r2["slssteam_update_pending"]), ("ready", False))


class PlanSetup(unittest.TestCase):
    """What a setup.sh run may install while our pin holds Steam at a client."""

    def ready(self):
        return g.evaluate(1791918634, LL_FEED, GROUP, SLS_REAL, "20261014151919")

    def test_no_pin_means_nothing_special(self):
        self.assertIsNone(g.plan_setup(False, SLS_REAL, OLD, self.ready())["refuse"])

    def test_latest_still_hooks_the_pinned_client(self):
        # Hypothetical feed where the new release kept the old client.
        kept = SLS_REAL.replace(f"    - {NEW} #ubuntu12_32 & steamdeck_stable 20261014",
                                f"    - {OLD}\n    - {NEW}")
        self.assertTrue(g.slssteam_latest_supports(kept, OLD))
        self.assertIsNone(g.plan_setup(True, kept, OLD, None)["refuse"])

    def test_todays_case_refuses_and_says_lift_first(self):
        # Pinned on bc54101b; latest SLSsteam dropped it but hooks 1791918634, as
        # does lumalinux: do NOT install it here; Let Steam update first.
        p = g.plan_setup(True, SLS_REAL, OLD, self.ready())
        self.assertIn("Let Steam update first", p["refuse"])

    def test_new_build_not_ready_refuses(self):
        # Pinned on bc54101b; latest SLSsteam dropped it and lumalinux has no hash
        # for Valve's build yet: nothing safe to install, say so.
        not_ready = g.evaluate(1799999999, LL_FEED, GROUP, SLS_REAL, "20261014151919")
        self.assertEqual(not_ready["state"], "not_yet")
        p = g.plan_setup(True, SLS_REAL, OLD, not_ready)
        self.assertIn("wait", p["refuse"])

    def test_no_release_hooks_the_pinned_client_refuses(self):
        orphan = "ec96ee3c" + "0" * 56   # the SteamOS image client of 2026-10-14
        p = g.plan_setup(True, SLS_REAL, orphan, g.evaluate(1799999999, LL_FEED, GROUP, SLS_REAL, None))
        self.assertIsNotNone(p["refuse"])

    def test_orphan_client_but_valves_build_ready_says_lift_first(self):
        orphan = "ec96ee3c" + "0" * 56
        p = g.plan_setup(True, SLS_REAL, orphan, self.ready())
        self.assertIn("Let Steam update first", p["refuse"])

    def test_feed_or_hash_unavailable_installs_latest(self):
        self.assertIsNone(g.plan_setup(True, None, OLD, None)["refuse"])
        self.assertIsNone(g.plan_setup(True, SLS_REAL, None, None)["refuse"])


class Evaluate(unittest.TestCase):
    """Today's Deck: pinned at 1788291500, Valve stable 1791918634."""

    def test_slssteam_not_fixed_yet(self):
        r = g.evaluate(1791918634, LL_FEED, GROUP, SLS_BROKEN, "20261001163836")
        self.assertEqual(r["state"], "not_yet")
        self.assertEqual(r["blocker"], "slssteam")
        self.assertEqual(r["hash"], NEW)
        self.assertTrue(r["lumalinux_ready"])

    def test_slssteam_released_but_not_installed_is_still_ready(self):
        # Lift first (old SLSsteam aborts cleanly on the new build), then Update.
        r = g.evaluate(1791918634, LL_FEED, GROUP, SLS_FIXED, "20261001163836")
        self.assertEqual(r["state"], "ready")
        self.assertTrue(r["slssteam_update_pending"])
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

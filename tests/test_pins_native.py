"""pins.py: which model the local pass applies per gmrc.json state.

Pure decision logic, no Steam, no network: lumalinux's gmrc.json, ManifestIds,
keys.txt, steamidra and the archive are stubbed; the assertions are on what
the pass DOES (pin / unpin / freeze / release) for each kind of game.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pins  # noqa: E402

NATIVE, USER, OURS, LEGACY = 100, 200, 300, 400   # appids: see setUp


class PinsNativeModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = {}
        self.calls = []
        self.mids = {}          # ManifestIds, {depot: gid}
        self.state = None       # gmrc.json content, or None

        def patch(name, value):
            self._orig[name] = getattr(pins, name)
            setattr(pins, name, value)

        patch("_STATE_PATH", os.path.join(self.tmp, "pins.json"))
        patch("managed_apps", lambda: [NATIVE, USER, OURS, LEGACY])
        patch("keyed_depots", lambda appid: {appid + 1: "k" * 64})
        patch("read_manifest_ids", lambda: dict(self.mids))
        patch("_download_busy", lambda appid: False)
        patch("_read_gmrc_json", lambda: self.state)

        async def ensure_pinned(appid, allow_pin=True):
            self.calls.append(("ensure_pinned", appid, allow_pin))
            d = appid + 1
            if allow_pin and d not in self.mids:
                self.mids[d] = 999
            return {d: self.mids[d]} if d in self.mids else {}

        async def unpin_game_depots(appid):
            self.calls.append(("unpin", appid))
            self.mids.pop(appid + 1, None)
            return True

        patch("ensure_pinned", ensure_pinned)
        patch("unpin_game_depots", unpin_game_depots)

        # NATIVE: no pin, not frozen.  USER: pinned, frozen by the user.
        # OURS: pinned, frozen by us (providers).  LEGACY: pinned, not frozen.
        self.mids = {USER + 1: 11, OURS + 1: 22, LEGACY + 1: 33}
        pins.set_frozen(USER, True)
        pins.set_frozen(OURS, True, reason=pins.FREEZE_REASON_PROVIDERS)
        pins._probe_ok_at = 0.0

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(pins, k, v)

    def run_pass(self):
        asyncio.run(pins.local_pass())

    def unpinned(self):
        return [c[1] for c in self.calls if c[0] == "unpin"]

    def pinned_by_pass(self):
        return [c[1] for c in self.calls if c[0] == "ensure_pinned" and c[2]]

    # ── up: native ────────────────────────────────────────────────────────
    def test_up_releases_ours_and_legacy_keeps_users(self):
        self.state = {"providers": "up", "at": "2026-09-16T10:00:00Z"}
        self.run_pass()
        self.assertEqual(sorted(self.unpinned()), [OURS, LEGACY])
        self.assertNotIn(NATIVE, self.pinned_by_pass())
        self.assertIn(USER, self.pinned_by_pass())          # theirs: kept and healed
        self.assertFalse(pins.is_frozen(OURS))              # our freeze cleared
        self.assertTrue(pins.user_frozen(USER))             # user freeze untouched
        self.assertNotIn(USER + 1, self.unpinned())
        self.assertIn(USER + 1, self.mids)

    def test_up_new_installs_are_not_pinned(self):
        self.state = {"providers": "up", "at": "2026-09-16T10:00:00Z"}
        self.assertFalse(pins.pin_new_installs())

    # ── down: freeze to installed ─────────────────────────────────────────
    def test_down_freezes_unfrozen_games_and_marks_them(self):
        self.state = {"providers": "down", "at": "2026-09-16T10:00:00Z"}
        self.run_pass()
        self.assertEqual(self.unpinned(), [])
        self.assertTrue(pins.frozen_by_providers(NATIVE))
        self.assertTrue(pins.frozen_by_providers(LEGACY))
        self.assertTrue(pins.frozen_by_providers(OURS))      # still ours
        self.assertTrue(pins.user_frozen(USER))              # still theirs
        self.assertIn(NATIVE + 1, self.mids)                 # pinned to installed
        self.assertTrue(pins.pin_new_installs())

    # ── absent: the 0.8.x model ───────────────────────────────────────────
    def test_absent_pins_everything_and_never_unpins(self):
        self.state = None
        self.run_pass()
        self.assertEqual(self.unpinned(), [])
        self.assertIn(NATIVE, self.pinned_by_pass())
        self.assertIn(NATIVE + 1, self.mids)
        self.assertFalse(pins.is_frozen(NATIVE))             # pinned, not frozen
        self.assertTrue(pins.pin_new_installs())

    # ── recovery: our probe overrides a stale "down" ──────────────────────
    def test_probe_newer_than_lumalinux_reads_as_up(self):
        self.state = {"providers": "down", "at": "2026-09-16T10:00:00Z"}
        self.assertEqual(pins.gmrc_state(), "down")
        pins._probe_ok_at = pins._iso_epoch("2026-09-16T10:30:00Z")
        self.assertEqual(pins.gmrc_state(), "up")
        pins._probe_ok_at = pins._iso_epoch("2026-09-16T09:00:00Z")   # older: no
        self.assertEqual(pins.gmrc_state(), "down")

    # ── the toggle reports only the user's freeze ─────────────────────────
    def test_status_does_not_report_our_freeze_as_pinned(self):
        import downloads
        st = asyncio.run(downloads.get_pin_status(OURS))
        self.assertTrue(st["success"])
        self.assertFalse(st["pinned"])
        st = asyncio.run(downloads.get_pin_status(USER))
        self.assertTrue(st["pinned"])


if __name__ == "__main__":
    unittest.main()

"""paths.read_crash_guard / paths.clear_crash_guard — the launcher's crash guard
(lumalinux/setup.sh `luma_guard_run`) as LumaDeck sees it.

Why this exists: on 2026-09-23 a Deck sat in the guard's safe mode for an hour
while the QAM said "Restart needed" and offered a restart that could never work
(the launcher goes vanilla again until the state files go). The plugin must read
the latch, and the retry must remove exactly the four state files and nothing
else. Real files in a temp dir, no Steam, no network:
    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths  # noqa: E402

LATCH_LOG = """2026-09-23 10:09:41 previous boot crashed at startup -> fail 1/3
2026-09-23 10:13:02 previous boot crashed at startup -> fail 2/3
2026-09-23 10:22:09 previous boot crashed at startup -> fail 3/3
2026-09-23 10:22:09 latching safe mode (fails=3 client_changed=0) -> vanilla (/usr/lib/steamos/steam-launcher)
2026-09-23 10:55:52 safe mode active -> launching Steam vanilla (/usr/lib/steamos/steam-launcher)
"""

CLIENT_LOG = """2026-09-30 09:00:00 steamclient.so changed since last clean boot -> first crash = compat break
2026-09-30 09:00:00 previous boot crashed at startup -> fail 1/3
2026-09-30 09:00:00 latching safe mode (fails=1 client_changed=1) -> vanilla (/usr/bin/steam)
"""


class CrashGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, ".local/state/lumalinux")
        self._saved = paths._REAL_HOME
        paths._REAL_HOME = self.tmp
        self.addCleanup(lambda: setattr(paths, "_REAL_HOME", self._saved))
        # No Dev override in these tests.
        import dev
        self._dev_get = dev.get
        dev.get = lambda key: None
        self.addCleanup(lambda: setattr(dev, "get", self._dev_get))

    def _write(self, name, text=""):
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_no_state_dir_is_inactive(self):
        self.assertEqual(paths.read_crash_guard(),
                         {"active": False, "fails": 0, "since": None, "client_changed": False})

    def test_state_dir_without_latch_is_inactive(self):
        # A normal injected launch leaves last_launch and a counter, never safe_mode.
        self._write("last_launch")
        self._write("boot_fail_count", "1")
        self.assertFalse(paths.read_crash_guard()["active"])

    def test_latched_after_three_crashes(self):
        self._write("safe_mode")
        self._write("safe_mode_fingerprint", "1|2|3|4|")
        self._write("boot_fail_count", "3")
        self._write("guard.log", LATCH_LOG)
        g = paths.read_crash_guard()
        self.assertEqual(g, {"active": True, "fails": 3,
                             "since": "2026-09-23 10:22:09", "client_changed": False})

    def test_latched_on_first_crash_after_a_steam_update(self):
        self._write("safe_mode")
        self._write("boot_fail_count", "1")
        self._write("guard.log", CLIENT_LOG)
        g = paths.read_crash_guard()
        self.assertTrue(g["active"])
        self.assertEqual(g["fails"], 1)
        self.assertTrue(g["client_changed"])
        self.assertEqual(g["since"], "2026-09-30 09:00:00")

    def test_latch_without_a_log_is_still_active(self):
        # safe_mode is the truth; the log only decorates it.
        self._write("safe_mode")
        g = paths.read_crash_guard()
        self.assertTrue(g["active"])
        self.assertIsNone(g["since"])

    def test_last_latch_line_wins(self):
        # Two latches over time: the newest one describes the current state.
        self._write("safe_mode")
        self._write("guard.log", LATCH_LOG + "2026-09-24 12:00:00 payload changed since latch -> clearing safe mode, retrying injection\n" + CLIENT_LOG)
        g = paths.read_crash_guard()
        self.assertEqual(g["since"], "2026-09-30 09:00:00")
        self.assertTrue(g["client_changed"])

    def test_dev_override_forges_a_latch(self):
        import dev
        dev.get = lambda key: "active" if key == "crash_guard" else None
        g = paths.read_crash_guard()
        self.assertTrue(g["active"])
        self.assertFalse(os.path.isdir(self.dir))   # nothing on disk was needed

    def test_clear_removes_exactly_the_four_state_files(self):
        for name in ("safe_mode", "safe_mode_fingerprint", "boot_fail_count", "last_launch",
                     "last_client", "good_client"):
            self._write(name, "x")
        self._write("guard.log", LATCH_LOG)
        r = paths.clear_crash_guard()
        self.assertTrue(r["success"])
        self.assertEqual(sorted(r["removed"]),
                         ["boot_fail_count", "last_launch", "safe_mode", "safe_mode_fingerprint"])
        self.assertEqual(sorted(os.listdir(self.dir)), ["good_client", "guard.log", "last_client"])
        self.assertFalse(paths.read_crash_guard()["active"])

    def test_clear_when_nothing_is_latched_is_a_no_op(self):
        r = paths.clear_crash_guard()
        self.assertTrue(r["success"])
        self.assertEqual(r["removed"], [])


if __name__ == "__main__":
    unittest.main()

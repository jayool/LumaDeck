"""SLSsteam's fatal log lines must all map to a non-healthy state.

SLSsteam (src/main.cpp) can give up at five points before placing any hook, each
with its own notify line. Until 2026-10-14 LumaDeck recognised only two of them,
so on the 1791918634 Steam client, where SLSsteam aborted with "Failed to parse
VFTables!" (its vtable parser could not find GetAvailableCompatToolsForApp),
read_slssteam_health reported SLSsteam *healthy*: the .so was mapped and the log
matched nothing. The fixture below is that real log.

    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths  # noqa: E402


# Verbatim from a Steam Deck on client 1791918634 with SLSsteam 20261001163836
# (2026-10-14): the vtable parser misses a method and load() returns early.
VFTABLES_LOG = (
    "[Info|Once in src/config.hpp:getSetting:134] WarnHashMissmatch is 0\n"
    "[Error in src/vftableinfo.cpp:init:46] GetAvailableCompatToolsForApp not found!\n"
    "[Notify Long|Error in src/main.cpp:load:202] Failed to parse VFTables! Aborting...\n"
)

FATAL_LINES = {
    "Unknown steamclient.so hash! Aborting...": "hash",
    "Failed to find all patterns! Aborting...": "patterns",
    "Failed to parse VFTables! Aborting...": "vftables",
    "Failed to setup & place hooks! Aborting...": "hooks",
    "Failed to find steam exports!": "exports",
}


class _WithLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self._tmp.name, ".SLSsteam.log")
        patcher = mock.patch.object(paths, "_slssteam_log_path", return_value=self.log)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def write(self, text):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write(text)


class TestAbortCause(_WithLog):
    def test_real_vftables_log_is_fatal(self):
        self.write(VFTABLES_LOG)
        self.assertEqual(paths._slssteam_log_abort_cause(), "vftables")

    def test_every_fatal_line_is_recognised(self):
        for line, cause in FATAL_LINES.items():
            with self.subTest(line=line):
                self.write(f"[Info] steamclient.so loaded\n[Notify Long|Error] {line}\n")
                self.assertEqual(paths._slssteam_log_abort_cause(), cause)

    def test_soft_hash_warning_is_not_fatal(self):
        self.write("[Notify|Warn in src/main.cpp:load:189] steamclient.so hash missmatch! Please update :)\n")
        self.assertIsNone(paths._slssteam_log_abort_cause())

    def test_clean_log_is_not_fatal(self):
        self.write("[Info] steamclient.so loaded at 0x1 to 0x2\n[Info] Hooks placed\n")
        self.assertIsNone(paths._slssteam_log_abort_cause())

    def test_missing_log_is_unknown(self):
        self.assertIsNone(paths._slssteam_log_abort_cause())


class TestHealthMapping(_WithLog):
    """With the .so mapped, any fatal cause must surface as not_supported."""

    def _health(self):
        import dev
        with mock.patch.object(paths, "check_slssteam_installed", return_value=True), \
             mock.patch.object(paths, "verify_slssteam_injected",
                               return_value={"method": "active"}), \
             mock.patch.object(dev, "get", return_value=None):
            return paths.read_slssteam_health()

    def test_vftables_abort_is_not_supported_hooks(self):
        self.write(VFTABLES_LOG)
        h = self._health()
        self.assertEqual(h["state"], "not_supported")
        self.assertEqual(h["cause"], "hooks")

    def test_hash_abort_is_not_supported_version(self):
        self.write("[Notify Long|Error] Unknown steamclient.so hash! Aborting...\n")
        h = self._health()
        self.assertEqual(h["state"], "not_supported")
        self.assertEqual(h["cause"], "version")

    def test_clean_log_is_healthy(self):
        self.write("[Info] Hooks placed\n")
        self.assertEqual(self._health()["state"], "healthy")


if __name__ == "__main__":
    unittest.main()

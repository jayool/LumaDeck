"""The Dev tab's fake installer: install_via_setup runs backend/dev_fake_setup.sh
instead of downloading setup.sh, walks the same phases (the QAM row can be
watched without installing anything), reports success without checking any
file, and says it was fake."""
import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import dev  # noqa: E402
import installer  # noqa: E402


class FakeInstallerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_file = dev._FILE
        dev._FILE = os.path.join(self._tmp.name, "dev_overrides.json")
        os.environ["LUMADECK_FAKE_SETUP_FAST"] = "1"

    def tearDown(self):
        dev._FILE = self._old_file
        os.environ.pop("LUMADECK_FAKE_SETUP_FAST", None)
        self._tmp.cleanup()

    def test_off_by_default(self):
        self.assertFalse(installer.fake_installer_active())

    def test_fake_run_walks_every_phase_and_installs_nothing(self):
        with open(dev._FILE, "w", encoding="utf-8") as f:
            json.dump({"installer": "fake"}, f)
        self.assertTrue(installer.fake_installer_active())
        self.assertTrue(os.path.exists(installer.FAKE_SETUP_SCRIPT))
        seen = []
        orig = installer.note_output_line

        def spy(state, text):
            orig(state, text)
            if state.get("phase") and (not seen or seen[-1] != state["phase"]):
                seen.append(state["phase"])
        installer.note_output_line = spy
        try:
            result = asyncio.run(installer.install_via_setup())
        finally:
            installer.note_output_line = orig
        self.assertEqual(result, {"success": True, "fake": True})
        self.assertEqual(installer.get_setup_status()["status"], "done")
        self.assertEqual(installer.get_setup_status()["phase"], "done")
        self.assertEqual(seen, ["preparing", "slssteam", "cloudredirect", "cloudredirect_app",
                                "netsock", "lumalinux", "tools", "gamemode"])
        # a bar was seen inside a download phase at some point: percent went non-None
        # (the final state has it cleared by the "done" phase)
        self.assertIsNone(installer.get_setup_status()["percent"])


if __name__ == "__main__":
    unittest.main()

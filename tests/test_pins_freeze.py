"""pins.freeze_for_files — the freeze every file-writing operation applies
(a fix, Goldberg, Steamless, the EOS proxy), so a Steam update under the
native model cannot put Valve's files back:
    python -m unittest discover -s tests

Pins: an unfrozen game gets pinned and frozen with reason "files"; a game the
user froze is left alone (no re-pin, reason kept); a providers freeze (the one
the local pass would lift once a provider answers) is upgraded to the durable
"files" freeze; the "files" freeze counts as user-frozen for the local pass
and for the pin status; and the .exe-swap / fix / Goldberg / Online callers
route through it (main.py + steamless.py + fixes.py grep-pinned).
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pins  # noqa: E402

APP = 4242


class FreezeForFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = {}
        self.pinned = []

        def patch(name, value):
            self._orig[name] = getattr(pins, name)
            setattr(pins, name, value)

        async def fake_ensure_pinned(appid, allow_pin=True):
            self.pinned.append((appid, allow_pin))
            return {appid + 1: 1}

        patch("_STATE_PATH", os.path.join(self.tmp, "pins.json"))
        patch("ensure_pinned", fake_ensure_pinned)

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(pins, k, v)

    def test_unfrozen_game_gets_pinned_and_frozen(self):
        self.assertTrue(asyncio.run(pins.freeze_for_files(APP)))
        self.assertEqual(self.pinned, [(APP, True)])
        info = pins.frozen_info(APP)
        self.assertTrue(info["frozen"])
        self.assertEqual(info["reason"], pins.FREEZE_REASON_FILES)
        self.assertTrue(pins.user_frozen(APP))              # kept by the local pass
        self.assertFalse(pins.frozen_by_providers(APP))     # and by the pin status

    def test_user_freeze_is_left_alone(self):
        pins.set_frozen(APP, True, fix_id="fix-1", version={"buildid": "7"})
        self.assertFalse(asyncio.run(pins.freeze_for_files(APP)))
        self.assertEqual(self.pinned, [])
        info = pins.frozen_info(APP)
        self.assertIsNone(info["reason"])
        self.assertEqual(info["fix_id"], "fix-1")           # a version fix's freeze survives

    def test_providers_freeze_is_upgraded_to_durable(self):
        pins.set_frozen(APP, True, reason=pins.FREEZE_REASON_PROVIDERS)
        self.assertTrue(asyncio.run(pins.freeze_for_files(APP)))
        self.assertEqual(pins.frozen_info(APP)["reason"], pins.FREEZE_REASON_FILES)
        self.assertFalse(pins.frozen_by_providers(APP))     # the local pass will not lift it

    def test_second_call_is_a_no_op(self):
        asyncio.run(pins.freeze_for_files(APP))
        self.assertFalse(asyncio.run(pins.freeze_for_files(APP)))
        self.assertEqual(len(self.pinned), 1)


class CallersRouteThroughIt(unittest.TestCase):
    """The four writers freeze through pins.freeze_for_files — cheap source
    pins so a refactor cannot silently drop one."""
    ROOT = os.path.join(os.path.dirname(__file__), "..")

    def _src(self, rel):
        with open(os.path.join(self.ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_fix_extraction_freezes(self):
        s = self._src("backend/fixes.py")
        self.assertIn("await pins.freeze_for_files(appid)", s)

    def test_steamless_freezes_after_a_swap(self):
        s = self._src("backend/steamless.py")
        self.assertIn("async def run_steamless(install_path: str, appid: int = 0)", s)
        self.assertIn("if success_count and appid:", s)
        self.assertIn("await pins.freeze_for_files(int(appid))", s)

    def test_goldberg_and_online_freeze_in_main(self):
        s = self._src("main.py")
        self.assertEqual(s.count("await _freeze_for_files(appid)"), 2)
        # Online: only when the EOS proxy (the one file-level door) was applied.
        self.assertIn('(res.get("applied") or {}).get("eos")', s)


if __name__ == "__main__":
    unittest.main()

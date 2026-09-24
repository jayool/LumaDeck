"""backend/eos_proxy.py — the EOS proxy leg of the Online toggle, on real files
in a temp dir. The bundled proxy is stubbed with a small fake binary, so this
runs without the release fetch:
    python -m unittest discover -s tests

Pins: detection (depth limit 6, pruned dirs), the four states, apply on a
pristine game (rename + copy + hash check), apply on a stale location (a game
update replaced the proxy: the NEW SDK becomes the .yes), idempotent re-apply,
remove restores the SDK, remove on a game with no proxy is a no-op, and the
proxy-missing failure.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import eos_proxy  # noqa: E402

PROXY_BYTES = b"MZ-proxy-" + b"P" * 300
SDK_V1 = b"MZ-sdk-v1-" + b"1" * 500
SDK_V2 = b"MZ-sdk-v2-" + b"2" * 500


def _w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _r(path):
    with open(path, "rb") as f:
        return f.read()


class EosProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(self.game)
        self.proxy = os.path.join(self.tmp, "deps", "EosProxy", eos_proxy.EOS_DLL)
        _w(self.proxy, PROXY_BYTES)
        self._saved = eos_proxy.bundled_proxy_path
        eos_proxy.bundled_proxy_path = lambda: self.proxy if os.path.isfile(self.proxy) else None
        self.addCleanup(lambda: setattr(eos_proxy, "bundled_proxy_path", self._saved))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def sdk(self, rel="Engine/Binaries/ThirdParty/EOSSDK/Win64"):
        d = os.path.join(self.game, *rel.split("/")) if rel else self.game
        return d, os.path.join(d, eos_proxy.EOS_DLL), os.path.join(d, eos_proxy.EOS_BACKUP)

    # ---- detection ---------------------------------------------------------
    def test_no_sdk_is_none(self):
        _w(os.path.join(self.game, "Game.exe"), b"x")
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "none")
        self.assertEqual(eos_proxy.find_eos_dirs(self.game), [])

    def test_finds_sdk_up_to_depth_6_and_prunes_backups(self):
        d, dll, _ = self.sdk()                                   # depth 5: Unreal's real layout
        _w(dll, SDK_V1)
        deep = os.path.join(self.game, "a", "b", "c", "d", "e", "f", "g", eos_proxy.EOS_DLL)   # depth 7
        _w(deep, SDK_V1)
        bak = os.path.join(self.game, "luatools-backup-123", eos_proxy.EOS_DLL)      # a fix backup
        _w(bak, SDK_V1)
        self.assertEqual(eos_proxy.find_eos_dirs(self.game), [d])

    # ---- apply on a pristine game -------------------------------------------
    def test_apply_renames_sdk_and_installs_proxy(self):
        d, dll, yes = self.sdk()
        _w(dll, SDK_V1)
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "inactive")
        r = eos_proxy.apply_eos_proxy(self.game)
        self.assertTrue(r["success"], r)
        self.assertEqual(r["applied"], 1)
        self.assertEqual(_r(dll), PROXY_BYTES)
        self.assertEqual(_r(yes), SDK_V1)
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "active")

    def test_apply_is_idempotent(self):
        d, dll, yes = self.sdk()
        _w(dll, SDK_V1)
        eos_proxy.apply_eos_proxy(self.game)
        r = eos_proxy.apply_eos_proxy(self.game)
        self.assertTrue(r["success"])
        self.assertEqual(r["applied"], 0)                       # already active, untouched
        self.assertEqual(_r(yes), SDK_V1)                       # pristine SDK preserved

    def test_apply_covers_every_location(self):
        for rel in ("Engine/Binaries/ThirdParty/EOSSDK/Win64", "Game/Binaries/Win64"):
            _w(self.sdk(rel)[1], SDK_V1)
        r = eos_proxy.apply_eos_proxy(self.game)
        self.assertEqual(r["applied"], 2)
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "active")

    # ---- stale: a game update overwrote the proxy with a new SDK -------------
    def test_stale_after_game_update_keeps_the_new_sdk(self):
        d, dll, yes = self.sdk()
        _w(dll, SDK_V1)
        eos_proxy.apply_eos_proxy(self.game)
        _w(dll, SDK_V2)                                         # Steam update: real SDK v2 in place
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "stale")
        r = eos_proxy.apply_eos_proxy(self.game)
        self.assertTrue(r["success"])
        self.assertEqual(_r(dll), PROXY_BYTES)
        self.assertEqual(_r(yes), SDK_V2)                       # the proxy forwards to the SDK the game expects now
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "active")

    def test_stale_with_dll_missing_reinstalls_proxy_over_kept_yes(self):
        d, dll, yes = self.sdk()
        _w(dll, SDK_V1)
        eos_proxy.apply_eos_proxy(self.game)
        os.remove(dll)                                          # someone deleted the proxy by hand
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "stale")
        r = eos_proxy.apply_eos_proxy(self.game)
        self.assertTrue(r["success"])
        self.assertEqual(_r(dll), PROXY_BYTES)
        self.assertEqual(_r(yes), SDK_V1)

    # ---- remove ------------------------------------------------------------
    def test_remove_restores_sdk(self):
        d, dll, yes = self.sdk()
        _w(dll, SDK_V1)
        eos_proxy.apply_eos_proxy(self.game)
        r = eos_proxy.remove_eos_proxy(self.game)
        self.assertTrue(r["success"])
        self.assertEqual(r["removed"], 1)
        self.assertEqual(_r(dll), SDK_V1)
        self.assertFalse(os.path.exists(yes))
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "inactive")

    def test_remove_without_proxy_is_a_no_op(self):
        d, dll, yes = self.sdk()
        _w(dll, SDK_V1)
        r = eos_proxy.remove_eos_proxy(self.game)
        self.assertTrue(r["success"])
        self.assertEqual(r["removed"], 0)
        self.assertEqual(_r(dll), SDK_V1)

    # ---- failures ----------------------------------------------------------
    def test_apply_without_sdk_fails_cleanly(self):
        r = eos_proxy.apply_eos_proxy(self.game)
        self.assertFalse(r["success"])
        self.assertIn("EOS SDK", r["error"])

    def test_apply_without_bundled_proxy_fails_cleanly(self):
        d, dll, yes = self.sdk()
        _w(dll, SDK_V1)
        os.remove(self.proxy)
        r = eos_proxy.apply_eos_proxy(self.game)
        self.assertFalse(r["success"])
        self.assertIn("not bundled", r["error"])
        self.assertEqual(_r(dll), SDK_V1)                       # nothing touched
        self.assertFalse(eos_proxy.get_eos_proxy_status(self.game)["bundled"])

    def test_missing_game_dir(self):
        self.assertFalse(eos_proxy.apply_eos_proxy(os.path.join(self.tmp, "nope"))["success"])
        self.assertEqual(eos_proxy.get_eos_proxy_status("")["status"], "none")


if __name__ == "__main__":
    unittest.main()

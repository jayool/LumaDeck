"""The Online toggle (backend/fixes.py enable_online / disable_online /
get_online_status) and slssteam_ops.is_in_denuvo_games, with SLSsteam's config
ops and the EOS proxy stubbed, on a real game dir in a temp folder:
    python -m unittest discover -s tests

Pins: the three doors applied by detection (480 always, netsock when the .so
is there, EOS only when the game ships the SDK); the DenuvoGames refusal; the
"netsock not installed" skip; the marker; disable removes the proxy and the
480 only when the toggle added it AND no surviving fix declares one; the
online-fix automatism's legacy netsock marker still counts for the LD_AUDIT;
status fields; and the DenuvoGames parser on block/flow/absent config.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import eos_proxy  # noqa: E402
import fixes  # noqa: E402
import slssteam_ops  # noqa: E402


class _SlsStub:
    """In-memory FakeAppIds map + DenuvoGames membership."""
    def __init__(self):
        self.fake = {}
        self.denuvo = set()

    def add_fake_app_id(self, appid, fake_id=480):
        self.fake[int(appid)] = fake_id
        return {"success": True}

    def remove_fake_app_id(self, appid):
        self.fake.pop(int(appid), None)
        return {"success": True}

    def check_fake_app_id_status(self, appid):
        return {"success": True, "exists": int(appid) in self.fake}

    def is_in_denuvo_games(self, appid):
        return int(appid) in self.denuvo


class OnlineToggleTests(unittest.TestCase):
    APPID = 892970

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "Valheim")
        os.makedirs(self.game)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

        # SLSsteam config ops → in-memory stub (the functions are imported lazily
        # inside fixes.*, so patching the module attributes is what takes effect).
        self.sls = _SlsStub()
        self._saved = []
        for name in ("add_fake_app_id", "remove_fake_app_id", "check_fake_app_id_status", "is_in_denuvo_games"):
            self._saved.append((slssteam_ops, name, getattr(slssteam_ops, name)))
            setattr(slssteam_ops, name, getattr(self.sls, name))
        # EOS proxy → a fake bundled binary in the temp dir (real file mechanics).
        self.proxy = os.path.join(self.tmp, "deps", "EosProxy", eos_proxy.EOS_DLL)
        os.makedirs(os.path.dirname(self.proxy))
        with open(self.proxy, "wb") as f:
            f.write(b"MZ-proxy" + b"P" * 200)
        self._saved.append((eos_proxy, "bundled_proxy_path", eos_proxy.bundled_proxy_path))
        eos_proxy.bundled_proxy_path = lambda: self.proxy
        # netsock.so present by default.
        self.netsock = True
        self._saved.append((fixes, "_netsock_so_installed", fixes._netsock_so_installed))
        fixes._netsock_so_installed = lambda: self.netsock
        self.addCleanup(self._restore)

    def _restore(self):
        for mod, name, old in reversed(self._saved):
            setattr(mod, name, old)

    def _sdk(self):
        d = os.path.join(self.game, "Engine", "Binaries", "ThirdParty", "EOSSDK", "Win64")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, eos_proxy.EOS_DLL), "wb") as f:
            f.write(b"MZ-sdk" + b"S" * 300)
        return d

    def _fix_log(self, blocks):
        with open(os.path.join(self.game, f"luatools-fix-log-{self.APPID}.log"), "w", encoding="utf-8") as f:
            f.write("\n---\n".join(blocks))

    ONLINE_FIX_BLOCK = ("[FIX]\nDate: 2026-09-20 10:00:00\nGame: Valheim\nFix Type: OnlineFix\n"
                        "Download URL: x\nFakeAppId: 480\nOnline: yes\nFiles:\nOnlineFix64.dll\n[/FIX]")
    CRACK_BLOCK = ("[FIX]\nDate: 2026-09-18 10:00:00\nGame: Valheim\nFix Type: Crack\n"
                   "Download URL: y\nFiles:\nGame.exe\n[/FIX]")

    # ---- enable: the three doors by detection ------------------------------
    def test_enable_applies_480_and_netsock_no_eos_without_sdk(self):
        r = fixes.enable_online(self.APPID, self.game)
        self.assertTrue(r["success"], r)
        self.assertEqual(r["applied"], {"fakeAppId": True, "netsock": True, "eos": False})
        self.assertEqual(r["skipped"], {"eos": "no EOS SDK"})
        self.assertIn(self.APPID, self.sls.fake)
        m = json.load(open(fixes._online_marker_path(self.game, self.APPID)))
        self.assertEqual(m, {"netsock": True, "eos": False, "fakeAppId": True})
        self.assertTrue(fixes._netsock_enabled(self.game, self.APPID))
        self.assertTrue(fixes._netsock_ld_audit_value(self.game, self.APPID))

    def test_enable_applies_eos_when_the_game_ships_the_sdk(self):
        d = self._sdk()
        r = fixes.enable_online(self.APPID, self.game)
        self.assertEqual(r["applied"], {"fakeAppId": True, "netsock": True, "eos": True})
        self.assertEqual(r["skipped"], {})
        self.assertTrue(os.path.isfile(os.path.join(d, eos_proxy.EOS_BACKUP)))
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "active")

    def test_enable_skips_netsock_when_not_installed(self):
        self.netsock = False
        r = fixes.enable_online(self.APPID, self.game)
        self.assertTrue(r["success"])
        self.assertFalse(r["applied"]["netsock"])
        self.assertEqual(r["skipped"]["netsock"], "netsock not installed")
        self.assertFalse(fixes._netsock_enabled(self.game, self.APPID))
        self.assertTrue(r["applied"]["fakeAppId"])                # the rest still applies

    def test_enable_refuses_a_denuvo_activated_game(self):
        self.sls.denuvo.add(self.APPID)
        r = fixes.enable_online(self.APPID, self.game)
        self.assertFalse(r["success"])
        self.assertEqual(r["blockedBy"], "denuvo")
        self.assertNotIn(self.APPID, self.sls.fake)               # nothing touched
        self.assertIsNone(fixes._read_online_marker(self.game, self.APPID))

    def test_enable_is_idempotent(self):
        self._sdk()
        fixes.enable_online(self.APPID, self.game)
        r = fixes.enable_online(self.APPID, self.game)
        self.assertTrue(r["success"])
        self.assertTrue(fixes._read_online_marker(self.game, self.APPID)["fakeAppId"])  # still ours

    # ---- disable: exactly what enable added ---------------------------------
    def test_disable_removes_marker_proxy_and_our_480(self):
        d = self._sdk()
        fixes.enable_online(self.APPID, self.game)
        r = fixes.disable_online(self.APPID, self.game)
        self.assertTrue(r["success"])
        self.assertEqual(r["removed"], {"eos": True, "fakeAppId": True})
        self.assertIsNone(fixes._read_online_marker(self.game, self.APPID))
        self.assertNotIn(self.APPID, self.sls.fake)
        self.assertFalse(os.path.exists(os.path.join(d, eos_proxy.EOS_BACKUP)))
        self.assertEqual(eos_proxy.get_eos_proxy_status(self.game)["status"], "inactive")
        self.assertFalse(fixes._netsock_enabled(self.game, self.APPID))

    def test_disable_keeps_a_480_the_toggle_did_not_add(self):
        self.sls.add_fake_app_id(self.APPID)                      # set by a fix or by hand before
        fixes.enable_online(self.APPID, self.game)
        self.assertFalse(fixes._read_online_marker(self.game, self.APPID)["fakeAppId"])
        r = fixes.disable_online(self.APPID, self.game)
        self.assertFalse(r["removed"]["fakeAppId"])
        self.assertIn(self.APPID, self.sls.fake)

    def test_disable_keeps_the_480_while_an_online_fix_declares_it(self):
        fixes.enable_online(self.APPID, self.game)                # toggle added the 480
        self._fix_log([self.ONLINE_FIX_BLOCK])                    # then an online fix landed
        r = fixes.disable_online(self.APPID, self.game)
        self.assertFalse(r["removed"]["fakeAppId"])
        self.assertIn(self.APPID, self.sls.fake)

    def test_disable_when_off_is_a_no_op(self):
        r = fixes.disable_online(self.APPID, self.game)
        self.assertTrue(r["success"])
        self.assertEqual(r["removed"], {"eos": False, "fakeAppId": False})

    # ---- the online-fix automatism's legacy marker is independent -----------
    def test_legacy_netsock_marker_still_counts_and_survives_disable(self):
        open(fixes._netsock_marker_path(self.game, self.APPID), "w").write("netsock enabled\n")
        self.assertTrue(fixes._netsock_enabled(self.game, self.APPID))
        st = fixes.get_online_status(self.APPID, self.game)
        self.assertFalse(st["enabled"])                           # the toggle itself is off
        fixes.enable_online(self.APPID, self.game)
        fixes.disable_online(self.APPID, self.game)
        self.assertTrue(os.path.isfile(fixes._netsock_marker_path(self.game, self.APPID)))
        self.assertTrue(fixes._netsock_enabled(self.game, self.APPID))

    # ---- status ------------------------------------------------------------
    def test_status_fields(self):
        self._sdk()
        st = fixes.get_online_status(self.APPID, self.game)
        self.assertEqual(st, {"success": True, "enabled": False,
                              "applied": {"netsock": False, "eos": False, "fakeAppId": False},
                              "netsockInstalled": True, "eosStatus": "inactive", "eosBundled": True,
                              "blockedBy": None, "hasOnlineFix": False})
        self._fix_log([self.CRACK_BLOCK, self.ONLINE_FIX_BLOCK])
        self.sls.denuvo.add(self.APPID)
        fixes.enable_online(self.APPID, self.game)                # refused
        st = fixes.get_online_status(self.APPID, self.game)
        self.assertEqual(st["blockedBy"], "denuvo")
        self.assertTrue(st["hasOnlineFix"])
        self.assertFalse(st["enabled"])

    def test_has_online_fix_ignores_plain_cracks(self):
        self._fix_log([self.CRACK_BLOCK])
        self.assertFalse(fixes._has_online_fix(self.APPID, self.game))
        self.assertFalse(fixes._fix_declares_fakeappid(self.APPID, self.game))

    def test_invalid_inputs(self):
        self.assertFalse(fixes.enable_online("x", self.game)["success"])
        self.assertFalse(fixes.enable_online(self.APPID, os.path.join(self.tmp, "nope"))["success"])


class DenuvoGamesParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "config.yaml")
        self._saved = slssteam_ops._config_path
        slssteam_ops._config_path = lambda: self.cfg
        self.addCleanup(lambda: setattr(slssteam_ops, "_config_path", self._saved))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _write(self, text):
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(text)

    def test_absent_config_or_block(self):
        self.assertFalse(slssteam_ops.is_in_denuvo_games(1234))
        self._write("AdditionalApps:\n  - 1234\nFakeAppIds:\n  1234: 480\n")
        self.assertFalse(slssteam_ops.is_in_denuvo_games(1234))

    def test_block_style(self):
        self._write("#Example of DenuvoGames:\n#DenuvoGames:\n#  SteamId:\n#    -  AppId1\n"
                    "DenuvoGames:\n  76561198000000001:\n    - 1234\n    -  5678\n  76561198000000002:\n    - 999\n"
                    "AdditionalApps:\n  - 1234\n")
        for a in (1234, 5678, 999):
            self.assertTrue(slssteam_ops.is_in_denuvo_games(a), a)
        self.assertFalse(slssteam_ops.is_in_denuvo_games(12345))
        self.assertFalse(slssteam_ops.is_in_denuvo_games(76561198000000001))   # the SteamId is not an appid

    def test_flow_style_and_comments(self):
        self._write("DenuvoGames:\n  # my activator\n  76561198000000001: [1234, 5678]\nFakeAppIds:\n  999: 480\n")
        self.assertTrue(slssteam_ops.is_in_denuvo_games(5678))
        self.assertFalse(slssteam_ops.is_in_denuvo_games(999))          # lives in another block

    def test_empty_block(self):
        self._write("DenuvoGames:\nAdditionalApps:\n  - 1234\n")
        self.assertFalse(slssteam_ops.is_in_denuvo_games(1234))


if __name__ == "__main__":
    unittest.main()

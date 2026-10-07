"""Uninstalling an OWNED game (lumalinux docs/owned-games-guide.md, flow D).

slssteam_ops.owned_dlc_to_disable and uninstall_game_full on a sandboxed
Steam root, with SLSsteam/keys helpers stubbed and their call order recorded:
Steam removes the DLC itself once the frontend unticks them, so the backend
refuses without that confirmation, never touches the game's folder, .acf,
depotcache or config.vdf, removes LumaDeck's record, and the .lua last.

    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths  # noqa: E402
import pins  # noqa: E402
import slssteam_ops  # noqa: E402
import steam_licenses  # noqa: E402
import steam_utils  # noqa: E402

APP, DLC_A, DLC_B = 262060, 580100, 702540
KEY = "ab" * 32
LUA = f"""addappid({APP})
addappid({DLC_A})
addappid(580102,1,"{KEY}")
setManifestid(580102,"4506000746151544241",100)
addappid({DLC_B})
addappid(702542,1,"{KEY}")
setManifestid(702542,"4258374143576351227",200)
"""


class OwnedUninstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "Steam")
        self.stplug = os.path.join(self.root, "config", "stplug-in")
        self.depotcache = os.path.join(self.root, "depotcache")
        self.game = os.path.join(self.root, "steamapps", "common", "DarkestDungeon")
        self.shaders = os.path.join(self.root, "steamapps", "shadercache", str(APP))
        for d in (self.stplug, self.depotcache, os.path.join(self.game, ".DepotDownloader"), self.shaders):
            os.makedirs(d)
        self.lua = os.path.join(self.stplug, f"{APP}.lua")
        with open(self.lua, "w") as fh:
            fh.write(LUA)
        self.manifest = os.path.join(self.depotcache, "580102_4506000746151544241.manifest")
        open(self.manifest, "wb").write(b"\0" * 8)
        self.acf = os.path.join(self.root, "steamapps", f"appmanifest_{APP}.acf")
        open(self.acf, "w").write('"AppState"\n{\n}\n')
        open(os.path.join(self.game, "game.bin"), "wb").write(b"x")
        self.calls = []
        self.licensed = {APP}
        self.running = False
        self.installed = True
        self._orig = []

        def patch(mod, name, value):
            self._orig.append((mod, name, getattr(mod, name)))
            setattr(mod, name, value)

        patch(pins, "_STATE_PATH", os.path.join(self.tmp, "pins.json"))
        patch(pins, "find_acf", lambda appid: self.acf if self.installed else None)
        patch(steam_utils, "detect_steam_install_path", lambda: self.root)
        patch(steam_utils, "get_steam_libraries", lambda: [{"path": self.root}])
        patch(steam_utils, "is_app_running", lambda appid: self.running)
        patch(steam_licenses, "is_licensed", lambda appid: int(appid) in self.licensed)
        patch(slssteam_ops, "get_game_install_path_response",
              lambda appid: {"success": True, "installPath": self.game, "libraryPath": self.root})
        patch(slssteam_ops, "_find_game_dir_fallback", lambda appid: "")
        patch(slssteam_ops, "_remove_from_additional_apps", lambda appid: self.calls.append(("sls", int(appid))))
        for name in ("remove_fake_app_id", "remove_game_token", "remove_game_dlcs"):
            patch(slssteam_ops, name, (lambda n: (lambda appid: self.calls.append((n, int(appid)))))(name))
        patch(slssteam_ops, "remove_from_lumalinux_keys",
              lambda appid, extra_depot_ids=None, retire=False: (self.calls.append(("keys", int(appid), retire)) or {"removed": 2, "depot_ids": ["580102", "702542"], "retired": 2 if retire else 0}))
        patch(slssteam_ops, "remove_depot_decryption_keys",
              lambda ids: self.fail("config.vdf must not be edited on uninstall"))
        real_delete = slssteam_ops.delete_luatools_for_app

        def delete_lua(appid):
            self.calls.append(("lua", int(appid)))
            for p in (self.lua, self.lua + ".disabled"):
                if os.path.exists(p):
                    os.remove(p)
            return {"success": True}
        patch(slssteam_ops, "delete_luatools_for_app", delete_lua)
        pins.set_owned(APP, True)

    def tearDown(self):
        for mod, name, value in reversed(self._orig):
            setattr(mod, name, value)

    def test_prep_lists_our_dlc_but_not_a_bought_one(self):
        self.licensed = {APP, DLC_B}
        prep = slssteam_ops.owned_dlc_to_disable(APP)
        self.assertEqual(prep, {"success": True, "owned": True, "installed": True, "running": False, "dlc": [DLC_A]})

    def test_prep_for_a_game_that_is_not_owned(self):
        pins.set_owned(APP, False)
        self.assertEqual(slssteam_ops.owned_dlc_to_disable(APP)["dlc"], [])
        self.assertFalse(slssteam_ops.owned_dlc_to_disable(APP)["owned"])

    def test_refused_until_steam_dropped_the_dlc(self):
        res = slssteam_ops.uninstall_game_full(APP)
        self.assertFalse(res["success"])
        self.assertTrue(os.path.exists(self.lua), "nothing touched")
        self.assertEqual(self.calls, [])
        self.assertTrue(pins.is_owned(APP))

    def test_refused_while_the_game_runs(self):
        self.running = True
        res = slssteam_ops.uninstall_game_full(APP, steam_dlc_disabled=True)
        self.assertFalse(res["success"])
        self.assertEqual(self.calls, [])

    def test_owned_uninstall_removes_only_our_record(self):
        res = slssteam_ops.uninstall_game_full(APP, steam_dlc_disabled=True)
        self.assertTrue(res["success"], res)
        # Steam's: untouched
        self.assertTrue(os.path.exists(os.path.join(self.game, "game.bin")))
        self.assertTrue(os.path.exists(self.acf))
        self.assertTrue(os.path.exists(self.manifest), "depotcache is Steam's: it needs the manifest to delete the DLC files")
        self.assertTrue(os.path.isdir(self.shaders), "shader cache is Steam's for an owned game")
        self.assertNotIn("game_files", res["removed"])
        self.assertNotIn("appmanifest", res["removed"])
        self.assertNotIn("depot_manifests", res["removed"])
        self.assertNotIn("decryption_keys", res["removed"])
        # ours: gone, the .lua last
        self.assertFalse(os.path.exists(self.lua))
        self.assertFalse(os.path.isdir(os.path.join(self.game, ".DepotDownloader")))
        self.assertIn(("sls", DLC_A), self.calls)
        self.assertIn(("sls", DLC_B), self.calls)
        self.assertIn(("keys", APP, True), self.calls, "owned: keys are retired, not dropped")
        self.assertIn("lumalinux_keys_retired", res["removed"])
        self.assertEqual(self.calls[-1], ("lua", APP))
        self.assertFalse(pins.is_owned(APP))

    def test_added_game_uninstall_drops_the_shader_cache(self):
        # The flow-E uninstall (lumalinux docs/owned-games-guide.md): Steam's
        # own uninstall removes steamapps/shadercache/<appid>, so do we.
        pins.set_owned(APP, False)
        res = slssteam_ops.uninstall_game_full(APP)
        self.assertTrue(res["success"], res)
        self.assertFalse(os.path.exists(self.shaders))
        self.assertIn("shadercache", res["removed"])
        self.assertFalse(os.path.exists(self.game))

    def test_not_installed_needs_no_confirmation(self):
        self.installed = False
        res = slssteam_ops.uninstall_game_full(APP)
        self.assertTrue(res["success"], res)
        self.assertFalse(os.path.exists(self.lua))


class RetiredKeys(unittest.TestCase):
    """remove_from_lumalinux_keys(retire=True) and prune_retired_keys on real
    files: the DLC's keyed lines move to retired_keys.txt (the app's own line
    and presence-only lines do not), a second retirement replaces the entry,
    and a re-add that puts the depot back in keys.txt prunes it."""
    KEYS = (f"{APP};\n"
            f"580102;{APP};0;0;{KEY}\n"
            f"702542;{APP};0;0;{'cd' * 32}\n"
            f"1942280;\n"
            f"1942281;1942280;0;0;{'ef' * 32}\n")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.keys = os.path.join(self.tmp, "keys.txt")
        self.retired = os.path.join(self.tmp, "retired_keys.txt")
        open(self.keys, "w").write(self.KEYS)
        self._orig = (paths.get_lumalinux_keys_path, paths.get_lumalinux_retired_keys_path)
        paths.get_lumalinux_keys_path = lambda: self.keys
        paths.get_lumalinux_retired_keys_path = lambda: self.retired

    def tearDown(self):
        paths.get_lumalinux_keys_path, paths.get_lumalinux_retired_keys_path = self._orig

    def test_retire_moves_the_keyed_lines(self):
        res = slssteam_ops.remove_from_lumalinux_keys(APP, retire=True)
        self.assertEqual((res["removed"], res["retired"]), (3, 2))
        keys = open(self.keys).read()
        self.assertNotIn("580102;", keys)
        self.assertIn("1942281;1942280;", keys, "the other game's lines stay")
        retired = open(self.retired).read().splitlines()
        self.assertEqual(sorted(l.split(";")[0] for l in retired), ["580102", "702542"])
        self.assertTrue(all(len(l.split(";")[4]) == 64 for l in retired))

    def test_plain_removal_retires_nothing(self):
        res = slssteam_ops.remove_from_lumalinux_keys(APP)
        self.assertEqual(res["retired"], 0)
        self.assertFalse(os.path.exists(self.retired))

    def test_second_retirement_replaces_and_readd_prunes(self):
        slssteam_ops.remove_from_lumalinux_keys(APP, retire=True)
        # the game is added again: steamidra rewrites keys.txt with the depots
        open(self.keys, "w").write(self.KEYS)
        self.assertEqual(slssteam_ops.prune_retired_keys(), 2)
        self.assertEqual(open(self.retired).read().strip(), "")
        # retire again with a new key for one depot: one entry per depot
        open(self.keys, "w").write(self.KEYS.replace(KEY, "12" * 32))
        slssteam_ops.remove_from_lumalinux_keys(APP, retire=True)
        open(self.keys, "w").write(f"580102;{APP};0;0;{KEY}\n")
        slssteam_ops.remove_from_lumalinux_keys(APP, retire=True)
        retired = [l for l in open(self.retired).read().splitlines() if l.strip()]
        self.assertEqual(len(retired), 2)
        self.assertEqual([l for l in retired if l.startswith("580102;")][0].split(";")[4], KEY)


if __name__ == "__main__":
    unittest.main()

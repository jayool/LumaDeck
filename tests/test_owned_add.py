"""Adding DLC to a game the account OWNS (RESEARCH §21 run E; the flows in
lumalinux docs/owned-games-guide.md).

Pure pieces, no Steam: the .lua filter that keeps only the DLC depots, the
`owned` flag in pins.json that uninstall and the game page read, the
three-way DLC-depot map and the owned plan (what gets added).

    python -m unittest discover -s tests
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import downloads  # noqa: E402
import pins  # noqa: E402

APP = 262060
KEY = "ab" * 32
LUA = f"""-- Darkest Dungeon
addappid({APP})
addappid(262065,1,"{KEY}")
setManifestid(262065,"111",10)
addappid(702540)
addappid(702541,1,"{KEY}")
--setManifestid(702541,"222",20)
addappid(702542,1,"{KEY}")
setManifestid(702542,"4258374143576351227",40024569)
addtoken({APP},"deadbeef")
-- SHARED DEPOTS
addappid(228989,1,"{KEY}")
"""


class OwnedLuaFilter(unittest.TestCase):
    def test_keeps_dlc_depots_drops_base_and_shared(self):
        text, dropped = downloads._filter_lua_for_owned_base(LUA, APP, {702541, 702542})
        self.assertEqual(sorted(dropped), [228989, 262065])
        self.assertIn(f"addappid({APP})\n", text)              # base AppID line (keyless) stays
        self.assertIn("addappid(702540)\n", text)              # DLC AppID line stays
        self.assertIn('addappid(702541,1,', text)
        self.assertIn('--setManifestid(702541,"222",20)', text)  # commented pin of a DLC depot stays
        self.assertIn('setManifestid(702542,', text)
        self.assertNotIn("262065", text)                       # base depot: key AND pin gone
        self.assertNotIn("228989", text)                       # shared redist gone
        self.assertIn('addtoken(262060,"deadbeef")', text)     # untouched
        self.assertIn("-- SHARED DEPOTS", text)

    def test_no_dlc_depots_drops_everything_keyed(self):
        text, dropped = downloads._filter_lua_for_owned_base(LUA, APP, set())
        self.assertEqual(sorted(dropped), [228989, 262065, 702541, 702542])
        self.assertNotIn(",1,", text)

    def test_base_line_is_added_when_the_lua_only_had_the_keyed_one(self):
        # Hubcap shape: the base game appears only as addappid(APP,1,"key") (its
        # Windows depot), followed by the DLC. Dropping it must not promote the
        # first DLC to "the game".
        lua = f'addappid({APP},1,"{KEY}")\naddappid(580100)\naddappid(580101,1,"{KEY}")\n'
        text, dropped = downloads._filter_lua_for_owned_base(lua, APP, {580101})
        self.assertTrue(text.startswith(f"addappid({APP})\n"), text)
        self.assertEqual(dropped, [APP])
        self.assertEqual(text.count(f"addappid({APP})"), 1)

    def test_owned_dlc_appid_line_is_dropped_base_line_kept(self):
        text, _ = downloads._filter_lua_for_owned_base(LUA, APP, {702541, 702542}, owned_apps={702540, APP})
        self.assertNotIn("addappid(702540)\n", text)   # the account has this DLC: no AdditionalApps entry
        self.assertIn(f"addappid({APP})\n", text)       # the base AppID line always stays


class OwnedFlag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = pins._STATE_PATH
        pins._STATE_PATH = os.path.join(self.tmp, "pins.json")

    def tearDown(self):
        pins._STATE_PATH = self._orig

    def test_set_and_clear(self):
        self.assertFalse(pins.is_owned(APP))
        pins.set_owned(APP, True)
        self.assertTrue(pins.is_owned(APP))
        pins.set_frozen(APP, True, reason="user")          # other fields do not disturb it
        self.assertTrue(pins.is_owned(APP))
        pins.set_owned(APP, False)
        self.assertFalse(pins.is_owned(APP))
        self.assertTrue(pins.is_frozen(APP))


if __name__ == "__main__":
    unittest.main()


class ResolveOwned(unittest.TestCase):
    """downloads.resolve_owned: the one decision for the add shape."""
    def test_recorded_wins(self):
        self.assertTrue(downloads.resolve_owned(licensed=False, managed=True, listed_in_sls=True, recorded=True))

    def test_managed_or_listed_is_never_owned(self):
        # a licence that arrives AFTER the add is a migration, not an owned add
        self.assertFalse(downloads.resolve_owned(licensed=True, managed=True, listed_in_sls=False, recorded=False))
        self.assertFalse(downloads.resolve_owned(licensed=True, managed=False, listed_in_sls=True, recorded=False))

    def test_fresh_game_follows_the_package_cache(self):
        self.assertTrue(downloads.resolve_owned(licensed=True, managed=False, listed_in_sls=False, recorded=False))
        self.assertFalse(downloads.resolve_owned(licensed=False, managed=False, listed_in_sls=False, recorded=False))


class DlcDepotMap(unittest.TestCase):
    """downloads._dlc_depots_of: None (unknown) vs {} (no DLC depots) vs map."""
    def setUp(self):
        import manifests
        self._orig = manifests.steamcmd_app_info

    def tearDown(self):
        import manifests
        manifests.steamcmd_app_info = self._orig

    def _with(self, answer):
        import manifests
        async def stub(appid):
            if isinstance(answer, Exception):
                raise answer
            return answer
        manifests.steamcmd_app_info = stub
        return asyncio.run(downloads._dlc_depots_of(APP))

    def test_failure_is_unknown(self):
        self.assertIsNone(self._with(RuntimeError("down")))
        self.assertIsNone(self._with(None))
        self.assertIsNone(self._with({"buildid": 1, "depots": {}}))

    def test_depots_without_dlc_is_empty_map(self):
        self.assertEqual(self._with({"depots": {262065: {"gid": 1}, 262066: {"gid": 2}}}), {})

    def test_dlc_depots(self):
        info = {"depots": {262065: {"gid": 1}, 580102: {"gid": 3, "dlcappid": 580100},
                           "702542": {"gid": 4, "dlcappid": "702540"}}}
        self.assertEqual(self._with(info), {580102: 580100, 702542: 702540})


class OwnedPlan(unittest.TestCase):
    """downloads._owned_plan over the zip's .lua and Steam's own data."""
    MAP = {580102: 580100, 580101: 580100, 702542: 702540, 445702: 445700}
    LUA = f"addappid({APP})\naddappid(580100)\naddappid(702540)\naddappid(445700)\naddappid(999001)\n" \
          f"addappid(580102,1,\"{KEY}\")\naddappid(262065,1,\"{KEY}\")\n"

    def test_depot_dlc_not_owned(self):
        plan = downloads._owned_plan(self.LUA, APP, self.MAP, licensed={APP, 445700})
        self.assertEqual(plan["owned_dlc"], {445700})
        self.assertEqual(plan["dlc_depots"], {580102, 580101, 702542})
        self.assertEqual(plan["flag_dlcs"], {999001})
        self.assertEqual(plan["add_dlcs"], [580100, 702540, 999001])

    def test_flag_only_game_is_still_an_add(self):
        # no DLC depot at all (map {}): every keyed line is the base game's,
        # the flag DLC are what gets registered
        plan = downloads._owned_plan(self.LUA, APP, {}, licensed={APP})
        self.assertEqual(plan["dlc_depots"], set())
        self.assertEqual(plan["add_dlcs"], [445700, 580100, 702540, 999001])
        filtered, dropped = downloads._filter_lua_for_owned_base(self.LUA, APP, plan["dlc_depots"], plan["owned_dlc"])
        self.assertNotIn('addappid(580102,1', filtered)
        self.assertNotIn('addappid(262065,1', filtered)
        self.assertIn("addappid(580100)", filtered)
        self.assertEqual(sorted(dropped), [262065, 580102])

    def test_nothing_to_add_when_all_owned(self):
        lua = f"addappid({APP})\naddappid(445700)\naddappid(445702,1,\"{KEY}\")\n"
        plan = downloads._owned_plan(lua, APP, {445702: 445700}, licensed={APP, 445700})
        self.assertEqual(plan["add_dlcs"], [])


class AppRunning(unittest.TestCase):
    def test_sees_steam_env_of_a_live_process(self):
        import steam_utils
        env = dict(os.environ, SteamAppId="4242424", SteamGameId="4242424")
        proc = subprocess.Popen(["sleep", "20"], env=env)
        try:
            self.assertTrue(steam_utils.is_app_running(4242424))
            self.assertFalse(steam_utils.is_app_running(4242425))
        finally:
            proc.kill()
            proc.wait()


class OwnedUpdateRelevance(unittest.TestCase):
    """pins._owned_relevant: what the update pass may touch on an owned game."""
    def test_only_dlc_the_account_lacks(self):
        relevant = {262065: {"gid": 1, "dlcappid": None}, 580102: {"gid": 2, "dlcappid": 580100},
                    445702: {"gid": 3, "dlcappid": 445700}}
        out = pins._owned_relevant(relevant, lambda a: a in {APP, 445700})
        self.assertEqual(sorted(out), [580102])

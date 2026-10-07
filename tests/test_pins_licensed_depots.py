"""Option B of lumalinux docs/owned-games-guide.md flow F/G: a depot whose app
the account has a REAL licence for (a game or DLC bought after LumaDeck added
it) is Steam's. ensure_pinned never pins it and releases a pin it already had;
the update pass stores the depot -> app map that makes the question answerable
offline, and ignores a bought DLC on any game.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import manifests  # noqa: E402
import pins  # noqa: E402
import steam_licenses  # noqa: E402

APP, BASE, DLC_DEPOT, DLC = 1000, 1001, 1002, 2000


class LicensedDepots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mids = {}
        self.licensed = set()
        self.calls = []
        self._orig = []

        def patch(mod, name, value):
            self._orig.append((mod, name, getattr(mod, name)))
            setattr(mod, name, value)

        async def set_pin(appid, gids):
            self.calls.append(("set_pin", appid, dict(gids)))
            self.mids.update(gids)
            return True

        async def unpin(appid):
            self.calls.append(("unpin", appid))
            self.mids.clear()
            return True
        patch(pins, "_STATE_PATH", os.path.join(self.tmp, "pins.json"))
        patch(pins, "keyed_depots", lambda appid: {BASE: "k" * 64, DLC_DEPOT: "j" * 64})
        patch(pins, "read_manifest_ids", lambda: dict(self.mids))
        patch(pins, "installed_depots", lambda appid: {BASE: 11, DLC_DEPOT: 22})
        patch(pins, "depotcache_gids", lambda depot: [])
        patch(pins, "get_depotcache_dir", lambda steam_root=None: None)
        patch(pins, "set_pin", set_pin)
        patch(pins, "unpin_game_depots", unpin)
        patch(manifests, "archived_manifests", lambda appid: {})
        patch(steam_licenses, "is_licensed", lambda appid: int(appid) in self.licensed)
        pins.set_depot_apps(APP, {BASE: APP, DLC_DEPOT: DLC})

    def tearDown(self):
        for mod, name, value in self._orig:
            setattr(mod, name, value)

    def pin(self):
        return asyncio.run(pins.ensure_pinned(APP, allow_pin=True))

    def test_nothing_licensed_pins_everything_as_before(self):
        self.assertEqual(self.pin(), {BASE: 11, DLC_DEPOT: 22})
        self.assertEqual(self.calls, [("set_pin", APP, {BASE: 11, DLC_DEPOT: 22})])

    def test_bought_game_keeps_only_its_added_dlc_pinned(self):
        self.licensed = {APP}
        self.assertEqual(self.pin(), {DLC_DEPOT: 22})
        self.assertEqual(self.calls, [("set_pin", APP, {DLC_DEPOT: 22})])

    def test_bought_game_and_dlc_are_never_pinned(self):
        self.licensed = {APP, DLC}
        self.assertEqual(self.pin(), {})
        self.assertEqual(self.calls, [])

    def test_bought_dlc_leaves_only_the_base_to_pin(self):
        self.licensed = {DLC}
        self.assertEqual(self.pin(), {BASE: 11})
        self.assertEqual(self.calls, [("set_pin", APP, {BASE: 11})])

    def test_a_pin_from_before_the_purchase_is_released(self):
        # Frozen by a providers outage, then the user buys the game but not
        # the DLC: Steam's depot is released, ours stays pinned.
        self.mids = {BASE: 11, DLC_DEPOT: 22}
        self.licensed = {APP}
        self.assertEqual(self.pin(), {DLC_DEPOT: 22})
        self.assertEqual(self.calls, [("unpin", APP), ("set_pin", APP, {DLC_DEPOT: 22})])
        self.assertEqual(self.mids, {DLC_DEPOT: 22})

    def test_bought_everything_releases_the_whole_pin(self):
        self.mids = {BASE: 11, DLC_DEPOT: 22}
        self.licensed = {APP, DLC}
        self.assertEqual(self.pin(), {})
        self.assertEqual(self.calls, [("unpin", APP)])
        self.assertEqual(self.mids, {})

    def test_an_unmapped_depot_belongs_to_the_base_game(self):
        pins.set_depot_apps(APP, {})
        self.licensed = {APP}
        self.assertEqual(self.pin(), {})
        self.licensed = {DLC}
        self.assertEqual(self.pin(), {BASE: 11, DLC_DEPOT: 22})

    def test_unreadable_licences_change_nothing(self):
        steam_licenses.is_licensed = lambda appid: (_ for _ in ()).throw(RuntimeError("no packageinfo"))
        self.assertEqual(self.pin(), {BASE: 11, DLC_DEPOT: 22})

    def test_owner_map_from_appinfo(self):
        valve = {
            BASE: {"gid": 1, "dlcappid": None, "fromapp": None},
            DLC_DEPOT: {"gid": 2, "dlcappid": DLC, "fromapp": None},
            1003: {"gid": 3, "dlcappid": None, "fromapp": 777},
            228981: {"gid": 4, "dlcappid": None, "fromapp": None},   # a redist
        }
        self.assertEqual(pins.depot_owner_map(APP, valve), {BASE: APP, DLC_DEPOT: DLC, 1003: 777})
        pins.set_depot_apps(APP, pins.depot_owner_map(APP, valve))
        self.assertEqual(pins.depot_apps(APP), {BASE: APP, DLC_DEPOT: DLC, 1003: 777})


if __name__ == "__main__":
    unittest.main()

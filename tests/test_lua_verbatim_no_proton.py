"""The hub's .lua reaches steamidra_lite as shipped (app line first, nothing
appended) and the add never touches localconfig.vdf.

Measured 2026-10-13 in the codespace (apps 2379780 and 1794680): the Hubcap
.lua already carries every platform depot the app has, Steam picks the depot
by Valve's Deck recommendation whatever keys we hold (Vampire Survivors got
1794681 with 1794685 keyed and its manifest present), it runs the Windows
build under Proton on its own, and a CompatToolMapping written while Steam
runs is lost on its next rewrite of localconfig.vdf. The Linux-depot enrich
pass and the Proton forcing went with that; the enrich pass used to append
the Linux depot a second time, keyed with the app's own key, when the game
was re-added while installed (#33).

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import downloads  # noqa: E402
import steam_utils  # noqa: E402

APP = 1794680
HUBCAP = (
    'addappid(1794680, 1, "4d6aeb4ef64d8f10cf5cc1e532efa20f212f3ec624394ae50b9c18782332b07e")\n'
    'addappid(1794681, 1, "a2ae9bd3450da7127b7298a3e66264d71b8413bd7bacd674788ca98df20ee262")\n'
    '--setManifestid(1794681, "6354157889980277978", 1224291565)\n'
    'addappid(1794684, 1, "a9134bad97d12f2af38c1f3fda9df5c1441e987c3931aed6bcbc8a28d76f2ec9")\n'
    '--setManifestid(1794684, "3164112101380201073", 1170017736)\n'
    'addappid(1794685, 1, "b84475f8ff35397bf450e3fd9e2b62d63058277871f676dcb7fb506c9b89a599")\n'
    '--setManifestid(1794685, "2624639318422129691", 1131740461)\n'
)
LOCALCONF = (
    '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n'
    '\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t}\n'
    '\t\t\t}\n\t\t}\n\t}\n}\n'
)


class LuaVerbatimNoProton(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lumadeck_test_")
        self.steam = os.path.join(self.root, "Steam")
        conf_dir = os.path.join(self.steam, "userdata", "62410692", "config")
        os.makedirs(conf_dir)
        os.makedirs(os.path.join(self.steam, "depotcache"))
        self.localconf = os.path.join(conf_dir, "localconfig.vdf")
        with open(self.localconf, "w", encoding="utf-8") as fh:
            fh.write(LOCALCONF)
        self.zip_path = os.path.join(self.root, f"{APP}.zip")
        with zipfile.ZipFile(self.zip_path, "w") as z:
            z.writestr(f"{APP}.lua", HUBCAP)
            for depot, gid in (("1794681", "6354157889980277978"),
                               ("1794684", "3164112101380201073"),
                               ("1794685", "2624639318422129691")):
                z.writestr(f"{depot}_{gid}.manifest", b"\x00")
        self.seen = {}

    async def _fake_invoke(self, lua_path, manifests_dir, **kw):
        with open(lua_path, encoding="utf-8") as fh:
            self.seen["lua"] = fh.read()
        self.seen["manifests"] = sorted(os.listdir(manifests_dir))
        return True, ""

    def _run(self):
        with mock.patch.object(downloads, "detect_steam_install_path", return_value=self.steam), \
             mock.patch.object(downloads, "_invoke_steamidra_lite", self._fake_invoke), \
             mock.patch.object(downloads, "_count_app_depot_keys", return_value=3), \
             mock.patch.object(downloads, "_is_download_cancelled", return_value=False), \
             mock.patch("pins.is_owned", return_value=False), \
             mock.patch("manifests.archive_zip", return_value=0), \
             mock.patch("slssteam_ops.prune_retired_keys", return_value=0):
            asyncio.run(downloads._process_and_install_lua(APP, self.zip_path))

    def test_lua_reaches_steamidra_as_the_hub_shipped_it(self):
        self._run()
        self.assertEqual(self.seen["lua"], HUBCAP)
        self.assertEqual(self.seen["lua"].count("addappid(1794685"), 1)
        self.assertEqual([m for m in self.seen["manifests"] if m.endswith(".manifest")],
                         ["1794681_6354157889980277978.manifest",
                          "1794684_3164112101380201073.manifest",
                          "1794685_2624639318422129691.manifest"])

    def test_localconfig_is_never_written(self):
        before = os.stat(self.localconf).st_mtime_ns
        self._run()
        with open(self.localconf, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), LOCALCONF)
        self.assertEqual(os.stat(self.localconf).st_mtime_ns, before)

    def test_the_forcing_helper_is_gone(self):
        self.assertFalse(hasattr(steam_utils, "set_compat_tool_for_app"))
        self.assertFalse(hasattr(downloads, "_enrich_lua_with_linux_depot"))


if __name__ == "__main__":
    unittest.main()

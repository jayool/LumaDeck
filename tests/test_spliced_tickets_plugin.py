"""backend/installer.py — the spliced-tickets plugin install:
    python -m unittest discover -s tests

Pins: `Plugins: yes` is flipped or appended; the .lua lands in <config dir>/
plugins/ under LumaDeck's own file name, byte-identical to the bundled copy; a
second run rewrites nothing; the kill-switch file and an SLSsteam release older
than the plugin system (or unknown) skip everything; foreign plugins survive;
a changed bundled copy is re-deployed.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import installer  # noqa: E402

NEW = ("20260903114323", "recorded")
OLD = ("20260820085507", "recorded")


class SplicedTickets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.cfg_dir = os.path.join(self.tmp, "SLSsteam")
        os.makedirs(self.cfg_dir)
        self.cfg = os.path.join(self.cfg_dir, "config.yaml")
        self.plugins = os.path.join(self.cfg_dir, "plugins")
        self.dest = os.path.join(self.plugins, installer.SPLICED_TICKETS_PLUGIN)
        self._real_home = installer.real_home
        installer.real_home = lambda: self.home
        self.addCleanup(lambda: setattr(installer, "real_home", self._real_home))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        with open(installer._spliced_tickets_source(), "rb") as f:
            self.bundled = f.read()

    def _write_cfg(self, text="PlayNotOwnedGames: yes\nPlugins: no\n"):
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write(text)

    def _cfg(self):
        with open(self.cfg, encoding="utf-8") as f:
            return f.read()

    def test_bundled_plugin_is_aces_file(self):
        body = self.bundled.decode("utf-8")
        self.assertIn("SplicedTickets = SplicedTickets or {", body)      # the double-load guard
        self.assertIn('VFTableInfo_t("14IClientUserMap", "GetAppOwnershipTicketExtendedData")', body)
        self.assertIn("Author: Ace", body)

    def test_installs_and_flips_plugins_no_to_yes(self):
        self._write_cfg()
        ok, msg = installer._install_spliced_tickets(self.cfg, NEW)
        self.assertTrue(ok, msg)
        self.assertIn("Plugins: yes", self._cfg())
        self.assertNotIn("Plugins: no", self._cfg())
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), self.bundled)
        self.assertEqual(oct(os.stat(self.dest).st_mode & 0o777), "0o600")

    def test_appends_plugins_key_when_absent(self):
        self._write_cfg("PlayNotOwnedGames: yes")               # no trailing newline, no key
        ok, msg = installer._install_spliced_tickets(self.cfg, NEW)
        self.assertTrue(ok, msg)
        self.assertEqual(self._cfg(), "PlayNotOwnedGames: yes\nPlugins: yes\n")

    def test_second_run_rewrites_nothing(self):
        self._write_cfg()
        installer._install_spliced_tickets(self.cfg, NEW)
        cfg_before, st_before = self._cfg(), os.stat(self.dest)
        ok, msg = installer._install_spliced_tickets(self.cfg, NEW)
        self.assertTrue(ok, msg)
        self.assertIn("already", msg)
        self.assertEqual(self._cfg(), cfg_before)
        self.assertEqual(os.stat(self.dest).st_ino, st_before.st_ino)   # same file, not replaced

    def test_kill_switch_skips_everything(self):
        self._write_cfg()
        ks = installer._spliced_tickets_kill_switch_path()
        os.makedirs(os.path.dirname(ks))
        open(ks, "w").close()
        ok, msg = installer._install_spliced_tickets(self.cfg, NEW)
        self.assertTrue(ok)
        self.assertIn("kill-switch", msg)
        self.assertIn("Plugins: no", self._cfg())
        self.assertFalse(os.path.exists(self.plugins))

    def test_old_or_unknown_slssteam_skips(self):
        for ver in (OLD, (None, "unknown"), ("20260819120840", "derived")):
            with self.subTest(ver=ver):
                self._write_cfg()
                ok, msg = installer._install_spliced_tickets(self.cfg, ver)
                self.assertTrue(ok)
                self.assertIn("skipped", msg)
                self.assertIn("Plugins: no", self._cfg())
                self.assertFalse(os.path.exists(self.plugins))

    def test_recorded_version_is_used_when_none_passed(self):
        self._write_cfg()
        import slssteam_version
        orig = slssteam_version.read_recorded_version
        slssteam_version.read_recorded_version = lambda: "20260903114323"
        self.addCleanup(lambda: setattr(slssteam_version, "read_recorded_version", orig))
        ok, msg = installer._install_spliced_tickets(self.cfg)
        self.assertTrue(ok, msg)
        self.assertTrue(os.path.isfile(self.dest))

    def test_foreign_plugin_survives(self):
        self._write_cfg()
        os.makedirs(self.plugins)
        foreign = os.path.join(self.plugins, "download.lua")
        with open(foreign, "w") as f:
            f.write("-- someone else's\n")
        ok, msg = installer._install_spliced_tickets(self.cfg, NEW)
        self.assertTrue(ok, msg)
        self.assertTrue(os.path.isfile(foreign))
        self.assertEqual(sorted(os.listdir(self.plugins)), sorted(["download.lua", installer.SPLICED_TICKETS_PLUGIN]))

    def test_changed_bundle_is_redeployed(self):
        self._write_cfg()
        os.makedirs(self.plugins)
        with open(self.dest, "wb") as f:
            f.write(b"-- stale copy\n")
        ok, msg = installer._install_spliced_tickets(self.cfg, NEW)
        self.assertTrue(ok, msg)
        self.assertIn("updated", msg)
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), self.bundled)

    def test_ensure_flags_reports_spliced_tickets(self):
        self._write_cfg("DisableCloud: yes\nDisableUpdates: yes\nSafeMode: yes\nPlugins: no\n")
        orig = installer.get_slssteam_config_path
        installer.get_slssteam_config_path = lambda: self.cfg
        self.addCleanup(lambda: setattr(installer, "get_slssteam_config_path", orig))
        res = installer.ensure_slssteam_flags(NEW)
        self.assertTrue(res["applied"])
        self.assertTrue(res["results"]["SplicedTickets"]["ok"], res["results"])
        self.assertTrue(os.path.isfile(self.dest))


if __name__ == "__main__":
    unittest.main()

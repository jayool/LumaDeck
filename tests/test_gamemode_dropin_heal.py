"""paths.heal_gamemode_dropin — the Game Mode steam-launcher.service drop-in
self-heal that runs once per plugin start (main.py `_main`).

Why this exists: the heal has shipped since September with no test and no Deck
measurement of its own (the 2026-10-14 factory-reset run exercised setup.sh's
drop-in, not the plugin's heal). It writes into ~/.config/systemd/user and
talks to the user's systemd from a root service, so a regression there is a
Game Mode that launches Steam un-injected — or not at all. Real files in a temp
home, a scripted `systemctl --user` (no systemd, no Steam, no network):
    python -m unittest discover -s tests

The cases:
  * healthy Deck            -> no write, no reload ("already_active")
  * drop-in missing         -> written byte-for-byte, then daemon-reload
  * drop-in on disk, inert  -> no write, daemon-reload (the 0.7.1 state)
  * systemd query fails     -> reload anyway, never treated as broken
  * no launcher, no drop-in -> hands off, no systemctl call at all
  * no launcher, OUR stale drop-in -> removed + reload (Steam launches vanilla)
  * no launcher, FOREIGN drop-in   -> never touched
  * the root -> deck-user systemctl crossing builds the argv it documents
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths  # noqa: E402

LOADED_OURS = "ExecStart={ path=/home/deck/.local/share/SLSsteam/lumalinux-steam-launcher ; argv[]=... }\n"
LOADED_VANILLA = "ExecStart={ path=/usr/lib/steamos/steam-launcher ; argv[]=/usr/lib/steamos/steam-launcher }\n"
FOREIGN_DROPIN = ("[Service]\n# managed-by: luatools-slssteam\nExecStart=\n"
                  "ExecStart=/bin/sh -c 'PATH=\"%h/.local/share/SLSsteam/path:$$PATH\" exec /usr/lib/steamos/steam-launcher'\n")


class FakeSystemctl:
    """Scripted `systemctl --user`: records every call, answers `show` with the
    configured ExecStart (or a failure) and `daemon-reload` with rc 0."""

    def __init__(self, show_out=LOADED_OURS, show_rc=0, reload_rc=0):
        self.show_out, self.show_rc, self.reload_rc = show_out, show_rc, reload_rc
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        if args and args[0] == "show":
            return self.show_rc, self.show_out if self.show_rc == 0 else "", "", "runuser"
        if args and args[0] == "daemon-reload":
            return self.reload_rc, "", "" if self.reload_rc == 0 else "Failed to connect to bus", "runuser"
        raise AssertionError(f"unexpected systemctl call: {args}")

    @property
    def reloads(self):
        return sum(1 for c in self.calls if c and c[0] == "daemon-reload")


class HealGamemodeDropin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.launcher = os.path.join(self.home, paths._GM_LAUNCHER_REL)
        self.dropin = os.path.join(self.home, paths._GM_DROPIN_REL)
        self._home_patch = mock.patch.object(paths, "_REAL_HOME", self.home)
        self._home_patch.start()

    def tearDown(self):
        self._home_patch.stop()
        self.tmp.cleanup()

    # -- helpers ------------------------------------------------------------
    def put_launcher(self):
        os.makedirs(os.path.dirname(self.launcher), exist_ok=True)
        with open(self.launcher, "w") as fh:
            fh.write("#!/bin/sh\nexec /usr/lib/steamos/steam-launcher \"$@\"\n")
        os.chmod(self.launcher, 0o755)

    def put_dropin(self, content=paths._GM_DROPIN_CONTENT):
        os.makedirs(os.path.dirname(self.dropin), exist_ok=True)
        with open(self.dropin, "w") as fh:
            fh.write(content)

    def heal(self, fake):
        with mock.patch.object(paths, "_run_user_systemctl", fake):
            return paths.heal_gamemode_dropin()

    # -- cases --------------------------------------------------------------
    def test_healthy_deck_is_left_alone(self):
        self.put_launcher()
        self.put_dropin()
        before = os.stat(self.dropin).st_mtime_ns
        fake = FakeSystemctl(show_out=LOADED_OURS)
        res = self.heal(fake)
        self.assertFalse(res["healed"])
        self.assertEqual(res["reason"], "already_active")
        self.assertEqual(fake.reloads, 0, "a healthy Deck must not daemon-reload every boot")
        self.assertEqual(os.stat(self.dropin).st_mtime_ns, before, "file must not be rewritten")

    def test_missing_dropin_is_written_and_loaded(self):
        self.put_launcher()
        fake = FakeSystemctl(show_out=LOADED_VANILLA)
        res = self.heal(fake)
        self.assertTrue(res["healed"])
        self.assertEqual(res["reason"], "written")
        self.assertTrue(res["wrote"])
        self.assertEqual(fake.reloads, 1)
        with open(self.dropin) as fh:
            content = fh.read()
        self.assertEqual(content, paths._GM_DROPIN_CONTENT)
        # The two load-bearing lines of the drop-in: reset ExecStart, then ours.
        self.assertIn("\nExecStart=\n", content)
        self.assertIn("ExecStart=%h/.local/share/SLSsteam/lumalinux-steam-launcher", content)
        self.assertEqual(oct(os.stat(self.dropin).st_mode & 0o777), "0o644")

    def test_wrong_dropin_is_rewritten(self):
        self.put_launcher()
        self.put_dropin("[Service]\nExecStart=\nExecStart=/usr/bin/true\n")
        fake = FakeSystemctl(show_out=LOADED_VANILLA)
        res = self.heal(fake)
        self.assertEqual(res["reason"], "written")
        with open(self.dropin) as fh:
            self.assertEqual(fh.read(), paths._GM_DROPIN_CONTENT)

    def test_inert_dropin_is_reloaded_not_rewritten(self):
        self.put_launcher()
        self.put_dropin()
        before = os.stat(self.dropin).st_mtime_ns
        fake = FakeSystemctl(show_out=LOADED_VANILLA)  # correct on disk, systemd never read it
        res = self.heal(fake)
        self.assertTrue(res["healed"])
        self.assertEqual(res["reason"], "reloaded_inert_dropin")
        self.assertFalse(res["wrote"])
        self.assertEqual(fake.reloads, 1)
        self.assertEqual(os.stat(self.dropin).st_mtime_ns, before)

    def test_failed_query_reloads_but_is_not_broken(self):
        self.put_launcher()
        self.put_dropin()
        fake = FakeSystemctl(show_rc=1)  # user bus not reachable yet
        res = self.heal(fake)
        self.assertEqual(res["reason"], "reloaded_unverified")
        self.assertIsNone(res["loaded"])
        self.assertEqual(fake.reloads, 1)

    def test_failed_reload_is_reported_not_hidden(self):
        self.put_launcher()
        fake = FakeSystemctl(show_out=LOADED_VANILLA, reload_rc=1)
        res = self.heal(fake)
        self.assertTrue(res["wrote"], "the file is still written; only the reload failed")
        self.assertFalse(res["reloaded"])
        self.assertIn("rc=1", res["reload_detail"])
        self.assertIn("Failed to connect to bus", res["reload_detail"])

    def test_no_launcher_no_dropin_hands_off(self):
        fake = FakeSystemctl()
        res = self.heal(fake)
        self.assertFalse(res["healed"])
        self.assertEqual(res["reason"], "no_launcher")
        self.assertFalse(os.path.exists(self.dropin), "must never point ExecStart at a missing launcher")
        self.assertEqual(fake.calls, [], "nothing to heal: no systemctl traffic")

    def test_orphan_dropin_is_removed(self):
        """Launcher gone (SLSDeck's uninstall, moon's `setup.sh uninstall`, a
        manual rm -rf of ~/.local/share/SLSsteam) but OUR drop-in survived in
        ~/.config/systemd/user: steam-launcher.service would exec a missing file
        and Game Mode comes up without Steam. The heal must remove the stale
        drop-in and reload so Steam launches vanilla."""
        self.put_dropin()
        fake = FakeSystemctl(show_out=LOADED_OURS)
        res = self.heal(fake)
        self.assertFalse(os.path.exists(self.dropin), "stale drop-in must be removed")
        self.assertTrue(os.path.isdir(os.path.dirname(self.dropin)), "only the file goes")
        self.assertEqual(fake.reloads, 1)
        self.assertEqual([c[0] for c in fake.calls], ["daemon-reload"], "no show query: nothing to verify")
        self.assertTrue(res["healed"])
        self.assertEqual(res["reason"], "orphan_dropin_removed")
        self.assertFalse(res["wrote"])
        self.assertTrue(res["reloaded"])

    def test_orphan_dropin_removal_survives_a_failed_reload(self):
        """The file is still removed when daemon-reload fails (bus not up yet):
        the next Game Mode boot reads unit files fresh, so the stale ExecStart is
        gone either way. The failure is reported, not hidden."""
        self.put_dropin()
        fake = FakeSystemctl(reload_rc=1)
        res = self.heal(fake)
        self.assertFalse(os.path.exists(self.dropin))
        self.assertEqual(res["reason"], "orphan_dropin_removed")
        self.assertFalse(res["reloaded"])
        self.assertIn("rc=1", res["reload_detail"])

    def test_foreign_dropin_is_never_touched(self):
        """No launcher and a drop-in that is not ours (SLSDeck's 50-slsdeck.conf
        shape, written at our path): hands off, whatever the pending orphan
        rule does for our own file."""
        self.put_dropin(FOREIGN_DROPIN)
        fake = FakeSystemctl(show_out=LOADED_VANILLA)
        res = self.heal(fake)
        self.assertEqual(res["reason"], "no_launcher")
        with open(self.dropin) as fh:
            self.assertEqual(fh.read(), FOREIGN_DROPIN)
        self.assertEqual(fake.calls, [])


class RunUserSystemctl(unittest.TestCase):
    """_run_user_systemctl: the root -> deck-user crossing. Decky's loader runs
    as root with a minimal PATH and no session env; the argv must carry absolute
    binaries, runuser (not sudo), and the user's XDG_RUNTIME_DIR / bus."""

    def _capture(self, euid, uid=1000, user="deck", home="/home/deck"):
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"] = list(argv)
            seen["timeout"] = kw.get("timeout")
            return mock.Mock(returncode=0, stdout="ok", stderr="")

        with mock.patch.object(paths.os, "geteuid", lambda: euid), \
             mock.patch.object(paths, "_REAL_UID", uid), \
             mock.patch.object(paths, "_REAL_USER", user), \
             mock.patch.object(paths, "_REAL_HOME", home), \
             mock.patch.object(paths, "_resolve_bin", lambda name, fb: "/usr/bin/" + name), \
             mock.patch("subprocess.run", fake_run):
            rc, out, err, via = paths._run_user_systemctl(["daemon-reload"])
        return rc, out, via, seen

    def test_as_root_crosses_with_runuser(self):
        rc, out, via, seen = self._capture(euid=0)
        self.assertEqual((rc, out, via), (0, "ok", "runuser"))
        argv = seen["argv"]
        self.assertEqual(argv[:4], ["/usr/bin/runuser", "-u", "deck", "--"])
        self.assertEqual(argv[4], "/usr/bin/env")
        self.assertIn("HOME=/home/deck", argv)
        self.assertIn("XDG_RUNTIME_DIR=/run/user/1000", argv)
        self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus", argv)
        self.assertEqual(argv[-3:], ["/usr/bin/systemctl", "--user", "daemon-reload"])
        self.assertNotIn("sudo", " ".join(argv))
        self.assertEqual(seen["timeout"], 20)

    def test_as_user_injects_session_env_without_runuser(self):
        rc, out, via, seen = self._capture(euid=1000)
        argv = seen["argv"]
        self.assertEqual(via, "env")
        self.assertEqual(argv[0], "/usr/bin/env")
        self.assertNotIn("/usr/bin/runuser", argv)
        self.assertIn("XDG_RUNTIME_DIR=/run/user/1000", argv)
        self.assertEqual(argv[-3:], ["/usr/bin/systemctl", "--user", "daemon-reload"])

    def test_exec_error_is_returned_not_raised(self):
        def boom(argv, **kw):
            raise FileNotFoundError("runuser")

        with mock.patch.object(paths, "_resolve_bin", lambda name, fb: name), \
             mock.patch("subprocess.run", boom):
            rc, out, err, via = paths._run_user_systemctl(["show", "x"])
        self.assertIsNone(rc)
        self.assertIn("runuser", err)


if __name__ == "__main__":
    unittest.main()

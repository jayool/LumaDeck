"""steamidra_lite is told where Steam, SLSsteam's config.yaml and keys.txt are
on every invocation, and the phantom-install post-check reads the same
keys.txt. Both used to come from the subprocess's HOME (Path.home() in the
script, expanduser in the post-check): right on SteamOS, where Decky runs as
root with HOME=/home/deck, wrong wherever root keeps /root. The rest of the
backend resolves the real user's home instead (paths.real_home); these are
the last two readers that didn't.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import downloads  # noqa: E402


class _FakeProc:
    returncode = 0

    def __init__(self):
        self.stdout = self

    async def readline(self):
        return b""

    async def wait(self):
        return 0

    async def communicate(self):
        return b"", b""


class SteamidraPathsExplicit(unittest.TestCase):
    def setUp(self):
        self.calls = []

        async def fake_exec(*cmd, **kw):
            self.calls.append(list(cmd))
            return _FakeProc()

        self.patches = [
            mock.patch.object(downloads, "_find_steamidra_lite_script", return_value="/x/steamidra_lite.py"),
            mock.patch.object(downloads, "detect_steam_install_path", return_value="/home/deck/.local/share/Steam"),
            mock.patch.object(downloads, "get_slssteam_config_path", return_value="/home/deck/.config/SLSsteam/config.yaml"),
            mock.patch.object(downloads, "get_lumalinux_keys_path", return_value="/home/deck/.config/lumalinux/keys.txt"),
            mock.patch.object(downloads.asyncio, "create_subprocess_exec", fake_exec),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _flag(self, cmd, name):
        return cmd[cmd.index(name) + 1]

    def test_add_carries_the_three_paths(self):
        ok, _ = asyncio.run(downloads._invoke_steamidra_lite("/tmp/1.lua", manifests_dir="/tmp"))
        self.assertTrue(ok)
        cmd = self.calls[0]
        self.assertEqual(self._flag(cmd, "--steam-root"), "/home/deck/.local/share/Steam")
        self.assertEqual(self._flag(cmd, "--sls-config"), "/home/deck/.config/SLSsteam/config.yaml")
        self.assertEqual(self._flag(cmd, "--luma-keys"), "/home/deck/.config/lumalinux/keys.txt")
        self.assertEqual(cmd[2], "/tmp/1.lua")  # input stays positional, right after the script

    def test_zipless_modes_carry_the_three_paths_before_the_mode(self):
        asyncio.run(downloads._run_steamidra_mode(["--set-pin", "10", "11:22"]))
        cmd = self.calls[0]
        for name in ("--steam-root", "--sls-config", "--luma-keys"):
            self.assertIn(name, cmd)
        # --set-pin takes nargs="+": it must be the last thing on the line.
        self.assertEqual(cmd[-3:], ["--set-pin", "10", "11:22"])

    def test_post_check_reads_the_resolved_keys_file(self):
        with tempfile.TemporaryDirectory() as d:
            keys = os.path.join(d, "keys.txt")
            with open(keys, "w") as fh:
                fh.write("1794681;1794680;0;0;" + "a" * 64 + "\n")
                fh.write("1794685;1794680;0;0;" + "b" * 64 + "\n")
                fh.write("2379781;2379780;0;0;" + "c" * 64 + "\n")
            with mock.patch.object(downloads, "get_lumalinux_keys_path", return_value=keys), \
                 mock.patch.dict(os.environ, {"HOME": "/nonexistent"}):
                self.assertEqual(downloads._count_app_depot_keys(1794680), 2)
                self.assertEqual(downloads._count_app_depot_keys(2379780), 1)
                self.assertEqual(downloads._count_app_depot_keys(504230), 0)


if __name__ == "__main__":
    unittest.main()

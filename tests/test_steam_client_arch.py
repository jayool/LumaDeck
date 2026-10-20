"""Which Steam client runs — ubuntu12_32 or steamrt64 (backend/paths.py
detect_steam_client_arch). The 64-bit client keeps the 32-bit tree on disk, so
the answer comes from the running process, then Valve's opt-in marker, and is
the 32-bit client for everything else (no Steam, no marker, no /proc): every
caller then behaves exactly as before the 64-bit client existed."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import paths  # noqa: E402


def _fake_proc(d, cmdlines_by_pid):
    for pid, argv in cmdlines_by_pid.items():
        os.makedirs(os.path.join(d, str(pid)))
        with open(os.path.join(d, str(pid), "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in argv) + b"\0")


class SteamClientArchTests(unittest.TestCase):
    def test_running_64bit_client_wins(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_proc(d, {
                10: ["bash", "/home/deck/.local/share/Steam/steam.sh", "-gamepadui"],
                20: ["/home/deck/.local/share/Steam/steamrt64/steam", "-srt-logger-opened", "-gamepadui"],
            })
            self.assertEqual(paths.detect_steam_client_arch(proc_root=d, steam_root="/nonexistent"), "steamrt64")

    def test_running_32bit_client(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_proc(d, {
                20: ["/home/deck/.local/share/Steam/ubuntu12_32/steam", "-srt-logger-opened", "-gamepadui"],
                # the runtime tools next to it are not the client
                21: ["/home/deck/.local/share/Steam/ubuntu12_32/steam-runtime/usr/libexec/srt-logger"],
            })
            self.assertEqual(paths.detect_steam_client_arch(proc_root=d, steam_root="/nonexistent"), "ubuntu12_32")

    def test_no_steam_running_marker_decides(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as root:
            _fake_proc(d, {30: ["bash"]})
            self.assertEqual(paths.detect_steam_client_arch(proc_root=d, steam_root=root), "ubuntu12_32")
            open(os.path.join(root, ".steam-enable-steamrt64-client"), "w").close()
            self.assertEqual(paths.detect_steam_client_arch(proc_root=d, steam_root=root), "steamrt64")

    def test_unreadable_proc_and_no_root_is_32bit(self):
        self.assertEqual(paths.detect_steam_client_arch(proc_root="/nonexistent/proc", steam_root="/nonexistent"),
                         "ubuntu12_32")

    def test_client_hash_follows_the_running_client(self):
        """steam_update_gate.current_client_hash hashes the running client's
        steamclient.so, not ubuntu12_32/ unconditionally."""
        import hashlib
        from unittest import mock
        import steam_update_gate as gate
        with tempfile.TemporaryDirectory() as root:
            for arch, payload in (("ubuntu12_32", b"thirty-two"), ("steamrt64", b"sixty-four")):
                os.makedirs(os.path.join(root, arch))
                with open(os.path.join(root, arch, "steamclient.so"), "wb") as f:
                    f.write(payload)
            with mock.patch.object(gate, "find_steam_root", return_value=root), \
                 mock.patch.object(paths, "steam_client_arch", return_value="steamrt64"), \
                 mock.patch.object(gate, "_read_hash_file", return_value=None), \
                 mock.patch.object(gate, "_write_hash_file", lambda *a, **k: None):
                gate._HASH_CACHE.clear()
                self.assertEqual(gate.current_client_hash(), hashlib.sha256(b"sixty-four").hexdigest())
            with mock.patch.object(gate, "find_steam_root", return_value=root), \
                 mock.patch.object(paths, "steam_client_arch", return_value="ubuntu12_32"), \
                 mock.patch.object(gate, "_read_hash_file", return_value=None), \
                 mock.patch.object(gate, "_write_hash_file", lambda *a, **k: None):
                gate._HASH_CACHE.clear()
                self.assertEqual(gate.current_client_hash(), hashlib.sha256(b"thirty-two").hexdigest())


if __name__ == "__main__":
    unittest.main()

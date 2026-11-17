"""CloudRedirect's init outcome is read from its own log (backend/paths).

The builds we ship (public 2.6.6 source, 32- and 64-bit) write "CloudRedirect
build ..." and "Init failed: ..." to ~/.config/CloudRedirect/cloud_redirect.log;
cr_debug.log is a fallback. Two causes come out: "restart" when CloudRedirect
gave up before Steam was ready (steamclient.so not mapped in time, or the
.data.rel.ro relocations not done after 30 s: a loaded machine, an update
applying), "not_hooked" when this Steam build defeats it (vtable not found,
hook install failed, crash guard tripped). The relocation timeout ends in the
same "transport vtable not found" line as a real incompatibility and is told
apart by the "Relocations did not complete" line before it. The file is appended for the life of the install
and every preloaded process writes a "started" header (the whole launcher
chain on the 64-bit client), so only the text after the LAST
"=== CloudRedirect loaded [BUILD:...] ===" marker (the client that got to init)
is inspected: a failure from weeks ago must not read as today's.

    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths  # noqa: E402

HEADER = "[INFO] === CloudRedirect Linux started ===\n[INFO] cloud_redirect.so active in process 'steam' (pid={})\n"
MARKER = "[INFO] === CloudRedirect loaded [BUILD:2.6.6] ===\n[INFO] CloudRedirect build {}\n"
OK = "[INFO] CloudRedirect initialized successfully (all hooks active)\n"
FAILED = "[ERROR] vtable for CClientUnifiedServiceTransport not found (typeinfo=0x7f00)\n[ERROR] Init failed: transport vtable not found\n"
RELOC_TIMEOUT = ("[INFO] Relocations pending for .data.rel.ro, waiting...\n"
                 "[ERROR] Relocations did not complete after 30000ms (name_ptr=0x1a2b3c, expected 0xf7a1b2c3)\n"
                 "[ERROR] Init failed: transport vtable not found\n")
NO_STEAMCLIENT = "[ERROR] Init failed: steamclient.so not found in maps\n"
HOOK_FAILED = "[ERROR] mprotect RW failed on vtable\n[ERROR] Init failed: transport hook installation failed\n"
CRASHED = "[ERROR] Caught signal during init - incompatible steamclient? Hooks NOT installed.\n"


class LogSource(unittest.TestCase):
    def test_cloud_redirect_log_first_then_cr_debug(self):
        self.assertTrue(paths._CR_LOG_PATHS[0].endswith("cloud_redirect.log"))
        self.assertTrue(any(p.endswith("cr_debug.log") for p in paths._CR_LOG_PATHS))


class LastInit(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.log = os.path.join(self.d.name, "cloud_redirect.log")
        saved = paths._cloudredirect_log_path
        paths._cloudredirect_log_path = lambda: self.log
        self.addCleanup(setattr, paths, "_cloudredirect_log_path", saved)

    def _write(self, text):
        with open(self.log, "w") as f:
            f.write(text)

    def test_old_failure_then_a_clean_init_reads_clean(self):
        self._write(HEADER.format(1) + MARKER.format("2.6.6+3434d9d") + FAILED
                    + HEADER.format(2) + HEADER.format(3) + MARKER.format("2.6.6+2a48dac") + OK)
        self.assertEqual(paths._cloudredirect_log_inspect(), ("2.6.6+2a48dac", None))

    def test_a_clean_past_then_a_failed_init_reads_failed(self):
        self._write(HEADER.format(1) + MARKER.format("2.6.6+2a48dac") + OK
                    + HEADER.format(2) + MARKER.format("2.6.6+2a48dac") + FAILED)
        self.assertEqual(paths._cloudredirect_log_inspect(), ("2.6.6+2a48dac", "not_hooked"))

    def test_launcher_chain_headers_after_the_init_do_not_hide_it(self):
        # 64-bit client: processes that only write the header (no init) come
        # before AND after the one that initialised; the marker is what counts.
        self._write(HEADER.format(1) + HEADER.format(2) + MARKER.format("2.6.6+2a48dac") + OK
                    + HEADER.format(3) + HEADER.format(4))
        self.assertEqual(paths._cloudredirect_log_inspect(), ("2.6.6+2a48dac", None))

    def test_no_marker_reads_the_whole_file(self):
        self._write("[INFO] CloudRedirect build 2.6.5+870afdb transport=external-curl\n" + FAILED)
        self.assertEqual(paths._cloudredirect_log_inspect(), ("2.6.5+870afdb", "not_hooked"))

    def test_only_init_failed_lines_count(self):
        # CR's own verdict: optional hooks missing are warnings/errors it carries
        # on from, and it still says "initialized successfully".
        self._write(MARKER.format("2.6.6+2a48dac")
                    + "[WARN] CUserRemoteStorage vtable not found (cloud toggle may not work)\n"
                    + "[ERROR] Protobuf helpers not fully resolved -- cloud RPCs may fail\n" + OK)
        self.assertEqual(paths._cloudredirect_log_inspect(), ("2.6.6+2a48dac", None))

    def test_missing_file(self):
        self.assertEqual(paths._cloudredirect_log_inspect(), (None, None))


class WhichCause(LastInit):
    """Fixed by a Steam restart versus this Steam build defeats it."""

    def test_relocation_timeout_is_restart_despite_the_vtable_line(self):
        # A codespace under load, 2026-11-17: Steam took more than 30 s to
        # relocate, CR gave up with the same final line as an incompatibility.
        # A Steam restart fixed it.
        self._write(MARKER.format("2.6.6+2a48dac") + RELOC_TIMEOUT)
        self.assertEqual(paths._cloudredirect_log_inspect(), ("2.6.6+2a48dac", "restart"))

    def test_steamclient_not_found_is_restart(self):
        # The 32-bit build's 10 s wait ran out before Steam mapped its client.
        self._write(MARKER.format("2.6.6+3434d9d") + NO_STEAMCLIENT)
        self.assertEqual(paths._cloudredirect_log_inspect(), ("2.6.6+3434d9d", "restart"))

    def test_vtable_not_found_without_a_relocation_wait_is_not_hooked(self):
        self._write(MARKER.format("2.6.6+2a48dac") + FAILED)
        self.assertEqual(paths._cloudredirect_log_inspect()[1], "not_hooked")

    def test_hook_install_failure_is_not_hooked(self):
        self._write(MARKER.format("2.6.6+2a48dac") + HOOK_FAILED)
        self.assertEqual(paths._cloudredirect_log_inspect()[1], "not_hooked")

    def test_crash_guard_tripping_is_not_hooked(self):
        # No "Init failed" line at all: CR's own crash guard caught a fault
        # while scanning and gave up. Used to read as a clean init.
        self._write(MARKER.format("2.6.6+2a48dac") + CRASHED)
        self.assertEqual(paths._cloudredirect_log_inspect()[1], "not_hooked")

    def test_an_old_relocation_timeout_does_not_colour_a_later_init(self):
        self._write(MARKER.format("2.6.6+2a48dac") + RELOC_TIMEOUT
                    + HEADER.format(2) + MARKER.format("2.6.6+2a48dac") + FAILED)
        self.assertEqual(paths._cloudredirect_log_inspect()[1], "not_hooked")
        self._write(MARKER.format("2.6.6+2a48dac") + FAILED
                    + HEADER.format(2) + MARKER.format("2.6.6+2a48dac") + OK)
        self.assertEqual(paths._cloudredirect_log_inspect()[1], None)


if __name__ == "__main__":
    unittest.main()

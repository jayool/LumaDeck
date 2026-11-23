"""setup.sh output as the QAM sees it: the installer's reader splits on
carriage returns (curl's and flatpak's bars never print a newline until they
end, which left the panel frozen; a user's report, 2026-11-21) and feeds the
tracker (install_progress.py) whose own tests are in test_install_progress."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from installer import new_install_state, note_output_line, set_phase, split_output, status_view  # noqa: E402


class InstallerProgressTests(unittest.TestCase):
    def test_split_on_cr_lf_and_crlf_keeps_the_tail(self):
        lines, tail = split_output(b"[*] Downloading SLSsteam\n#####   12.0%\r######  18.5%\r")
        self.assertEqual(lines, ["[*] Downloading SLSsteam", "#####   12.0%", "######  18.5%"])
        self.assertEqual(tail, b"")
        lines, tail = split_output(b"[+] Deployed\r\n####")
        self.assertEqual(lines, ["[+] Deployed"])
        self.assertEqual(tail, b"####")
        lines, tail = split_output(tail + b"  40.0%\r[+] done\n")
        self.assertEqual(lines, ["####  40.0%", "[+] done"])
        # flatpak redraws its table with cursor codes and no newline for a minute:
        # every escape sequence is a separator too, so the rows reach the tracker
        lines, tail = split_output(b"1. [/] a b i f 1.0 kB / 147.8 MB\x1b[1A\x1b[K2. [ ] c d i f < 14.6 MB\x1b[")
        self.assertEqual(lines, ["1. [/] a b i f 1.0 kB / 147.8 MB", "2. [ ] c d i f < 14.6 MB"])
        self.assertEqual(tail, b"\x1b[")

    def test_state_view_carries_the_bar(self):
        state = new_install_state()
        set_phase(state, "preparing")
        note_output_line(state, "\x1b[0;36m[*]\x1b[0m Downloading SLSsteam (latest), release 1...")
        note_output_line(state, "########                                  21.4%")
        v = status_view(state)
        self.assertEqual(v["status"], "installing")
        self.assertEqual((v["phase"], v["progress"], v["percent"], v["step"], v["stepTotal"]),
                         ("slssteam", "Downloading SLSsteam…", 21.4, 2, 9))
        self.assertNotIn("tracker", v)
        set_phase(state, "done")
        self.assertEqual(status_view(state)["overall"], 100.0)


if __name__ == "__main__":
    unittest.main()

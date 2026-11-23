"""setup.sh output as the QAM sees it during Quick Install: the reader splits
on carriage returns (curl's --progress-bar never prints a newline until the
download ends, which left the panel frozen on the step text; a user's report,
2026-11-21), a bar line becomes a percent, any other line is the step text."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from installer import note_output_line, phase_for_line, set_phase, split_output  # noqa: E402


class InstallerProgressTests(unittest.TestCase):
    def test_split_on_cr_lf_and_crlf_keeps_the_tail(self):
        lines, tail = split_output(b"[*] Downloading SLSsteam\n#####   12.0%\r######  18.5%\r")
        assert lines == ["[*] Downloading SLSsteam", "#####   12.0%", "######  18.5%"]
        assert tail == b""
        lines, tail = split_output(b"[+] Deployed\r\n####")
        assert lines == ["[+] Deployed"]
        assert tail == b"####"
        lines, tail = split_output(tail + b"  40.0%\r[+] done\n")
        assert lines == ["####  40.0%", "[+] done"]

    def test_bar_line_is_a_percent_and_keeps_the_phase(self):
        state = {"progress": "", "percent": None, "phase": None, "detail": ""}
        note_output_line(state, "\x1b[0;36m[*]\x1b[0m Downloading SLSsteam (64-bit client), release v20261112130346...")
        self.assertEqual(state["phase"], "slssteam")
        self.assertEqual(state["progress"], "Downloading SLSsteam…")
        self.assertEqual(state["detail"], "[*] Downloading SLSsteam (64-bit client), release v20261112130346...")
        self.assertIsNone(state["percent"])
        note_output_line(state, "########                                  21.4%")
        self.assertEqual(state["progress"], "Downloading SLSsteam…")
        self.assertEqual(state["percent"], 21.4)
        note_output_line(state, "######################################## 100.0%")
        self.assertEqual(state["percent"], 100.0)
        # a line inside the phase: logged as detail, the label and bar untouched
        note_output_line(state, "\x1b[0;32m[+]\x1b[0m Deployed /home/deck/.local/share/SLSsteam/x86_64/SLSsteam.so (64-bit client)")
        self.assertEqual(state["progress"], "Downloading SLSsteam…")
        self.assertEqual(state["percent"], 100.0)
        self.assertTrue(state["detail"].startswith("[+] Deployed"))
        # the next phase clears the percent (the bar goes back to indeterminate)
        note_output_line(state, "[*] Downloading CloudRedirect...")
        self.assertEqual((state["phase"], state["progress"], state["percent"]),
                         ("cloudredirect", "Downloading CloudRedirect…", None))

    def test_every_phase_of_a_full_run_in_order(self):
        script = [
            "[*] Installing lumalinux unlock stack (self-contained, wrapper injection)...",
            "[*] SLSsteam release: v20261112130346",
            "[*] Downloading SLSsteam (64-bit client), release v20261112130346...",
            "[+] Seeded /home/deck/.config/SLSsteam/config.yaml (default)",
            "[*] Downloading CloudRedirect...",
            "[*] Installing CloudRedirect app (flatpak bundle; may pull the KDE runtime)...",
            "[*] Downloading netsock...",
            "[*] Downloading lumalinux...",
            "[*] Runtime tools from v0.22.3 (same ref as the .so)",
            "[+] Guardian installed (watches launcher dirs + 5-min reconcile).",
            "[+] Game Mode injection installed (steam-launcher.service drop-in, via fail-safe).",
        ]
        state = {"progress": "", "percent": None, "phase": None, "detail": ""}
        seen = []
        for line in script:
            note_output_line(state, line)
            if not seen or seen[-1] != state["progress"]:
                seen.append(state["progress"])
        self.assertEqual(seen, ["Preparing…", "Downloading SLSsteam…", "Downloading CloudRedirect…",
                                "Installing CloudRedirect app", "Downloading netsock…", "Downloading lumalinux…",
                                "Installing tools…", "Setting up Game Mode…"])
        set_phase(state, "done")
        self.assertEqual((state["phase"], state["progress"], state["percent"]), ("done", "Done", None))

    def test_blank_and_odd_lines_do_not_disturb_the_state(self):
        state = {"progress": "Downloading SLSsteam…", "percent": 50.0, "phase": "slssteam", "detail": ""}
        note_output_line(state, "   ")
        self.assertEqual(state["progress"], "Downloading SLSsteam…")
        self.assertEqual(state["percent"], 50.0)
        note_output_line(state, "100% not a bar")      # a percent inside prose is not a bar, not a phase
        self.assertEqual(state["progress"], "Downloading SLSsteam…")
        self.assertEqual(state["percent"], 50.0)
        self.assertEqual(state["detail"], "100% not a bar")
        self.assertIsNone(phase_for_line("[+] Deployed something"))


if __name__ == "__main__":
    unittest.main()

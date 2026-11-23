"""setup.sh output as the QAM sees it during Quick Install: the reader splits
on carriage returns (curl's --progress-bar never prints a newline until the
download ends, which left the panel frozen on the step text; a user's report,
2026-11-21), a bar line becomes a percent, any other line is the step text."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from installer import note_output_line, split_output  # noqa: E402


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

    def test_bar_line_is_a_percent_and_keeps_the_step_text(self):
        state = {"progress": "", "percent": None}
        note_output_line(state, "[*] Downloading SLSsteam (64-bit), release v20261112130346...")
        assert state["progress"].startswith("[*] Downloading SLSsteam")
        assert state["percent"] is None
        note_output_line(state, "########                                  21.4%")
        assert state["progress"].startswith("[*] Downloading SLSsteam")
        assert state["percent"] == 21.4
        note_output_line(state, "######################################## 100.0%")
        assert state["percent"] == 100.0
        # the next step clears the percent (the bar goes back to indeterminate)
        note_output_line(state, "[+] Deployed SLSsteam.so")
        assert state["progress"] == "[+] Deployed SLSsteam.so"
        assert state["percent"] is None

    def test_blank_and_odd_lines_do_not_disturb_the_state(self):
        state = {"progress": "step", "percent": 50.0}
        note_output_line(state, "   ")
        assert state == {"progress": "step", "percent": 50.0}
        note_output_line(state, "100% not a bar")      # a percent inside prose is text
        assert state["progress"] == "100% not a bar" and state["percent"] is None


if __name__ == "__main__":
    unittest.main()

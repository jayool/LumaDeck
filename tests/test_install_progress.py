"""The one bar of a setup.sh run (backend/install_progress.py): phases in the
script's real order with byte-based weights, curl's and flatpak's percentages
as the real progress inside a phase, a short capped time fill where nothing
reports, step N of M, never backwards, Done = 100. The lines are the ones a
real Quick Install printed (codespace, 2026-11-23) and flatpak's output on a
terminal (same day)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import install_progress as ip  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def tracker():
    c = Clock()
    tr = ip.InstallProgress(now=c)
    return tr, c


class PhaseTests(unittest.TestCase):
    def test_real_order_and_step_numbers(self):
        tr, c = tracker()
        tr.enter("preparing")
        self.assertEqual((tr.snapshot()["step"], tr.snapshot()["stepTotal"]), (1, 9))
        seen = []
        for line in [
            "\x1b[0;36m[*]\x1b[0m Installing lumalinux unlock stack (self-contained, wrapper injection)...",
            "[*] SLSsteam release: 20261112130346",
            "[*] Downloading SLSsteam (latest), release 20261112130346...",
            "[+] Seeded /home/deck/.config/SLSsteam/config.yaml (default)",
            "[*] Downloading CloudRedirect...",
            "[*] Installing CloudRedirect app (flatpak bundle; may pull the KDE runtime)...",
            "[*] Downloading netsock...",
            "[*] Downloading lumalinux...",
            "[*] Runtime tools from v0.22.9 (same ref as the .so)",
            "[*] Installing .NET 9 runtime (Steamless needs it)...",
            "[*] Writing injection wrapper at /home/deck/.local/share/SLSsteam/path/steam...",
            "[!] No systemd --user session — guardian not installed (the wrapper re-asserts on each launch instead).",
        ]:
            tr.feed(line)
            s = tr.snapshot()
            if not seen or seen[-1] != s["phase"]:
                seen.append(s["phase"])
        self.assertEqual(seen, list(ip.PHASE_IDS))
        self.assertEqual(tr.snapshot()["step"], 9)
        self.assertTrue(tr.detail.startswith("[!] No systemd"))      # colour codes gone, detail kept
        tr.enter("done")
        self.assertEqual((tr.snapshot()["overall"], tr.snapshot()["progress"]), (100.0, "Done"))

    def test_never_backwards_and_a_skipped_phase_jumps_forward(self):
        tr, c = tracker()
        tr.enter("preparing")
        tr.feed("[*] Downloading lumalinux...")
        tr.feed("[*] Downloading SLSsteam (32-bit), release 20261106120254...")   # a late repeat: ignored
        self.assertEqual(tr.snapshot()["phase"], "lumalinux")
        tr.feed("[+] .NET 9 runtime already present.")                           # no dotnet phase this run
        tr.feed("[*] Writing injection wrapper at /x/steam...")
        s = tr.snapshot()
        self.assertEqual((s["phase"], s["step"]), ("gamemode", 9))
        self.assertGreaterEqual(s["overall"], 98.0)

    def test_weights_sum_and_offsets(self):
        self.assertEqual(sum(p[2] for p in ip.PHASES), 100)
        self.assertEqual(ip._OFFSET["cloudredirect_app"], 9)
        self.assertEqual(ip._OFFSET["netsock"], 89)


class PercentTests(unittest.TestCase):
    def test_curl_bar_fills_the_phase(self):
        tr, c = tracker()
        tr.enter("preparing")
        tr.feed("[*] Downloading SLSsteam (latest), release 20261112130346...")
        self.assertIsNone(tr.snapshot()["percent"])
        tr.feed("##############                                   21.4%")
        s = tr.snapshot()
        self.assertEqual(s["percent"], 21.4)
        self.assertAlmostEqual(s["overall"], 5 + 2 * 0.214, places=1)
        tr.feed("######################################## 100.0%")
        self.assertEqual(tr.snapshot()["overall"], 7.0)
        tr.feed("[*] Downloading CloudRedirect...")                  # next phase: percent cleared, bar at its start
        s = tr.snapshot()
        self.assertEqual((s["phase"], s["percent"], s["overall"]), ("cloudredirect", None, 7.0))

    def test_flatpak_on_a_terminal_weighted_by_the_plan_table(self):
        tr, c = tracker()
        tr.enter("preparing")
        tr.feed("[*] Installing CloudRedirect app (flatpak bundle; may pull the KDE runtime)...")
        for row in [
            "Looking for matches…",
            "        ID                              Branch          Op          Remote          Download",
            " 1.     org.kde.KStyle.Adwaita          6.10            i           flathub         < 8.6 MB",
            " 2.     org.kde.Platform                6.10            i           flathub         < 392.1 MB",
        ]:
            tr.feed(row)
        self.assertEqual(tr._fp_sizes, {1: 8.6, 2: 392.1})
        tr.feed("Installing 1/2…                        0%  0 bytes/s")
        self.assertAlmostEqual(tr.snapshot()["percent"], 0.0, places=1)
        tr.feed("Installing 1/2… ████████████████████ 100%")
        self.assertAlmostEqual(tr.snapshot()["percent"], 100 * 8.6 / 400.7, places=1)
        tr.feed("Installing 2/2… ██████████           50%  12.4 MB/s  00:15")
        s = tr.snapshot()
        self.assertAlmostEqual(s["percent"], 100 * (8.6 + 196.05) / 400.7, places=1)
        self.assertAlmostEqual(s["overall"], 9 + 80 * s["percent"] / 100, places=1)
        # the single-ref form flatpak prints for one ref
        tr2, _ = tracker()
        tr2.enter("cloudredirect_app")
        tr2.feed("Installing… ████████████████████ 100%")
        self.assertEqual(tr2.snapshot()["percent"], 100.0)

    def test_flatpak_without_a_terminal_counts_refs(self):
        tr, c = tracker()
        tr.enter("cloudredirect_app")
        for ref in ["Installing runtime/org.freedesktop.Platform.GL.default/x86_64/25.08",
                    "Installing runtime/org.kde.Platform/x86_64/6.10",
                    "Installing app/org.cloudredirect.CloudRedirect/x86_64/master"]:
            tr.feed(ref)
        s = tr.snapshot()
        self.assertAlmostEqual(s["percent"], 100 * 2 / 3, places=1)   # third of three begun
        self.assertEqual(s["phase"], "cloudredirect_app")
        self.assertTrue(tr.detail.startswith("[*]") or tr.detail == "")    # the ref lines are not "detail"


class NeverBackwardsTests(unittest.TestCase):
    def test_bundle_curl_bar_in_the_app_phase_is_ignored(self):
        # the Quick Install video (codespace 2026-11-23): the 3 MB bundle's curl bar
        # read as the phase sent the bar to 89 % and flatpak's start pulled it back to 9 %
        tr, c = tracker()
        tr.enter("preparing")
        tr.feed("[*] Installing CloudRedirect app (flatpak bundle; may pull the KDE runtime)...")
        tr.feed("######################################## 100.0%")
        self.assertIsNone(tr.percent)
        self.assertLess(tr.snapshot()["overall"], 10)
        tr.feed("Installing runtime/org.freedesktop.Platform.GL.default/x86_64/25.08")
        self.assertLess(tr.snapshot()["overall"], 10)

    def test_readings_inside_a_phase_only_go_up(self):
        tr, c = tracker()
        tr.enter("preparing")
        tr.feed("[*] Downloading SLSsteam (latest), release 1...")
        tr.feed("######################################## 100.0%")        # the 64-bit archive
        tr.feed("[+] Deployed /x/x86_64/SLSsteam.so (64-bit client, latest)")
        tr.feed("#####                                    12.0%")        # the 32-bit archive begins
        self.assertEqual(tr.percent, 100.0)
        # and the time fill never shows more than a later real reading takes back
        tr2, c2 = tracker()
        tr2.enter("cloudredirect_app")
        c2.t += 5
        shown = tr2.snapshot()["overall"]
        tr2.feed("Installing runtime/org.kde.Platform/x86_64/6.10")      # flatpak's first ref: 0 %
        self.assertGreaterEqual(tr2.snapshot()["overall"], shown)

    def test_whole_fake_run_is_monotonic(self):
        import subprocess
        out = subprocess.run(["bash", os.path.join(os.path.dirname(__file__), "..", "backend", "dev_fake_setup.sh")],
                             capture_output=True, env={**os.environ, "LUMADECK_FAKE_SETUP_FAST": "1"}).stdout
        tr, c = tracker()
        tr.enter("preparing")
        last = 0.0
        for line in out.decode("utf-8", "replace").replace("\r", "\n").split("\n"):
            tr.feed(line)
            now = tr.snapshot()["overall"]
            self.assertGreaterEqual(now, last, line)
            last = now
        tr.enter("done")
        self.assertEqual(tr.snapshot()["overall"], 100.0)


class TimeFillTests(unittest.TestCase):
    def test_silent_phase_moves_with_time_and_never_fills(self):
        tr, c = tracker()
        tr.enter("preparing")                         # expected 8 s, weight 5
        self.assertEqual(tr.snapshot()["overall"], 0.0)
        c.t += 4
        mid = tr.snapshot()["overall"]
        self.assertTrue(0 < mid < 5, mid)
        c.t += 60
        late = tr.snapshot()["overall"]
        self.assertGreater(late, mid)
        self.assertLessEqual(late, 5 * ip.TIME_FILL_CAP)
        tr.feed("[*] Downloading SLSsteam (latest), release 1...")
        self.assertEqual(tr.snapshot()["overall"], 5.0)   # the next phase starts at its offset

    def test_time_fill_shape(self):
        self.assertEqual(ip.time_fill(0, 8), 0.0)
        self.assertAlmostEqual(ip.time_fill(8, 8), 1 - 1 / 2.718281828, places=3)
        self.assertEqual(ip.time_fill(1000, 8), ip.TIME_FILL_CAP)


if __name__ == "__main__":
    unittest.main()

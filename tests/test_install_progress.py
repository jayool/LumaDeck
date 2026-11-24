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


class FlatpakLiveTableTests(unittest.TestCase):
    # the rows a real Quick Install printed through the pty (codespace 2026-11-23 14:40),
    # as they reached the log: several rows in one piece of text, redrawn in place
    GIANT = ("1. [ ] org.freedesktop.Platform.GL.default   25.08       i  flathub < 147.8 MB "
             "2. [ ] org.freedesktop.Platform.GL.default   25.08-extra i  flathub < 147.8 MB "
             "3. [ ] org.freedesktop.Platform.codecs-extra 25.08-extra i  flathub  < 14.6 MB "
             "4. [ ] org.kde.Platform.Locale               6.10        i  flathub < 401.9 MB (partial) "
             "5. [ ] org.kde.Platform                      6.10        i  flathub < 392.1 MB "
             "1. [|] org.freedesktop.Platform.GL.default   25.08       i  flathub < 147.8 MBInstalling 1/5… "
             "1. [/] org.freedesktop.Platform.GL.default   25.08       i  flathub     1.0 kB / 147.8 MB")

    def test_bytes_over_totals_with_partial_rows_left_out(self):
        tr, c = tracker()
        tr.enter("cloudredirect_app")
        tr.feed(self.GIANT)
        GL, GLX, CODECS, LOCALE, PLATFORM = (("org.freedesktop.Platform.GL.default", "25.08"),
                                             ("org.freedesktop.Platform.GL.default", "25.08-extra"),
                                             ("org.freedesktop.Platform.codecs-extra", "25.08-extra"),
                                             ("org.kde.Platform.Locale", "6.10"), ("org.kde.Platform", "6.10"))
        self.assertEqual(set(tr._fp_live), {GL, GLX, CODECS, PLATFORM})    # the (partial) Locale has no total yet
        self.assertEqual(tr._fp_partial, {LOCALE})
        self.assertAlmostEqual(tr._fp_live[GL][0], 1.0 / 1024, places=4)
        tr.feed("1. [/] org.freedesktop.Platform.GL.default   25.08       i  flathub    73.9 MB / 147.8 MB")
        whole = 147.8 * 2 + 14.6 + 392.1
        self.assertAlmostEqual(tr.snapshot()["percent"], 100 * 0.5 * 73.9 / whole, places=1)   # the download half
        # the partial Locale in flight: flatpak shows the whole runtime's size
        # (recording 2026-11-24: the total jumped 702 → 1104 MB there); it
        # weighs its bytes, the total barely moves
        tr.feed("4. [/] org.kde.Platform.Locale               6.10        i  flathub   0.5 MB / 401.9 MB")
        self.assertEqual(tr._fp_live[LOCALE][:2], [0.5, 0.5])
        self.assertEqual(tr.snapshot()["mbTotal"], round(whole + 0.5))
        tr.feed("4. [✓] org.kde.Platform.Locale               6.10        i  flathub   401.9 MB")
        self.assertEqual(tr._fp_live[LOCALE][:2], [0.5, 0.5])
        self.assertEqual(tr.snapshot()["mbTotal"], round(whole + 0.5))
        tr.feed("5. [/] org.kde.Platform                      6.10        i  flathub   196.0 MB / 392.1 MB")
        p1 = tr.snapshot()["percent"]
        tr.feed("5. [/] org.kde.Platform                      6.10        i  flathub   190.0 MB / 392.1 MB")  # a stale redraw
        self.assertEqual(tr.snapshot()["percent"], p1)
        tr.feed("5. [✓] org.kde.Platform                      6.10        i  flathub   392.1 MB")
        self.assertGreater(tr.snapshot()["percent"], p1)
        self.assertIsNone(tr._fp_ref_started)                              # no ref time fill competes with real bytes

    def test_the_bar_follows_the_bytes_once_the_live_table_exists(self):
        # the 30 s at 57 % (recording 2026-11-24): the plan table and the
        # "Installing N/M… pct" line, in another row order, had sent the
        # phase ahead of the bytes; now only the live rows count
        tr, c = tracker()
        tr.enter("cloudredirect_app")
        tr.feed(" 1.     org.kde.Platform                6.10            i           flathub         < 392.1 MB")
        tr.feed(" 2.     org.freedesktop.Platform.GL.default 25.08        i           flathub         < 147.8 MB")
        tr.feed(self.GIANT)
        tr.feed("1. [/] org.freedesktop.Platform.GL.default   25.08       i  flathub    40.0 MB / 147.8 MB")
        p0 = tr.snapshot()["percent"]
        tr.feed("Installing 2/5… ████████████ 95%")                         # would be (392 + 0.95 × 148) / 702
        self.assertEqual(tr.snapshot()["percent"], p0)
        tr.feed("1. [/] org.freedesktop.Platform.GL.default   25.08       i  flathub    80.0 MB / 147.8 MB")
        self.assertGreater(tr.snapshot()["percent"], p0)
        tr.feed("[*] Downloading netsock...")                                 # phase lines still count
        self.assertEqual(tr.phase, "netsock")

    def test_the_deploy_half_moves_by_time_until_the_check(self):
        # the 27 s plateau while flatpak wrote org.kde.Platform to disk (recording 2026-11-23)
        tr, c = tracker()
        tr.enter("cloudredirect_app")
        tr.feed(" 1.     org.kde.Platform                6.10            i           flathub         < 392.1 MB")
        tr.feed("1. [ ] org.kde.Platform 6.10 i flathub < 392.1 MB")
        tr.feed("1. [/] org.kde.Platform 6.10 i flathub 392.1 MB / 392.1 MB")        # download complete
        s0 = tr.snapshot()
        self.assertAlmostEqual(s0["percent"], 50.0, places=1)                       # the download half, whole
        self.assertTrue(s0["writing"])
        c.t += 10
        s1 = tr.snapshot()
        self.assertGreater(s1["percent"], 50.0)
        self.assertTrue(s1["writing"])
        c.t += 60
        s2 = tr.snapshot()
        self.assertGreater(s2["percent"], s1["percent"])
        self.assertLessEqual(s2["percent"], 50 + 50 * ip.TIME_FILL_CAP + 0.1)       # never the ✓'s 100 by time
        tr.feed("1. [✓] org.kde.Platform 6.10 i flathub 392.1 MB")
        s3 = tr.snapshot()
        self.assertAlmostEqual(s3["percent"], 100.0, places=1)
        self.assertFalse(s3["writing"])

    def test_bytes_for_the_row_text(self):
        tr, c = tracker()
        tr.enter("cloudredirect_app")
        self.assertNotIn("mbTotal", tr.snapshot())
        tr.feed(self.GIANT)
        tr.feed("1. [/] org.freedesktop.Platform.GL.default   25.08       i  flathub    73.9 MB / 147.8 MB")
        s = tr.snapshot()
        self.assertEqual((s["mbDone"], s["mbTotal"], s["writing"]), (74, 702, False))
        tr.feed("[*] Downloading netsock...")
        self.assertNotIn("mbTotal", tr.snapshot())

    def test_the_second_table_the_bundle_cannot_pull_the_bar_back(self):
        tr, c = tracker()
        tr.enter("cloudredirect_app")
        tr.feed(self.GIANT)
        tr.feed("5. [✓] org.kde.Platform                      6.10        i  flathub   392.1 MB / 392.1 MB")
        for r in (1, 2, 3):
            tr.feed("%d. [✓] x y i flathub 147.8 MB / 147.8 MB" % r)
        high = tr.snapshot()["overall"]
        tr.feed("1. [ ] org.cloudredirect.CloudRedirect master i  cloudredirect-origin 0 bytes "
                "1. [|] org.cloudredirect.CloudRedirect master i  cloudredirect-origin 0 bytesInstalling… "
                "1. [✓] org.cloudredirect.CloudRedirect master i  cloudredirect-origin 0 bytesInstalling…bwrap: setuid use of bubblewrap is not supported")
        self.assertGreaterEqual(tr.snapshot()["overall"], high)


class AppTextTests(unittest.TestCase):
    """The app phase's sub-phase and filler lines (snapshot()["sub"],
    ["filler"]): the text the QAM shows over the one bar during the 80 %
    of the run that the CloudRedirect app is."""
    PLAN = " 1.     org.kde.Platform                6.10            i           flathub         < 392.1 MB"
    LIVE = "1. [/] org.kde.Platform 6.10 i flathub %s MB / 392.1 MB"
    BUNDLE = ("1. [ ] org.cloudredirect.CloudRedirect master i  cloudredirect-origin 0 bytes"
              "1. [✓] org.cloudredirect.CloudRedirect master i  cloudredirect-origin 0 bytes")

    def test_sub_phases_in_order_and_never_back(self):
        tr, c = tracker()
        tr.feed("[*] Installing CloudRedirect app (flatpak bundle; may pull the KDE runtime)...")
        self.assertEqual(tr.snapshot()["sub"], None)                   # the phase label itself
        tr.feed("######                                                  12.0%")   # the bundle's curl bar
        self.assertEqual(tr.snapshot()["sub"], "app_download")
        tr.feed(self.PLAN)
        self.assertEqual(tr.snapshot()["sub"], "runtime_download")
        tr.feed(self.LIVE % "10.0")
        self.assertEqual(tr.snapshot()["sub"], "runtime_download")
        tr.feed(self.BUNDLE)
        self.assertEqual(tr.snapshot()["sub"], "app_install")
        tr.feed(self.LIVE % "392.1")                                   # a late runtime redraw
        self.assertEqual(tr.snapshot()["sub"], "app_install")
        tr.feed("[*] Downloading netsock...")
        self.assertEqual(tr.snapshot()["sub"], None)                   # only the app phase has sub-phases

    def test_curl_in_other_phases_has_no_sub(self):
        tr, c = tracker()
        tr.feed("[*] Downloading SLSsteam (latest), release 20261112130346...")
        tr.feed("######                                                  12.0%")
        self.assertEqual(tr.snapshot()["sub"], None)

    def test_fillers_after_five_quiet_seconds_then_one_every_five_and_the_last_stays(self):
        tr, c = tracker()
        tr.feed("[*] Installing CloudRedirect app (flatpak bundle; may pull the KDE runtime)...")
        tr.feed(self.PLAN)
        tr.feed(self.LIVE % "392.1")                                    # download complete, flatpak writes in silence
        self.assertIsNone(tr.snapshot()["filler"])
        c.t += 4.9
        self.assertIsNone(tr.snapshot()["filler"])
        c.t += 0.1
        self.assertEqual(tr.snapshot()["filler"], 0)
        c.t += 5
        self.assertEqual(tr.snapshot()["filler"], 1)
        c.t += 5 * (ip.FILLER_COUNT - 2)
        self.assertEqual(tr.snapshot()["filler"], ip.FILLER_COUNT - 1)
        c.t += 300
        self.assertEqual(tr.snapshot()["filler"], ip.FILLER_COUNT - 1)  # the last one stays, no wrap
        tr.feed("1. [✓] org.kde.Platform 6.10 i flathub 392.1 MB")        # nothing visible changed (bytes the same)
        tr.feed(self.BUNDLE)                                            # a real change: the bundle's table
        self.assertIsNone(tr.snapshot()["filler"])
        self.assertEqual(tr.snapshot()["sub"], "app_install")

    def test_moving_bytes_keep_the_fillers_away(self):
        tr, c = tracker()
        tr.feed("[*] Installing CloudRedirect app (flatpak bundle; may pull the KDE runtime)...")
        tr.feed(self.PLAN)
        for i in range(1, 8):
            c.t += 4
            tr.feed(self.LIVE % ("%.1f" % (i * 10.0)))
            self.assertIsNone(tr.snapshot()["filler"])
        c.t += 6
        self.assertEqual(tr.snapshot()["filler"], 0)                    # the same bytes for 6 s
        c.t += 1
        tr.feed(self.LIVE % "90.0")
        self.assertIsNone(tr.snapshot()["filler"])                      # bytes again: back to the real text

    def test_no_fillers_outside_the_app_phase(self):
        tr, c = tracker()
        tr.feed("[*] Installing lumalinux unlock stack (self-contained, wrapper injection)...")
        c.t += 60
        self.assertIsNone(tr.snapshot()["filler"])
        tr.feed("[*] Installing .NET 9 runtime...")
        c.t += 60
        self.assertIsNone(tr.snapshot()["filler"])


class RefTimeFillTests(unittest.TestCase):
    def test_a_silent_ref_moves_by_time_and_stays_short_of_the_next(self):
        # the 29 s plateau at 73 % (org.kde.Platform, ref 6 of 7, no terminal)
        tr, c = tracker()
        tr.enter("cloudredirect_app")
        for ref in ["Installing runtime/org.freedesktop.Platform.GL.default/x86_64/25.08",
                    "Installing runtime/org.freedesktop.Platform.GL.default/x86_64/25.08-extra",
                    "Installing runtime/org.freedesktop.Platform.codecs-extra/x86_64/25.08-extra",
                    "Installing runtime/org.kde.KStyle.Adwaita/x86_64/6.10",
                    "Installing runtime/org.kde.Platform.Locale/x86_64/6.10",
                    "Installing runtime/org.kde.Platform/x86_64/6.10"]:
            tr.feed(ref)
        start = tr.snapshot()["overall"]
        self.assertAlmostEqual(start, 9 + 80 * 5 / 6, places=1)     # 6 refs seen: 5 complete
        c.t += 10
        mid = tr.snapshot()["overall"]
        self.assertGreater(mid, start)
        c.t += 60
        late = tr.snapshot()["overall"]
        self.assertGreater(late, mid)
        self.assertLess(late, 9 + 80 * 6 / 6)                         # never past the ref's end
        tr.feed("Installing app/org.cloudredirect.CloudRedirect/x86_64/master")
        self.assertGreaterEqual(tr.snapshot()["overall"], late)         # the next ref: forward only

    def test_a_ref_with_a_real_percent_does_not_get_the_time_fill(self):
        tr, c = tracker()
        tr.enter("cloudredirect_app")
        tr.feed("Installing 1/2… ████                 20%  5.2 MB/s")
        p = tr.snapshot()["overall"]
        c.t += 30
        self.assertEqual(tr.snapshot()["overall"], p)


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

"""Phase 2 — the gamescope crash-loop repair vs. the SLSsteam/lumalinux injection
(issue #31), with a FAITHFUL reproduction of CachyOS's do_repair().

What is verified (from source, CachyOS/gamescope-session @cachyos):
  * CachyOS Handheld's gamescope-session-cachyos is a *Valve/SteamOS* fork. Its
    `usr/lib/steamos/steam-short-session-tracker` uses `/tmp/steamos-short-session
    -tracker` (the SAME path as SteamOS) and, after `short_session_count_before_
    reset=3` short (<60s) sessions, its `do_repair()` re-extracts the vanilla
    Steam bootstrap OVER ~/.local/share/Steam — clobbering the lumalinux/SLSsteam
    steam.sh LD_PRELOAD block — UNLESS ~/.config/inhibit-short-session-tracker
    exists ("Auto-repair disabled by config").

What this test does and does NOT cover — read this before trusting it:
  * COVERS: that do_repair() genuinely wipes the steam.sh injection, and pins the
    two mechanisms that stop it — the /tmp/*-short-session-tracker reset, and
    CachyOS/SteamOS's own ~/.config/inhibit-short-session-tracker (which LumaDeck
    documents but does NOT set; see test_native_inhibit_would_prevent_repair).
    This is a real reproduction of the tracker->repair->clobber mechanism (the
    "black screen returning to Game Mode" tail of #31, and any game-mode path).
  * DOES NOT COVER: #31's *primary* reported symptom — "when steam restarted in
    DESKTOP mode, nothing was injected + stuck loading". In Plasma/desktop the
    gamescope steam-launcher.service (which drives the tracker) is NOT running,
    so do_repair() is not the desktop-mode mechanism. That symptom points at the
    Steam client re-extracting steam.sh during the downgrade's own restarts with
    the re-patch not settling, and its root cause is UNCONFIRMED (the reporter
    had no logs). It is device-gated, not reproducible here. Do not read a green
    run of this file as "issue #31 is fixed".

    python -m unittest discover -s tests
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import installer  # noqa: E402


# A minimal fake headcrab.sh carrying a literal instance of every _HEADCRAB_PATCHES
# anchor, so _patch_headcrab_script applies cleanly (it raises if one is missing).
FAKE_HEADCRAB = (
    "#!/usr/bin/env bash\n"
    "killall steam | true\n"
    "wheresteam -exitsteam\n"
    "wheresteam -clearbeta steam://exit\n"
    "wheresteam -clearbeta -exitsteam\n"
    "cp -f $InstallDir/SLSsteam.so $SLSsteamInstallDir/\n"
    'wget -O cloud_redirect.so "$CloudRedirectLib" &> /dev/null\n'
    'grep -F "DisableCloud: no" config.yaml &> /dev/null\n'
)

# A faithful, sandbox-parameterised port of CachyOS's steam-short-session-tracker
# do_repair()/handle_started() (verified: CachyOS/gamescope-session @cachyos
# usr/lib/steamos/steam-short-session-tracker). Paths are taken from env instead
# of the hardcoded /tmp and /usr/lib/steam so the test can run in a sandbox; the
# LOGIC (count>=3 -> re-extract bootstrap over Steam, skip if inhibit file) is
# byte-for-byte the same shape as upstream.
CACHYOS_TRACKER = r"""#!/bin/bash
short_session_tracker_file="$TRACKER_FILE"
short_session_count_before_reset=3

do_repair() {
  mkdir -p "$STEAM_DIR"
  # restore clean copy of binaries from RO partition (clobbers the injected steam.sh)
  tar xf "$BOOTSTRAP_TAR" -C "$STEAM_DIR"
  rm -f "$short_session_tracker_file"
}

handle_started() {
  short_session_count=$(< "$short_session_tracker_file" wc -l)
  if [[ "$short_session_count" -ge "$short_session_count_before_reset" ]]; then
    if [ -f "$HOME/.config/inhibit-short-session-tracker" ]; then
      echo >&2 "Auto-repair disabled by config"
      return
    fi
    do_repair
  fi
}

handle_started
"""

_MARKER = "# >>> lumalinux launcher patch >>>"


class TestCrashLoopTrackerReset(unittest.TestCase):
    def test_reset_covers_the_whole_tracker_family(self):
        # Must clear /tmp/*-short-session-tracker (steamos-, chimeraos-, any
        # rename), NOT just the SteamOS-only path the pre-#31 code used.
        self.assertIn("/tmp/*-short-session-tracker", installer._SESSION_TRACKER_RESET)
        self.assertIn("rm -f /tmp/*-short-session-tracker", installer._SESSION_TRACKER_RESET)

    def test_reset_documents_the_verified_cachyos_lineage(self):
        # CachyOS is documented as the Valve/SteamOS fork (steamos- tracker),
        # NOT chimeraos — the earlier assumption this file used was wrong.
        reset = installer._SESSION_TRACKER_RESET
        self.assertIn("steamos-short-session-tracker", reset)
        self.assertIn("Valve/SteamOS", reset)
        self.assertIn("count_before_reset=3", reset)

    def test_gamemode_prepends_the_reset_after_the_shebang(self):
        out = installer._patch_headcrab_script(FAKE_HEADCRAB, gamemode=True)
        self.assertIn("rm -f /tmp/*-short-session-tracker", out)
        self.assertTrue(out.startswith("#!/usr/bin/env bash\n"))  # shebang stays line 1
        # kill/relaunch lines are no-op'd in Game Mode.
        self.assertNotIn("killall steam | true", out)

    def test_desktop_mode_omits_the_reset(self):
        # In the Desktop hand-off the kills are REQUIRED (to step the downgrade)
        # and gamescope isn't running, so no tracker reset is injected.
        out = installer._patch_headcrab_script(FAKE_HEADCRAB, gamemode=False)
        self.assertNotIn("short-session-tracker", out)
        # gamemode-only kill no-ops are skipped -> the kill line survives verbatim.
        self.assertIn("killall steam | true", out)


class TestDoRepairClobber(unittest.TestCase):
    """Drive the faithful CachyOS tracker: prove do_repair() wipes the injection,
    and pin that CachyOS's own inhibit file would stop it (a mechanism we
    document but deliberately don't wire)."""

    def _run(self, with_inhibit):
        import shutil
        d = tempfile.mkdtemp(prefix="ld-crashloop-")
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        home = os.path.join(d, "home")
        steam_dir = os.path.join(home, ".local/share/Steam")
        os.makedirs(steam_dir)
        steam_sh = os.path.join(steam_dir, "steam.sh")
        with open(steam_sh, "w") as fh:
            fh.write("#!/bin/sh\n" + _MARKER + "\nexport LD_PRELOAD=liblumalinux.so\n")
        boot_root = os.path.join(d, "boot")
        os.makedirs(boot_root)
        with open(os.path.join(boot_root, "steam.sh"), "w") as fh:
            fh.write("#!/bin/sh\n# vanilla\n")
        bootstrap_tar = os.path.join(d, "bootstrap.tar")
        subprocess.run(["tar", "cf", bootstrap_tar, "-C", boot_root, "steam.sh"], check=True)
        if with_inhibit:
            os.makedirs(os.path.join(home, ".config"))
            open(os.path.join(home, ".config", "inhibit-short-session-tracker"), "w").close()
        tracker = os.path.join(d, "tracker.sh")
        with open(tracker, "w") as fh:
            fh.write(CACHYOS_TRACKER)
        tracker_file = os.path.join(d, "steamos-short-session-tracker")
        with open(tracker_file, "w") as fh:
            fh.write("frog\nfrog\nfrog\n")  # 3 short sessions -> repair threshold
        env = {**os.environ, "HOME": home, "TRACKER_FILE": tracker_file,
               "STEAM_DIR": steam_dir, "BOOTSTRAP_TAR": bootstrap_tar}
        subprocess.run(["bash", tracker], env=env, check=True)
        with open(steam_sh) as fh:
            return _MARKER in fh.read()

    def test_repair_wipes_injection_when_not_inhibited(self):
        # Reproduces the clobber: 3 short sessions -> do_repair -> injection gone.
        self.assertFalse(self._run(with_inhibit=False))

    def test_native_inhibit_would_prevent_repair(self):
        # Documents CachyOS/SteamOS's OWN inhibit mechanism: with
        # ~/.config/inhibit-short-session-tracker present, do_repair() is skipped.
        # LumaDeck deliberately does NOT set this file (redundant given the
        # desktop-routing protection, and setting it unconditionally would alter
        # SteamOS behaviour) — this test just pins the upstream behaviour so the
        # decision stays informed if we ever revisit it.
        self.assertTrue(self._run(with_inhibit=True))


if __name__ == "__main__":
    unittest.main()

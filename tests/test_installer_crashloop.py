"""Phase 2 — the gamescope crash-loop tracker reset (issue #31).

LumaDeck neutralises the gamescope-session short-session counter so the Steam
downgrade's restarts can't trip `short_session_recover` (which, on the ChimeraOS
lineage CachyOS/Bazzite use, re-extracts the Steam bootstrap over the install —
clobbering the lumalinux/SLSsteam steam.sh patch — and drops to desktop). The
tracker file is named per lineage (steamos- vs chimeraos-), so the reset must
clear the whole /tmp/*-short-session-tracker family, not just the SteamOS one.

    python -m unittest discover -s tests
"""
import os
import sys
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


class TestCrashLoopTrackerReset(unittest.TestCase):
    def test_reset_covers_the_whole_tracker_family(self):
        # Must clear /tmp/*-short-session-tracker (steamos-, chimeraos-, any
        # rename), NOT just the SteamOS-only path the pre-#31 code used.
        self.assertIn("/tmp/*-short-session-tracker", installer._SESSION_TRACKER_RESET)
        self.assertIn("rm -f /tmp/*-short-session-tracker", installer._SESSION_TRACKER_RESET)
        # Documents the ChimeraOS/CachyOS lineage explicitly.
        self.assertIn("chimeraos-short-session-tracker", installer._SESSION_TRACKER_RESET)

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


if __name__ == "__main__":
    unittest.main()

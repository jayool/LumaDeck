"""Phase 2 — the desktop session-select arg differs by lineage.

`steamos-session-select` reaches the desktop session with 'plasma' on SteamOS
(HoloISO) AND on CachyOS Handheld — its gamescope-session-cachyos is a
Valve/SteamOS fork (verified against CachyOS/gamescope-session @cachyos:
usr/bin/steamos-session-select accepts only plasma/gamescope/persistent/oneshot,
NOT 'desktop'). The ChimeraOS gamescope-session-plus lineage (Bazzite) uses
'desktop'. desktop_handoff picks the right one, defaulting to the tested SteamOS
value ('plasma') for anything not positively a ChimeraOS lineage.

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import desktop_handoff as dh  # noqa: E402
import platform_info as p     # noqa: E402


class TestDesktopArgByLineage(unittest.TestCase):
    def test_steamos_uses_plasma(self):
        self.assertEqual(dh._desktop_arg_for("steamos"), "plasma")

    def test_cachyos_uses_plasma_valve_fork(self):
        # CachyOS Handheld's gamescope-session is a Valve/SteamOS fork; its
        # steamos-session-select has NO 'desktop' case. Verified from source.
        self.assertEqual(dh._desktop_arg_for("cachyos"), "plasma")

    def test_chimeraos_lineage_uses_desktop(self):
        self.assertEqual(dh._desktop_arg_for("bazzite"), "desktop")
        self.assertEqual(dh._desktop_arg_for("chimeraos"), "desktop")

    def test_unknown_defaults_to_plasma(self):
        # SteamOS-default: only switch to 'desktop' for a POSITIVELY known lineage.
        self.assertEqual(dh._desktop_arg_for("unknown"), "plasma")
        self.assertEqual(dh._desktop_arg_for(""), "plasma")

    def test_live_arg_is_valid_and_never_raises(self):
        arg = dh._desktop_session_arg()
        self.assertIn(arg, ("plasma", "desktop"))


class TestTerminalResolver(unittest.TestCase):
    """The hand-off must open in a terminal that actually exists — konsole is
    KDE-only and breaks the hand-off on GNOME-family distros (ChimeraOS,
    Bazzite-GNOME). _terminal_exec_prefix resolves a DE-agnostic one."""

    def _with_which(self, present):
        import shutil
        orig = shutil.which
        shutil.which = lambda n: ("/usr/bin/" + n) if n in present else None
        self.addCleanup(lambda: setattr(shutil, "which", orig))

    def test_konsole_first_on_kde(self):
        self._with_which({"konsole", "xterm"})
        self.assertEqual(dh._terminal_exec_prefix(), "konsole --hold -e")

    def test_falls_through_to_gnome_family(self):
        self._with_which({"gnome-terminal"})
        self.assertEqual(dh._terminal_exec_prefix(), "gnome-terminal --")
        self._with_which({"ptyxis"})
        self.assertEqual(dh._terminal_exec_prefix(), "ptyxis --")

    def test_none_when_no_terminal(self):
        self._with_which(set())
        self.assertIsNone(dh._terminal_exec_prefix())  # -> caller runs headless

    def test_konsole_is_tried_first(self):
        self.assertEqual(dh._TERMINALS[0][0], "konsole")


class TestGameModeArg(unittest.TestCase):
    def test_gamemode_arg_is_gamescope_and_used_in_the_payload(self):
        self.assertEqual(dh._GAMEMODE_ARG, "gamescope")
        self.assertIn("steamos-session-select gamescope", dh._REAL_PAYLOAD)


class TestSessionFamilyPublic(unittest.TestCase):
    def test_session_family_matches_pure_helper(self):
        # Public wrapper is consistent with the pure classifier on the live distro.
        self.assertEqual(p.session_family(), p._session_family(p._distro_id(p._read_os_release())))

    def test_pure_classifier(self):
        self.assertEqual(p._session_family("steamos"), "steamos")
        self.assertEqual(p._session_family("cachyos"), "cachyos")
        self.assertEqual(p._session_family("fedora"), "unknown")




class DowngradeTargetTests(unittest.TestCase):
    """LumaDeck decides the build downgrade.sh lands on (2026-11-19, both client
    lines): the newest build lumalinux's whitelist annotates for the running
    client's arch below the installed one that both the latest lumalinux
    release and the latest SLSsteam for that arch hook. The 64-bit client
    downgrades along its own steamrt64 line."""

    LL = """SafeModeHashes:
  20261119000000:
    # steam_version: 1791918634
    - 0d01ab4fe889f87314c8416d18a2152b130a93231bb19cd6f0ed2ebd7a7ab90a
    # steam_version: 1792618285
    - c770a8b13872fed128dd357eabc1d715260fadd9b16c627ae3395406e6ea37d4
    # steam_version: 1794266161
    # arch: steamrt64
    - 53bdabbbb63fff0146a459f1f40dc9208661f329810557c462404ba52318bf11
    # steam_version: 1794536281
    # arch: steamrt64
    - dab8df0daa27ffa6594ef5d6bc8cf707f37990220628f1f249fb30f4d88ade91
    # steam_version: 1795048523
    # arch: steamrt64
    - c6b5784ae84a7d63ae1d238045eab33c92eb947d4556de5328e51272973c113c
"""
    SLS = """SafeModeHashes:
  20261014151919:
    - 0d01ab4fe889f87314c8416d18a2152b130a93231bb19cd6f0ed2ebd7a7ab90a #ubuntu12_32
    - 53bdabbbb63fff0146a459f1f40dc9208661f329810557c462404ba52318bf11 #steamrt64
  20261112130346:
    - 53bdabbbb63fff0146a459f1f40dc9208661f329810557c462404ba52318bf11 #steamrt64
    - dab8df0daa27ffa6594ef5d6bc8cf707f37990220628f1f249fb30f4d88ade91 #steamrt64
"""

    def test_64bit_picks_the_newest_hooked_steamrt64_build_below_current(self):
        r = dh.pick_downgrade_target(self.LL, "20261119000000", self.SLS, 1795048523, "steamrt64")
        self.assertEqual(r["target"], 1794536281)
        self.assertEqual(r["hash"][:8], "dab8df0d")
        self.assertTrue(r["possible"])
        # Every hooked build below the installed one, newest first: the script
        # keeps the first one this install's branch served.
        self.assertEqual(r["candidates"], [1794536281, 1794266161])

    def test_64bit_skips_a_build_the_latest_slssteam_dropped(self):
        sls = self.SLS.replace("    - dab8df0daa27ffa6594ef5d6bc8cf707f37990220628f1f249fb30f4d88ade91 #steamrt64\n", "")
        r = dh.pick_downgrade_target(self.LL, "20261119000000", sls, 1795048523, "steamrt64")
        self.assertEqual(r["target"], 1794266161)
        self.assertTrue(r["possible"])

    def test_32bit_follows_its_own_line(self):
        import slssteam_version
        saved = slssteam_version.LAST_32BIT_TAG
        slssteam_version.LAST_32BIT_TAG = "20261014151919"
        try:
            r = dh.pick_downgrade_target(self.LL, "20261119000000", self.SLS, 1792618285, "ubuntu12_32")
        finally:
            slssteam_version.LAST_32BIT_TAG = saved
        self.assertEqual(r["target"], 1791918634)
        self.assertTrue(r["possible"])

    def test_nothing_below_current_is_not_possible(self):
        r = dh.pick_downgrade_target(self.LL, "20261119000000", self.SLS, 1794266161, "steamrt64")
        self.assertIs(r["possible"], False)
        self.assertIsNone(r["target"])

    def test_unknown_slssteam_support_is_unknown_not_refused(self):
        # A 64-bit hash SLSsteam's feed lists nowhere reads None (fail-open).
        sls = self.SLS.replace("dab8df0daa27ffa6594ef5d6bc8cf707f37990220628f1f249fb30f4d88ade91", "f" * 64)
        sls = sls.replace("53bdabbbb63fff0146a459f1f40dc9208661f329810557c462404ba52318bf11", "e" * 64)
        r = dh.pick_downgrade_target(self.LL, "20261119000000", sls, 1795048523, "steamrt64")
        self.assertIsNone(r["possible"])
        self.assertEqual(r["target"], 1794536281)

    def test_no_whitelist_is_unknown(self):
        r = dh.pick_downgrade_target(None, None, self.SLS, 1795048523, "steamrt64")
        self.assertIsNone(r["possible"])

    def test_payload_carries_build_and_line(self):
        pl = dh._real_payload(1794536281, "steamrt64")
        self.assertIn("| TARGET_VERSION=1794536281 CLIENT_LINE=steamrt64 bash", pl)
        pl = dh._real_payload(1794536281, "steamrt64", [1794536281, 1794266161])
        self.assertIn('| TARGET_VERSION=1794536281 TARGET_VERSIONS="1794536281 1794266161" CLIENT_LINE=steamrt64 bash', pl)
        self.assertIn("| bash", dh._real_payload())
        self.assertNotIn("TARGET_VERSION", dh._real_payload())


class TrackerBranchCheckTests(unittest.TestCase):
    """Before Fix in Desktop is offered, the candidates are checked against the
    tracker history of the install's own Steam branch, with the script's walk:
    newest first, stop at the build or at the first smaller one (2026-11-20;
    beta 1794266161 was relabelled 1794424036 on stable, and the Deck's
    64-bit files only exist in the tracker since 2026-11-12)."""

    def test_tracker_file_follows_branch_and_line(self):
        self.assertEqual(dh.tracker_file("steamrt64", "steamdeck_stable"), "steamdeck_stable_steamrt64")
        self.assertEqual(dh.tracker_file("steamrt64", "steamdeck_publicbeta"), "steamdeck_publicbeta_steamrt64")
        self.assertEqual(dh.tracker_file("ubuntu12", "steamdeck_stable"), "steamdeck_stable")
        self.assertEqual(dh.tracker_file("steamrt64", "publicbeta"), "steam_client_publicbeta_steamrt64")
        self.assertEqual(dh.tracker_file("steamrt64", ""), "steam_client_steamrt64")
        self.assertEqual(dh.tracker_file("ubuntu12", ""), "steam_client_ubuntu12")

    def test_served_on_branch_walks_like_the_script(self):
        # stable history: 300, 260, 200, 100 (260 is 250 relabelled)
        hist = [300, 260, None, 200, 100]
        self.assertEqual(dh.served_on_branch(hist, [250, 260, 200]), [260, 200])
        self.assertEqual(dh.served_on_branch(hist, [300]), [300])
        self.assertEqual(dh.served_on_branch(hist, [50]), [])
        self.assertEqual(dh.served_on_branch([], [250]), [])

    def _fake_client(self, history, api_down=False):
        """history: {sha: version|None} in newest-first order."""
        shas = list(history)

        class R:
            def __init__(self, code, text="", data=None):
                self.status_code, self.text, self._d = code, text, data
            def json(self): return self._d

        class C:
            calls = []
            async def get(self_, url, params=None, timeout=None, **k):
                C.calls.append(url)
                if url == dh._TRACKER_API:
                    if api_down: return R(503)
                    page, per = params["page"], params["per_page"]
                    return R(200, data=[{"sha": s} for s in shas[(page - 1) * per: page * per]])
                sha = url.split("/")[-3]
                v = history.get(sha)
                return R(200, '"steamrt64"\n{\n\t"version"\t\t"%s"\n}\n' % v) if v else R(200, "")
        return C()

    def test_served_candidates_keeps_only_what_the_branch_served(self):
        import asyncio
        c = self._fake_client({"a": 1794536281, "b": 1794424036, "c": None, "d": 1792618285})
        got = asyncio.run(dh.served_candidates("steamdeck_stable_steamrt64", [1794536281, 1794266161, 1792618285], c))
        self.assertEqual(got, [1794536281, 1792618285])
        # the walk stopped at the first version below the oldest candidate: 4 manifests read
        self.assertEqual(sum(1 for u in c.calls if "/ClientManifest/" in u), 4)

    def test_served_candidates_stops_early(self):
        import asyncio
        c = self._fake_client({"a": 400, "b": 300, "c": 200, "d": 100})
        self.assertEqual(asyncio.run(dh.served_candidates("f", [300], c)), [300])
        self.assertEqual(sum(1 for u in c.calls if "/ClientManifest/" in u), 2)

    def test_tracker_unreachable_is_none_not_empty(self):
        import asyncio
        c = self._fake_client({"a": 300}, api_down=True)
        self.assertIsNone(asyncio.run(dh.served_candidates("f", [300], c)))
        self.assertEqual(asyncio.run(dh.served_candidates("f", [], c)), [])

    def test_downgrade_target_refuses_when_nothing_was_served(self):
        # Whole decision with the feeds and the tracker patched: a stable Deck
        # broken on 1794424036 whose supported builds are beta-only -> no button.
        import asyncio
        import headcrab_compat, steam_update_gate, paths
        LL = DowngradeTargetTests.LL; SLS = DowngradeTargetTests.SLS
        saved = {}
        def patch(mod, name, val):
            saved[(mod, name)] = getattr(mod, name); setattr(mod, name, val)
        async def ll_text(force=False): return LL
        async def group(force=False): return "20261119000000"
        async def sls(force=False): return SLS
        async def served(file, cands, client=None): return []
        patch(headcrab_compat, "_lumalinux_updates_text", ll_text)
        patch(headcrab_compat, "latest_release_group", group)
        patch(headcrab_compat, "current_steam_build", lambda: 1795048523)
        patch(steam_update_gate, "slssteam_updates_text", sls)
        patch(steam_update_gate, "_branch", lambda: "steamdeck_stable")
        patch(paths, "steam_client_arch", lambda: paths.STEAM_CLIENT_64)
        patch(dh, "served_candidates", served)
        patch(dh, "_TARGET_CACHE", "/nonexistent/dir/downgrade_target.json")
        try:
            r = asyncio.run(dh.downgrade_target(force=True))
        finally:
            for (mod, name), val in saved.items():
                setattr(mod, name, val)
        self.assertIs(r["possible"], False)
        self.assertIsNone(r["target"])
        self.assertEqual(r["tracker_file"], "steamdeck_stable_steamrt64")
        self.assertIn("steamdeck_stable_steamrt64", r["error"])

    def test_downgrade_target_keeps_only_served_candidates(self):
        import asyncio
        import headcrab_compat, steam_update_gate, paths
        LL = DowngradeTargetTests.LL; SLS = DowngradeTargetTests.SLS
        saved = {}
        def patch(mod, name, val):
            saved[(mod, name)] = getattr(mod, name); setattr(mod, name, val)
        async def ll_text(force=False): return LL
        async def group(force=False): return "20261119000000"
        async def sls(force=False): return SLS
        async def served(file, cands, client=None): return [c for c in cands if c == 1794266161]
        patch(headcrab_compat, "_lumalinux_updates_text", ll_text)
        patch(headcrab_compat, "latest_release_group", group)
        patch(headcrab_compat, "current_steam_build", lambda: 1795048523)
        patch(steam_update_gate, "slssteam_updates_text", sls)
        patch(steam_update_gate, "_branch", lambda: "publicbeta")
        patch(paths, "steam_client_arch", lambda: paths.STEAM_CLIENT_64)
        patch(dh, "served_candidates", served)
        patch(dh, "_TARGET_CACHE", "/nonexistent/dir/downgrade_target.json")
        try:
            r = asyncio.run(dh.downgrade_target(force=True))
        finally:
            for (mod, name), val in saved.items():
                setattr(mod, name, val)
        self.assertEqual((r["target"], r["candidates"], r["possible"]), (1794266161, [1794266161], True))
        self.assertEqual(r["hash"][:8], "53bdabbb")


if __name__ == "__main__":
    unittest.main()

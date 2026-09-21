"""game_versions.py: the pure parts (beta filter, current build) and the
not-installed guard. The SteamDB read and the pin are exercised by their own
modules' tests and by the codespace run.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import game_versions as gv  # noqa: E402
import versions as v  # noqa: E402


def T(*a):
    return datetime(*a, tzinfo=timezone.utc)


class PublicBuilds(unittest.TestCase):
    def test_beta_row_drops_the_build_others_stay(self):
        builds = [v.Build(3, T(2025, 2, 24, 18, 21, 58), "c"),
                  v.Build(2, T(2024, 8, 27, 16, 48, 4), "b"),
                  v.Build(1, T(2023, 6, 18, 5, 54, 25), "a")]
        rows = [v.ManifestRow(1, 11, T(2025, 2, 24, 18, 21, 57)),
                v.ManifestRow(1, 12, T(2024, 8, 27, 16, 48, 5), branch="beta")]
        kept = gv.public_builds(builds, rows)
        self.assertEqual([b.buildid for b in kept], [3, 1])   # 2 sits on a beta row; 1 has no row: kept

    def test_no_rows_keeps_everything(self):
        builds = [v.Build(1, T(2024, 1, 1), "a")]
        self.assertEqual(gv.public_builds(builds, []), builds)


class CurrentBuild(unittest.TestCase):
    def setUp(self):
        import pins
        self.pins = pins
        self._vi, self._fr, self._ib = pins.version_info, pins.is_frozen, pins.installed_buildid

    def tearDown(self):
        self.pins.version_info, self.pins.is_frozen, self.pins.installed_buildid = self._vi, self._fr, self._ib

    def test_pinned_with_build_wins(self):
        self.pins.version_info = lambda a: {"buildid": "13615277"}
        self.pins.is_frozen = lambda a: True
        self.pins.installed_buildid = lambda a: 17459173
        self.assertEqual(gv.current_build(1), 13615277)

    def test_pinned_without_build_is_unknown_not_the_acf(self):
        self.pins.version_info = lambda a: {"buildid": None}
        self.pins.is_frozen = lambda a: True
        self.pins.installed_buildid = lambda a: 17459173
        self.assertIsNone(gv.current_build(1))

    def test_unpinned_uses_the_acf(self):
        self.pins.version_info = lambda a: None
        self.pins.is_frozen = lambda a: False
        self.pins.installed_buildid = lambda a: 17459173
        self.assertEqual(gv.current_build(1), 17459173)


class AllBuilds(unittest.TestCase):
    """_all_builds: the feed's 10, nothing else is requested."""

    def _reader(self, feed_ok):
        import steamdb_reader as sr
        feed = open(os.path.join(os.path.dirname(__file__), "fixtures", "steamdb",
                                 "PatchnotesRSS_2545360.xml"), encoding="utf-8").read()

        class R:
            appid = 1
            needs_user = False
            view_state = {}
            paths = []

            async def builds_page(self):
                raise AssertionError("the builds table must not be requested")

            async def get(self, path, ttl, *a, **k):
                self.paths.append(path)
                return sr.Fetched(path, outcome="ok" if feed_ok else "http_error",
                                  transport="direct", status=200 if feed_ok else 403, text=feed if feed_ok else "")
        return R()

    def test_feed_only(self):
        r = self._reader(True)
        builds, source = asyncio.run(gv._all_builds(r))
        self.assertEqual(source, "feed")
        self.assertEqual(len(builds), 10)
        self.assertEqual(r.paths, ["/api/PatchnotesRSS/?appid=1"])

    def test_nothing_when_the_feed_fails(self):
        builds, source = asyncio.run(gv._all_builds(self._reader(False)))
        self.assertEqual((builds, source), ([], "none"))


class NotInstalled(unittest.TestCase):
    def test_list_and_install_refuse_without_depots(self):
        import pins
        keep = pins.installed_depots
        pins.installed_depots = lambda a: {}
        try:
            self.assertEqual(asyncio.run(gv.list_versions(1))["error"], "not_installed")
            self.assertEqual(asyncio.run(gv.install_version(1, 2))["error"], "not_installed")
        finally:
            pins.installed_depots = keep


if __name__ == "__main__":
    unittest.main()

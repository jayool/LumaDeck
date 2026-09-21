"""versions.py: SteamDB feed/history parsers and the build -> gids join, against
the captures in tests/fixtures/steamdb/ (app 2545360, depot 2545361).

    python -m unittest discover -s tests
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import versions as V  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "steamdb")


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def _t(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


DEPOT = 2545361
# Feed build -> the public row at the same second (the join's ground truth).
EXPECTED = {
    25186450: 4209777899962857694,
    23207407: 6942462877456514386,
    22984428: 6746481342175634782,
    22687582: 3382795988127541794,
    21901851: 7163153305258776199,
    21804737: 3373149024265861,
    21716451: 8570201879598297527,
    21683820: 766500775795107344,
    21512016: 9015231850671778882,
}


class Feed(unittest.TestCase):
    def setUp(self):
        self.builds = V.parse_builds_feed(_read("PatchnotesRSS_2545360.xml"))

    def test_all_items_newest_first(self):
        self.assertEqual([b.buildid for b in self.builds][:3], [25186450, 25172008, 23207407])
        self.assertEqual(len(self.builds), 10)

    def test_time_is_the_publish_time_utc(self):
        b = next(b for b in self.builds if b.buildid == 23207407)
        self.assertEqual(b.time, _t("2026-05-21T00:44:19"))
        self.assertEqual(b.date, "2026-05-21")

    def test_label_is_the_studio_string_or_none(self):
        by = {b.buildid: b for b in self.builds}
        self.assertEqual(by[25172008].label, "V 1.4.511 - OFFICIAL IN-GAME LEVEL EDITOR RELEASE!")
        self.assertEqual(by[21716451].label, "Version 1.4.207 - Hotfix Steam Cloud Storage")
        self.assertIsNone(by[25186450].label)          # "SteamDB Build 25186450" only

    def test_garbage_in_nothing_out(self):
        self.assertEqual(V.parse_builds_feed("<not xml"), [])
        self.assertEqual(V.parse_builds_feed("<rss><channel><item><title>x</title></item></channel></rss>"), [])


class History(unittest.TestCase):
    def setUp(self):
        self.rows = V.parse_depot_history(_read("depot_2545361_manifests.fragment.html"), DEPOT)

    def test_rows_with_time_gid_branch(self):
        self.assertEqual(len(self.rows), 22)
        self.assertEqual(sum(1 for r in self.rows if r.public), 10)
        r = next(r for r in self.rows if r.gid == 6942462877456514386)
        self.assertEqual((r.depot, r.time, r.branch), (DEPOT, _t("2026-05-21T00:44:19"), "public"))
        r = next(r for r in self.rows if r.gid == 1608269889624674378)
        self.assertEqual(r.branch, "leveleditor")
        self.assertIn("public_beta", {r.branch for r in self.rows})

    def test_branch_never_leaks_from_the_next_row(self):
        html = ('<tr><td class="timeago" data-time="2026-05-21T00:44:19+00:00"></td>'
                '<td><a href="/depot/1/history/?changeid=M:111">111</a></td></tr>'
                '<tr><td class="timeago" data-time="2026-05-21T00:31:59+00:00"></td>'
                '<td><a href="/depot/1/history/?changeid=M:222">222</a>'
                '<code class="js-branch">leveleditor</code></td></tr>')
        rows = V.parse_depot_history(html)
        self.assertEqual([(r.gid, r.branch) for r in rows], [(111, "public"), (222, "leveleditor")])

    def test_other_depot_rows_are_dropped_when_asked(self):
        html = ('<tr><td data-time="2026-01-01T00:00:00+00:00"></td>'
                '<td><a href="/depot/7/history/?changeid=M:5">5</a></td></tr>')
        self.assertEqual(V.parse_depot_history(html, depot=8), [])
        self.assertEqual(len(V.parse_depot_history(html)), 1)


class BuildPage(unittest.TestCase):
    def test_changed_depots_from_inline_json(self):
        self.assertEqual(V.parse_build_depots(_read("patchnotes_25172008.fragment.html")),
                         {DEPOT: 9107064576136045598})

    def test_missing_json(self):
        self.assertEqual(V.parse_build_depots("<html></html>"), {})


class Join(unittest.TestCase):
    def setUp(self):
        self.builds = {b.buildid: b for b in V.parse_builds_feed(_read("PatchnotesRSS_2545360.xml"))}
        self.rows = V.parse_depot_history(_read("depot_2545361_manifests.fragment.html"), DEPOT)

    def test_every_captured_build_matches_its_public_row_to_the_second(self):
        for buildid, gid in EXPECTED.items():
            res = V.resolve_depot(DEPOT, self.builds[buildid].time, self.rows)
            self.assertEqual((res.status, res.gid), ("changed", gid), buildid)

    def test_build_missing_from_the_capture_falls_back_to_the_previous_public_row(self):
        # 25172008 (15:30) is the top row the capture lost; its gid is unknown to
        # the table, so the resolver can only say "unchanged since 12:53".
        res = V.resolve_depot(DEPOT, self.builds[25172008].time, self.rows)
        self.assertEqual((res.status, res.gid), ("unchanged", 4209777899962857694))

    def test_beta_row_thirteen_minutes_earlier_is_never_picked(self):
        # 21 May: leveleditor at 00:31:59, public at 00:44:19. A build stamped
        # at the beta's own time must not get the beta gid.
        res = V.resolve_depot(DEPOT, _t("2026-05-21T00:31:59"), self.rows)
        self.assertEqual((res.status, res.gid), ("unchanged", 6746481342175634782))   # 29 Apr, public

    def test_a_change_after_the_build_is_never_picked(self):
        rows = [V.ManifestRow(300, 3, _t("2026-08-03T15:26:00")),        # after
                V.ManifestRow(300, 2, _t("2026-01-15T18:20:43"))]        # before
        res = V.resolve_depot(300, _t("2026-07-20T12:00:00"), rows)
        self.assertEqual((res.status, res.gid), ("unchanged", 2))
        only_after = [V.ManifestRow(300, 3, _t("2026-08-03T15:26:00"))]
        res = V.resolve_depot(300, _t("2026-07-20T12:00:00"), only_after)
        self.assertEqual((res.status, res.gid), ("unconfirmed", None))

    def test_build_page_gid_wins_without_dates(self):
        res = V.resolve_depot(DEPOT, self.builds[25172008].time, self.rows, build_gid=9107064576136045598)
        self.assertEqual((res.status, res.gid), ("changed", 9107064576136045598))

    def test_resolve_build_over_the_users_depots(self):
        b = self.builds[23207407]
        out = V.resolve_build(b, [DEPOT, 999], {DEPOT: self.rows}, {})
        self.assertEqual(out[DEPOT].gid, 6942462877456514386)
        self.assertEqual(out[999].status, "unconfirmed")
        self.assertEqual(V.pins_from(out), {DEPOT: 6942462877456514386})
        self.assertEqual(V.unconfirmed(out), [999])

    def test_build_branch_from_rows(self):
        self.assertEqual(V.build_branch(_t("2026-05-21T00:44:19"), self.rows), "public")
        self.assertEqual(V.build_branch(_t("2026-05-21T00:31:59"), self.rows), "leveleditor")
        self.assertIsNone(V.build_branch(_t("2026-06-01T00:00:00"), self.rows))


class Rfc2822AndEntities(unittest.TestCase):
    """versions.py must not import xml/email/html: Decky's bundled Python
    lacks them (probe failed with "No module named 'xml.etree'")."""

    def test_no_forbidden_imports(self):
        import versions as v
        src = open(v.__file__, encoding="utf-8").read()
        for mod in ("xml", "email", "html"):
            self.assertNotRegex(src, rf"^\s*(import|from)\s+{mod}\b", msg=mod)

    def test_pubdate_variants(self):
        from datetime import datetime, timezone
        import versions as v
        want = datetime(2026, 9, 8, 12, 53, 52, tzinfo=timezone.utc)
        self.assertEqual(v.parse_rfc2822("Tue, 08 Sep 2026 12:53:52 +0000"), want)
        self.assertEqual(v.parse_rfc2822("08 Sep 2026 14:53:52 +0200"), want)
        self.assertEqual(v.parse_rfc2822("Tue, 08 Sep 2026 12:53:52 GMT"), want)
        self.assertIsNone(v.parse_rfc2822("2026-09-08"))
        self.assertIsNone(v.parse_rfc2822(""))

    def test_entities_and_cdata(self):
        import versions as v
        feed = ("<rss><channel><item><title><![CDATA[Game update & more]]></title>"
                "<link>https://steamdb.info/patchnotes/5/</link>"
                "<description>V 1.0 &amp; &quot;hotfix&quot; &#x27;x&#39; (SteamDB Build 5)</description>"
                "<pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate></item></channel></rss>")
        b = v.parse_builds_feed(feed)
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0].title, "Game update & more")
        self.assertEqual(b[0].label, "V 1.0 & \"hotfix\" 'x'")
        self.assertEqual(v.parse_builds_feed("not xml"), [])


if __name__ == "__main__":
    unittest.main()

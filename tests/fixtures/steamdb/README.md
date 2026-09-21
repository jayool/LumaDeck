# SteamDB samples (Lonely Mountains: Snow Riders, app 2545360)

Captured 2026-09-21 from a desktop browser, for the version-picker parsers
(#43). No code uses them yet.

- `PatchnotesRSS_2545360.xml` — `steamdb.info/api/PatchnotesRSS/?appid=2545360`,
  complete. One `<item>` per build: build id in `<link>` (`/patchnotes/<id>/`),
  `<pubDate>` = the build's publish time (matches the depot history to the
  second), `<description>` carries the studio's version string when set.
- `depot_2545361_manifests.fragment.html` — `<tr>` rows of the "manifests" table
  at `steamdb.info/depot/2545361/manifests/`, top row (9107064576136045598,
  build 25172008, 2026-09-08 15:30) missing from the capture. Each row:
  `data-time` ISO timestamp, gid in the `changeid=M:` link, and
  `<code class="js-branch">` only when the row is NOT the public branch.
- `patchnotes_25172008.fragment.html` — the depot block of
  `steamdb.info/patchnotes/25172008/`. The static HTML only carries the
  changed depots as JSON (`const depots = [...]`); old→new history is lazy
  loaded by JS from `/api/GetDepotHistory/` and gated on ownership.

Join checked: 9/10 RSS builds match a public depot row within 3 s (the 10th is
the missing top row).

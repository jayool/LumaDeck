"""Unit tests for backend/slssteam_version.py.

Nothing SLSsteam installs states its version, so LumaDeck resolves it from two
sources: the tag setup.sh recorded, or — for installs predating that — a lower
bound scanned out of the binary. The guardrail these tests pin is the direction
of the errors:

  * a malformed record is NEVER fed to the version compare;
  * the derived value NEVER overstates how new the install is;
  * an unresolvable version yields None, never a guess.

Pure helpers are tested with fixtures, so this runs anywhere:
    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import slssteam_version as sv  # noqa: E402


# Shaped like the real res/updates.yaml: two-space-indented VERSION keys, each
# with a list of steamclient.so hashes, plus the trailing-comment form AceSLS
# uses when a VERSION reuses the previous group's hashes.
UPDATES_YAML = """\
SafeModeHashes:
  20251226083318:
    - 8cd7cd0cf872396c47371c23bbd805d4e5aa8088a9d5b1518f60c24e6f3c444d #ubuntu12_32
    - 1e9ddfe86369edb365458bc1973381625e01d3c0c687e3e87150b59a1c84a871 #steamdeck_stable

  20260624075231: #tag 20260528151547

  20260815201341: #tag 20260815201341
    - d0c0ff6ea6b3df8900 #ubuntu32_32 & steamdeck_stable - 20260804
"""


class CandidateVersionsTests(unittest.TestCase):
    def test_keys_are_parsed_newest_first(self):
        self.assertEqual(
            sv.candidate_versions(UPDATES_YAML),
            [20260815201341, 20260624075231, 20251226083318],
        )

    def test_hashes_and_comments_are_not_mistaken_for_keys(self):
        # The hash lines contain long digit runs and the comments contain bare
        # 8-digit dates; neither is a top-level key.
        for v in sv.candidate_versions(UPDATES_YAML):
            self.assertEqual(len(str(v)), 14)

    def test_empty_or_junk_yields_no_candidates(self):
        self.assertEqual(sv.candidate_versions(""), [])
        self.assertEqual(sv.candidate_versions("not yaml at all"), [])


class ScanSoVersionTests(unittest.TestCase):
    """SLSsteam compiles VERSION as a constexpr uint64_t, so it sits in the
    binary as 8 little-endian bytes and cannot be found by a text search. We
    identify it by testing the known-possible values."""

    CANDIDATES = [20260815201341, 20260624075231, 20251226083318]

    def _so(self, payload: bytes) -> str:
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        self.addCleanup(os.remove, path)
        return path

    def test_finds_the_embedded_value(self):
        blob = b"\x00" * 512 + (20260624075231).to_bytes(8, "little") + b"\xff" * 512
        self.assertEqual(sv.scan_so_version(self._so(blob), self.CANDIDATES),
                         20260624075231)

    def test_no_match_returns_none(self):
        self.assertIsNone(sv.scan_so_version(self._so(b"\x00" * 4096), self.CANDIDATES))

    def test_ambiguous_match_returns_none(self):
        # Two candidates present: we cannot tell which is the version, so we say
        # nothing rather than pick one.
        blob = ((20260815201341).to_bytes(8, "little")
                + (20251226083318).to_bytes(8, "little"))
        self.assertIsNone(sv.scan_so_version(self._so(blob), self.CANDIDATES))

    def test_missing_file_returns_none(self):
        self.assertIsNone(sv.scan_so_version("/nonexistent/SLSsteam.so", self.CANDIDATES))

    def test_big_endian_is_not_matched(self):
        # x86 stores the constant little-endian; matching the reversed bytes too
        # would double the collision surface for no gain.
        blob = (20260624075231).to_bytes(8, "big")
        self.assertIsNone(sv.scan_so_version(self._so(blob), self.CANDIDATES))


class ReadRecordedVersionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        real = sv.get_slssteam_config_dir
        sv.get_slssteam_config_dir = lambda: self.cfg
        self.addCleanup(lambda: setattr(sv, "get_slssteam_config_dir", real))

    def _write(self, text: str):
        with open(os.path.join(self.cfg, ".slssteam.version"), "w") as fh:
            fh.write(text)

    def test_reads_a_release_tag(self):
        self._write("20260820085507\n")
        self.assertEqual(sv.read_recorded_version(), "20260820085507")

    def test_absent_file_is_none(self):
        self.assertIsNone(sv.read_recorded_version())

    def test_malformed_records_are_rejected(self):
        # "update" is SLSsteam's stale rolling tag — the case that motivated the
        # validation: _version_tuple() would turn it into (0, 0, 0) and order it
        # below every real release, silently. The rest are failure modes of a
        # best-effort curl (empty, an error page) or the wrong project's scheme.
        for bad in ("update", "", "   \n", "<!DOCTYPE html>", "0.18.1",
                    "2026082008550", "202608200855077", "v20260820085507"):
            with self.subTest(bad=bad):
                self._write(bad)
                self.assertIsNone(sv.read_recorded_version())


if __name__ == "__main__":
    unittest.main()

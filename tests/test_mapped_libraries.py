"""One pass over /proc/*/maps answers "is it loaded?" for every component
(backend/paths.py mapped_libraries / _is_mapped)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths  # noqa: E402


def _fake_proc(d, maps_by_pid):
    for pid, text in maps_by_pid.items():
        os.makedirs(os.path.join(d, str(pid)))
        with open(os.path.join(d, str(pid), "maps"), "w") as f:
            f.write(text)


class MappedLibrariesTests(unittest.TestCase):
    def test_finds_each_name_in_whichever_process_maps_it(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_proc(d, {
                100: "e5000000-e5100000 r-xp 00000000 fd:01 1 /home/deck/.local/share/SLSsteam/SLSsteam.so\n",
                200: "e6000000-e6100000 r-xp 00000000 fd:01 2 /home/deck/.local/share/lumalinux/liblumalinux.so\n"
                     "e7000000-e7100000 r-xp 00000000 fd:01 3 /usr/lib32/libc.so.6\n",
            })
            self.assertEqual(paths.mapped_libraries(proc_root=d),
                             frozenset({"SLSsteam.so", "liblumalinux.so"}))

    def test_nothing_mapped_and_unreadable_maps_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_proc(d, {100: "e5000000-e5100000 r-xp 00000000 fd:01 1 /usr/lib32/libc.so.6\n"})
            os.makedirs(os.path.join(d, "300"))
            os.mkdir(os.path.join(d, "300", "maps"))  # a directory, not a file: open() fails
            self.assertEqual(paths.mapped_libraries(proc_root=d), frozenset())

    def test_substring_match_is_what_it_always_was(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_proc(d, {100: "e5000000-e5100000 r-xp 00000000 fd:01 1 /x/cloud_redirect.so.bak\n"})
            # "cloud_redirect.so" is a substring of "cloud_redirect.so.bak": the
            # scan is a substring test, as the three per-library scans were, so
            # this documents that a .bak sitting in a process's maps would count.
            # No process maps a .bak file (the loader opens the real name), so
            # the question never arises in practice.
            self.assertEqual(paths.mapped_libraries(proc_root=d), frozenset({"cloud_redirect.so"}))

    def test_one_scan_serves_the_three_checks_within_the_ttl(self):
        calls = []

        def fake_scan(names=paths._MAPPED_NAMES, proc_root="/proc"):
            calls.append(1)
            return frozenset({"SLSsteam.so", "cloud_redirect.so"})

        with mock.patch.object(paths, "mapped_libraries", fake_scan), \
             mock.patch.dict(paths._mapped_cache, {"at": 0.0, "found": frozenset()}):
            self.assertTrue(paths._check_process_injected())
            self.assertFalse(paths.check_lumalinux_active())
            self.assertTrue(paths.check_cloudredirect_active())
            self.assertEqual(len(calls), 1)

    def test_the_scan_is_repeated_once_the_ttl_has_passed(self):
        calls = []

        def fake_scan(names=paths._MAPPED_NAMES, proc_root="/proc"):
            calls.append(1)
            return frozenset()

        with mock.patch.object(paths, "mapped_libraries", fake_scan), \
             mock.patch.dict(paths._mapped_cache, {"at": 0.0, "found": frozenset()}):
            paths.check_lumalinux_active()
            paths._mapped_cache["at"] -= paths._MAPPED_TTL + 1
            paths.check_lumalinux_active()
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()

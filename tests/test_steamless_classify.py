"""steamless.py — the per-exe outcome and the timeout cleanup:
    python -m unittest discover -s tests

Pins: rc 0 is "unpacked" only when the swap happened (else swap_failed); rc 1
is "no_drm" unless the CLI said it failed to unpack (the Cosmic Fear case,
formerly reported as no DRM); anything else is error; a killed run's partial
.unpacked.exe (either naming) is removed and the original never touched; the
swap finds either output name and keeps a pristine .original.exe.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import steamless as sl  # noqa: E402


class Classify(unittest.TestCase):
    def test_rc0(self):
        self.assertEqual(sl._classify(0, "Unpacked!", True), sl.OUTCOME_UNPACKED)
        self.assertEqual(sl._classify(0, "Unpacked!", False), sl.OUTCOME_SWAP_FAILED)

    def test_rc1_not_packed(self):
        self.assertEqual(sl._classify(1, "File is not packed with SteamStub.", False), sl.OUTCOME_NO_DRM)
        self.assertEqual(sl._classify(1, "", False), sl.OUTCOME_NO_DRM)

    def test_rc1_unpack_failed(self):
        out = "Info: File is packed with SteamStub v3.1 x64\nError: Failed to unpack file.\n"
        self.assertEqual(sl._classify(1, out, False), sl.OUTCOME_UNPACK_FAILED)
        self.assertEqual(sl._classify(1, "FAILED TO UNPACK FILE", False), sl.OUTCOME_UNPACK_FAILED)

    def test_other_rc(self):
        self.assertEqual(sl._classify(2, "boom", False), sl.OUTCOME_ERROR)
        self.assertEqual(sl._classify(None, "", False), sl.OUTCOME_ERROR)
        self.assertEqual(sl._classify(-9, "", False), sl.OUTCOME_ERROR)


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.exe = os.path.join(self.tmp, "Game.exe")
        self._w(self.exe, b"PACKED")

    def _w(self, p, data):
        with open(p, "wb") as f:
            f.write(data)

    def _r(self, p):
        with open(p, "rb") as f:
            return f.read()

    def test_cleanup_partial_removes_either_name_and_keeps_original(self):
        self._w(self.exe + ".unpacked.exe", b"HALF")
        self._w(os.path.join(self.tmp, "Game.unpacked.exe"), b"HALF2")
        self.assertEqual(sl._cleanup_partial(self.exe), 2)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["Game.exe"])
        self.assertEqual(self._r(self.exe), b"PACKED")

    def test_cleanup_partial_with_nothing_is_zero(self):
        self.assertEqual(sl._cleanup_partial(self.exe), 0)
        self.assertEqual(self._r(self.exe), b"PACKED")

    def test_swap_uses_either_output_name(self):
        self._w(os.path.join(self.tmp, "Game.unpacked.exe"), b"CLEAN")
        self.assertTrue(sl._swap_in_unpacked(self.exe))
        self.assertEqual(self._r(self.exe), b"CLEAN")
        self.assertEqual(self._r(os.path.join(self.tmp, "Game.original.exe")), b"PACKED")

    def test_swap_keeps_pristine_original_on_rerun(self):
        self._w(self.exe + ".unpacked.exe", b"CLEAN1")
        sl._swap_in_unpacked(self.exe)
        self._w(self.exe + ".unpacked.exe", b"CLEAN2")
        self.assertTrue(sl._swap_in_unpacked(self.exe))
        self.assertEqual(self._r(self.exe), b"CLEAN2")
        self.assertEqual(self._r(os.path.join(self.tmp, "Game.original.exe")), b"PACKED")

    def test_swap_without_output_is_false(self):
        self.assertFalse(sl._swap_in_unpacked(self.exe))
        self.assertEqual(self._r(self.exe), b"PACKED")


if __name__ == "__main__":
    unittest.main()

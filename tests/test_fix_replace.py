"""One LuaTools fix per game, and un-fix restores by copy — on real files in a
temp dir, the download stubbed with an in-memory zip:
    python -m unittest discover -s tests

Pins: installed_fix_types reads the log; apply_game_fix refuses a second fix
with needsReplace + the installed types and queues nothing; with replace the
installed fix is un-fixed first (originals back, its added files gone) and the
new one lands on a clean game with a single [FIX] block; a legacy install with
two fixes over the same file survives two un-fixes (copy, not move: the second
still finds the original) and the backup tree goes with the last fix.
"""
import asyncio
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import fixes  # noqa: E402
import pins  # noqa: E402

APP = 777


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class _Resp:
    def __init__(self, data): self.data, self.headers = data, {}
    def raise_for_status(self): pass
    async def aiter_bytes(self): yield self.data


class _Stream:
    def __init__(self, data): self.data = data
    async def __aenter__(self): return _Resp(self.data)
    async def __aexit__(self, *a): return False


class _Client:
    """One zip per download URL: the URL is the key into `zips`."""
    def __init__(self, zips): self.zips = zips
    def stream(self, method, url, **kw): return _Stream(self.zips[url])


class _Now:
    def __init__(self, s): self.s = s
    def strftime(self, fmt): return self.s


class _FakeDT:
    """Distinct Date: per [FIX] block (a real clock could stamp two in one second)."""
    n = 0
    @classmethod
    def now(cls):
        cls.n += 1
        return _Now(f"2026-01-01 00:00:{cls.n:02d}")


async def _drain():
    """Wait for the download task apply_game_fix created."""
    others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if others:
        await asyncio.gather(*others)


class FixReplaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(self.game)
        self.zips = {}
        self._orig = {}

        def patch(mod, name, value):
            self._orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, value)

        patch(fixes, "ensure_temp_download_dir", lambda: self.tmp)
        patch(fixes, "ensure_http_client", self._client)
        patch(fixes, "datetime", _FakeDT)
        async def no_freeze(appid): return False
        patch(pins, "freeze_for_files", no_freeze)
        self.addCleanup(lambda: [setattr(m, n, v) for (m, n), v in self._orig.items()])
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    async def _client(self, ctx=""):
        return _Client(self.zips)

    # -- helpers ---------------------------------------------------------------
    def w(self, rel, data):
        p = os.path.join(self.game, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f: f.write(data)

    def r(self, rel):
        p = os.path.join(self.game, rel)
        if not os.path.isfile(p):
            return None
        with open(p) as f:
            return f.read()

    def bak(self, rel):
        return self.r(os.path.join(f"luatools-backup-{APP}", rel))

    def apply(self, name, files, replace=False):
        url = f"https://example.invalid/{name}.zip"
        self.zips[url] = _zip(files)
        async def run():
            res = await fixes.apply_game_fix(APP, url, self.game, fix_type=name, game_name="G", replace=replace)
            await _drain()
            return res
        return asyncio.run(run())

    def unfix(self, date=""):
        fixes._unfix_game_worker(APP, self.game, date)
        return fixes._get_unfix_state(APP)

    @property
    def backup(self): return os.path.join(self.game, f"luatools-backup-{APP}")
    @property
    def log(self): return os.path.join(self.game, f"luatools-fix-log-{APP}.log")

    # -- tests -----------------------------------------------------------------
    def test_first_fix_applies_and_is_listed(self):
        self.w("a.dll", "ORIG")
        res = self.apply("Fix1", {"a.dll": "FIX1", "b.dll": "B1"})
        self.assertTrue(res["success"], res)
        self.assertEqual(res["replaced"], [])
        self.assertEqual(fixes._get_fix_download_state(APP)["status"], "done")
        self.assertEqual(self.r("a.dll"), "FIX1")
        self.assertEqual(self.bak("a.dll"), "ORIG")
        self.assertEqual(fixes.installed_fix_types(APP, self.game), ["Fix1"])

    def test_second_fix_is_refused_until_replace(self):
        self.w("a.dll", "ORIG")
        self.apply("Fix1", {"a.dll": "FIX1", "b.dll": "B1"})
        res = self.apply("Fix2", {"a.dll": "FIX2", "c.dll": "C2"})
        self.assertFalse(res["success"])
        self.assertTrue(res["needsReplace"])
        self.assertEqual(res["installed"], ["Fix1"])
        self.assertEqual(self.r("a.dll"), "FIX1")                 # nothing touched
        self.assertIsNone(self.r("c.dll"))
        self.assertEqual(fixes.installed_fix_types(APP, self.game), ["Fix1"])

    def test_replace_unfixes_then_applies_on_a_clean_game(self):
        self.w("a.dll", "ORIG")
        self.apply("Fix1", {"a.dll": "FIX1", "b.dll": "B1"})
        res = self.apply("Fix2", {"a.dll": "FIX2", "c.dll": "C2"}, replace=True)
        self.assertTrue(res["success"], res)
        self.assertEqual(res["replaced"], ["Fix1"])
        self.assertEqual(fixes._get_fix_download_state(APP)["status"], "done")
        self.assertEqual(self.r("a.dll"), "FIX2")
        self.assertIsNone(self.r("b.dll"))                        # Fix1's added file is gone
        self.assertEqual(self.r("c.dll"), "C2")
        self.assertEqual(fixes.installed_fix_types(APP, self.game), ["Fix2"])
        self.assertEqual(self.bak("a.dll"), "ORIG")   # pristine, re-backed-up
        # Un-fix the survivor: the game is pristine again.
        self.assertEqual(self.unfix()["status"], "done")
        self.assertEqual(self.r("a.dll"), "ORIG")
        self.assertIsNone(self.r("c.dll"))
        self.assertFalse(os.path.exists(self.backup))
        self.assertFalse(os.path.exists(self.log))

    def test_replace_with_nothing_installed_is_a_plain_apply(self):
        self.w("a.dll", "ORIG")
        res = self.apply("Fix1", {"a.dll": "FIX1"}, replace=True)
        self.assertTrue(res["success"])
        self.assertEqual(res["replaced"], [])
        self.assertEqual(self.r("a.dll"), "FIX1")

    def test_legacy_two_fixes_over_one_file_unfix_one_by_one(self):
        """Pre-rule installs: two [FIX] blocks over the same file. Restores are
        copies, so the second un-fix still finds the original."""
        self.w("a.dll", "ORIG")
        self.apply("Fix1", {"a.dll": "FIX1"})
        # Second block through the task directly (the gate lives in apply_game_fix).
        url = "https://example.invalid/Fix2.zip"
        self.zips[url] = _zip({"a.dll": "FIX2", "c.dll": "C2"})
        asyncio.run(fixes._download_and_extract_fix(APP, url, self.game, "Fix2", "G"))
        self.assertEqual(fixes.installed_fix_types(APP, self.game), ["Fix1", "Fix2"])
        self.assertEqual(self.r("a.dll"), "FIX2")
        self.assertEqual(self.bak("a.dll"), "ORIG")   # first-time copy kept
        blocks = fixes._fix_log_blocks(APP, self.game)
        dates = [next(l.split(":", 1)[1].strip() for l in b.splitlines() if l.strip().startswith("Date:")) for b in blocks]
        self.assertEqual(len(set(dates)), 2)

        self.assertEqual(self.unfix(dates[0])["status"], "done")  # remove Fix1
        self.assertEqual(self.r("a.dll"), "ORIG")                 # original back...
        self.assertTrue(os.path.isfile(os.path.join(self.backup, "a.dll")))   # ...and still in the backup
        self.assertEqual(fixes.installed_fix_types(APP, self.game), ["Fix2"])

        self.assertEqual(self.unfix(dates[1])["status"], "done")  # remove Fix2
        self.assertEqual(self.r("a.dll"), "ORIG")                 # not deleted: the copy was there
        self.assertIsNone(self.r("c.dll"))
        self.assertFalse(os.path.exists(self.backup))
        self.assertFalse(os.path.exists(self.log))

    def test_installed_fix_types_without_log(self):
        self.assertEqual(fixes.installed_fix_types(APP, self.game), [])
        self.assertEqual(fixes.installed_fix_types(APP, ""), [])


if __name__ == "__main__":
    unittest.main()

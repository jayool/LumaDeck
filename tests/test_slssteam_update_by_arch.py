"""The SLSsteam update offer depends on the client that runs
(backend/components.check_slssteam_update).

Upstream dropped 32-bit support after 20261014151919, so on the 32-bit client
that release is the last "latest": a newer release at AceSLS/SLSsteam is a
64-bit build and must never be offered there. On the 64-bit client the release
feed decides, as before.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import components  # noqa: E402

LAST32 = "20261014151919"


class SlssteamUpdateByArch(unittest.TestCase):
    def setUp(self):
        self._real = sys.modules.get("slssteam_version")
        self.addCleanup(lambda: sys.modules.__setitem__("slssteam_version", self._real)
                        if self._real is not None else sys.modules.pop("slssteam_version", None))
        self._has_update = components.has_update
        self.addCleanup(lambda: setattr(components, "has_update", self._has_update))
        self.calls = []

        async def fake_has_update(owner, repo, installed, force=False):
            self.calls.append((owner, repo, installed))
            return {"installed": installed, "latest": "20261101000000", "has_update": True, "url": "u"}
        components.has_update = fake_has_update

    def _installed(self, tag, source="recorded"):
        module = types.ModuleType("slssteam_version")
        module.LAST_32BIT_TAG = LAST32
        module.SOURCE_UNKNOWN = "unknown"

        async def resolve(arch=None):
            self.resolved_arch = arch
            return tag, source
        module.resolve_installed_version = resolve
        sys.modules["slssteam_version"] = module

    def test_32bit_client_is_compared_against_the_last_32bit_release(self):
        self._installed("20260903114323")
        r = asyncio.run(components.check_slssteam_update(arch="ubuntu12_32"))
        self.assertEqual((r["installed"], r["latest"], r["has_update"]), ("20260903114323", LAST32, True))
        self.assertEqual(self.calls, [])          # the release feed is never asked
        self.assertEqual(self.resolved_arch, "ubuntu12_32")

    def test_32bit_client_on_the_last_release_has_nothing_newer(self):
        self._installed(LAST32)
        r = asyncio.run(components.check_slssteam_update(arch="ubuntu12_32"))
        self.assertFalse(r["has_update"])
        self.assertEqual(self.calls, [])

    def test_64bit_client_asks_the_release_feed(self):
        self._installed("20261022000000")
        r = asyncio.run(components.check_slssteam_update(arch="steamrt64"))
        self.assertTrue(r["has_update"])
        self.assertEqual(self.calls, [("AceSLS", "SLSsteam", "20261022000000")])
        self.assertEqual(self.resolved_arch, "steamrt64")

    def test_unknown_version_reports_no_update_on_either_client(self):
        for arch in ("ubuntu12_32", "steamrt64"):
            self._installed(None, "unknown")
            r = asyncio.run(components.check_slssteam_update(arch=arch))
            self.assertFalse(r["has_update"], arch)


if __name__ == "__main__":
    unittest.main()

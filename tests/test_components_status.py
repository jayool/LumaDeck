"""Smoke test for components.get_components_status().

This exists because of a real near-miss: an edit removed check_slssteam_update()
while leaving its call site, and every other test still passed — nothing
exercised the aggregate, so a NameError would only have surfaced on a Deck.

The point is not to assert health logic (that lives in paths.py and is tested
there) but to actually CALL the aggregate with every dependency stubbed, so that
each per-component check is resolved and the payload the UI consumes keeps its
shape. Both surfaces read the same fields — the QAM's update row
(SystemStatus.tsx) and the per-component subtext in Settings — so a rename here
silently blanks them.

Runs anywhere (no network, no Steam):
    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import components  # noqa: E402


HEALTHY = {"state": "healthy", "cause": None, "action": None}


class GetComponentsStatusTests(unittest.TestCase):
    def setUp(self):
        import paths
        import update_checks

        # get_components_status imports these lazily inside the call, so patching
        # the modules (not names in components) is what takes effect.
        self._saved = []

        def patch(mod, name, value):
            self._saved.append((mod, name, getattr(mod, name, None), hasattr(mod, name)))
            setattr(mod, name, value)

        self.patch = patch
        for fn in ("read_slssteam_health", "read_lumalinux_health",
                   "read_cloudredirect_health"):
            patch(paths, fn, lambda: dict(HEALTHY))
        patch(paths, "read_lumalinux_health", lambda: dict(HEALTHY, version="0.18.1"))
        patch(paths, "get_cloudredirect_so_path", lambda: None)

        async def _has_update(owner, repo, installed, force=False):
            return {"installed": installed, "latest": None, "has_update": False, "url": None}

        async def _latest_with_asset(owner, repo, asset, force=False):
            return None

        patch(update_checks, "has_update", _has_update)
        patch(components, "has_update", _has_update)
        patch(components, "get_latest_release_with_asset", _latest_with_asset)

        for name, attrs in (
            ("headcrab_compat", {"check_headcrab_compat": self._async_const({
                "compatible": True, "target": 20260101, "current_build": 20260101,
                "lumalinux_ready": True, "current_build_supported_by_latest": True})}),
            ("self_update", {"check_plugin_update": self._async_const({
                "installed": "0.7.2", "latest": "0.7.2", "has_update": False})}),
            ("dev", {"get": lambda key: None}),
            ("slssteam_version", {
                "SOURCE_UNKNOWN": "unknown",
                "resolve_installed_version": self._async_const(("20260820085507", "recorded")),
            }),
        ):
            self._install_stub(name, attrs)

        self.addCleanup(self._restore)

    @staticmethod
    def _async_const(value):
        async def fn(*args, **kwargs):
            return value
        return fn

    def _install_stub(self, name, attrs):
        real = sys.modules.get(name)
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module
        self.addCleanup(lambda: sys.modules.__setitem__(name, real)
                        if real is not None else sys.modules.pop(name, None))

    def _restore(self):
        for mod, name, old, existed in reversed(self._saved):
            if existed:
                setattr(mod, name, old)
            else:
                delattr(mod, name)

    def test_every_component_check_resolves_and_reports_its_shape(self):
        result = asyncio.run(components.get_components_status())
        self.assertTrue(result["success"])

        by_id = {c["id"]: c for c in result["components"]}
        self.assertEqual(set(by_id), {"slssteam", "cloudredirect", "lumalinux"})

        for cid, component in by_id.items():
            with self.subTest(component=cid):
                # The exact keys both surfaces read. `update.available` is what
                # lights the QAM row and the per-component subtext in Settings.
                self.assertEqual(
                    set(component),
                    {"id", "name", "installed", "health", "cause", "action", "update"},
                )
                self.assertEqual(set(component["update"]),
                                 {"installed", "latest", "available"})
                self.assertIsInstance(component["update"]["available"], bool)

        self.assertEqual(set(result["plugin"]), {"installed", "latest", "available"})
        self.assertIn("headcrab", result)

    def test_a_failing_subcheck_does_not_blank_the_payload(self):
        async def boom(*args, **kwargs):
            raise RuntimeError("network down")
        self.patch(components, "get_latest_release_with_asset", boom)

        result = asyncio.run(components.get_components_status())
        self.assertTrue(result["success"])
        by_id = {c["id"]: c for c in result["components"]}
        self.assertFalse(by_id["cloudredirect"]["update"]["available"])
        # The others are unaffected by CloudRedirect's failure.
        self.assertEqual(set(by_id), {"slssteam", "cloudredirect", "lumalinux"})


if __name__ == "__main__":
    unittest.main()

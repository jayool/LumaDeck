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
        patch(paths, "read_crash_guard",
              lambda: {"active": False, "fails": 0, "since": None, "client_changed": False})

        async def _has_update(owner, repo, installed, force=False):
            return {"installed": installed, "latest": None, "has_update": False, "url": None}

        patch(update_checks, "has_update", _has_update)
        patch(components, "has_update", _has_update)

        for name, attrs in (
            ("headcrab_compat", {"check_headcrab_compat": self._async_const({
                "compatible": True, "target": 20260101, "current_build": 20260101,
                "lumalinux_ready": True, "current_build_supported_by_latest": True})}),
            ("self_update", {"check_plugin_update": self._async_const({
                "installed": "0.7.2", "latest": "0.7.2", "has_update": False})}),
            ("dev", {"get": lambda key: None}),
            ("slssteam_version", {
                "SOURCE_UNKNOWN": "unknown",
                "LAST_32BIT_TAG": "20261014151919",
                "read_recorded_version": lambda *a, **k: "20260820085507",
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
                                 {"installed", "latest", "available", "supports_current_build"})
                self.assertIsInstance(component["update"]["available"], bool)

        self.assertEqual(set(result["plugin"]), {"installed", "latest", "available"})
        self.assertIn("headcrab", result)
        # The launcher's crash guard, read by the QAM's "Recovery mode" row and
        # the Settings button; stack-wide like headcrab.
        self.assertEqual(set(result["guard"]), {"active", "fails", "since", "client_changed"})
        self.assertFalse(result["guard"]["active"])

    def test_a_latched_crash_guard_is_reported(self):
        import paths
        self.patch(paths, "read_crash_guard",
                   lambda: {"active": True, "fails": 3, "since": "2026-09-23 10:22:09",
                            "client_changed": False})
        result = asyncio.run(components.get_components_status())
        self.assertEqual(result["guard"], {"active": True, "fails": 3,
                                           "since": "2026-09-23 10:22:09", "client_changed": False})

    def test_a_failing_guard_read_reports_inactive(self):
        import paths
        def boom():
            raise OSError("permission denied")
        self.patch(paths, "read_crash_guard", boom)
        result = asyncio.run(components.get_components_status())
        self.assertTrue(result["success"])
        self.assertFalse(result["guard"]["active"])

    def test_a_failing_subcheck_does_not_blank_the_payload(self):
        import paths

        def boom(*args, **kwargs):
            raise RuntimeError("disk read failed")
        self.patch(paths, "get_cloudredirect_so_path", lambda: "/nonexistent/cloud_redirect.so")
        self.patch(components, "read_cloudredirect_version", boom)

        result = asyncio.run(components.get_components_status())
        self.assertTrue(result["success"])
        by_id = {c["id"]: c for c in result["components"]}
        self.assertFalse(by_id["cloudredirect"]["update"]["available"])
        # The others are unaffected by CloudRedirect's failure.
        self.assertEqual(set(by_id), {"slssteam", "cloudredirect", "lumalinux"})


if __name__ == "__main__":
    unittest.main()


# Ace's feed shape (see test_steam_update_gate): one group per release tag, the
# newest group at or before the installed release decides what it hooks.
_OLD = "bc54101b" + "0" * 56
_NEW = "0d01ab4f" + "0" * 56
_FEED = f"""SafeModeHashes:
  20260903114323: #tag
    - {_OLD} #ubuntu12_32
  20261014151919: #tag
    - {_NEW} #ubuntu12_32
"""
NOT_LOADED = {"state": "not_loaded", "cause": None, "action": "restart"}
NOT_INJECTED = {"state": "not_injected", "cause": "wrapper", "action": "install"}
NOT_SUPPORTED = {"state": "not_supported", "cause": "version", "action": "downgrade"}


class SlssteamHealthFromFeedTests(unittest.TestCase):
    """SLSsteam not mapped reads not_loaded / not_injected from the process
    alone. When the INSTALLED release's list lacks the client on disk, the real
    cause is a Steam build it does not hook: not_supported, whose row names the
    fix. Anything the feed cannot answer leaves the state alone."""

    def setUp(self):
        self._real = sys.modules.get("slssteam_version")
        self.addCleanup(lambda: sys.modules.__setitem__("slssteam_version", self._real)
                        if self._real is not None else sys.modules.pop("slssteam_version", None))

    def _recorded(self, tag):
        module = types.ModuleType("slssteam_version")
        module.read_recorded_version = lambda *a, **k: tag
        sys.modules["slssteam_version"] = module

    def test_installed_release_lacking_the_client_is_not_supported(self):
        # 20261014151919 on the old client: the crash-loop combination.
        self._recorded("20261014151919")
        for h in (NOT_LOADED, NOT_INJECTED):
            self.assertEqual(components._slssteam_health_from_feed(dict(h), _FEED, _OLD), NOT_SUPPORTED)

    def test_installed_release_listing_the_client_is_left_alone(self):
        self._recorded("20261001163836")  # group 20260903114323 lists OLD
        self.assertEqual(components._slssteam_health_from_feed(dict(NOT_LOADED), _FEED, _OLD), NOT_LOADED)
        self._recorded("20261014151919")
        self.assertEqual(components._slssteam_health_from_feed(dict(NOT_LOADED), _FEED, _NEW), NOT_LOADED)

    def test_unanswerable_feed_leaves_the_state_alone(self):
        self._recorded("20261014151919")
        for text, sha in ((None, _OLD), (_FEED, None), ("junk", _OLD)):
            self.assertEqual(components._slssteam_health_from_feed(dict(NOT_LOADED), text, sha), NOT_LOADED)
        self._recorded(None)  # install predating the recorded tag
        self.assertEqual(components._slssteam_health_from_feed(dict(NOT_LOADED), _FEED, _OLD), NOT_LOADED)

    def test_only_the_not_mapped_states_are_rewritten(self):
        self._recorded("20261014151919")
        for h in (HEALTHY, NOT_SUPPORTED, {"state": "not_installed", "cause": None, "action": "install"}):
            self.assertEqual(components._slssteam_health_from_feed(dict(h), _FEED, _OLD), h)

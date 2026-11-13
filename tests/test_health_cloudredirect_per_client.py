"""CloudRedirect is a per-client build like SLSsteam (lumalinux v0.22.8): the
32-bit cloud_redirect.so at the CloudRedirect root, the 64-bit one under
x86_64/. backend/paths asks every question about the build of the client that
runs: installed, which .so, mapped (by path tail: both share the file name),
and the health ladder. On the 64-bit client a 32-bit .so alone is
not_installed with the install action; nothing is "unavailable" any more.

    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths  # noqa: E402


class _Patching(unittest.TestCase):
    def setUp(self):
        self._saved = []

        def patch(name, value):
            self._saved.append((name, getattr(paths, name)))
            setattr(paths, name, value)
        self.patch = patch
        self.addCleanup(lambda: [setattr(paths, n, v) for n, v in reversed(self._saved)])
        import dev
        self._dev_get = dev.get
        dev.get = lambda key: None
        self.addCleanup(lambda: setattr(dev, "get", self._dev_get))

    def _client(self, arch):
        self.patch("steam_client_arch", lambda: arch)
        self.patch("steam_client_is_64", lambda: arch == paths.STEAM_CLIENT_64)


class PerClientPaths(_Patching):
    """The .so of the running client, from one CloudRedirect dir holding both."""

    def _dir(self, have32, have64):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        if have32:
            open(os.path.join(d.name, "cloud_redirect.so"), "wb").write(b"\x7fELF\x01")
        if have64:
            os.mkdir(os.path.join(d.name, "x86_64"))
            open(os.path.join(d.name, "x86_64", "cloud_redirect.so"), "wb").write(b"\x7fELF\x02")
        self.patch("_CLOUDREDIRECT_CANDIDATES", [d.name])
        return d.name

    def test_relpath_per_client(self):
        self.assertEqual(paths._cloudredirect_so_relpath(paths.STEAM_CLIENT_32), "cloud_redirect.so")
        self.assertEqual(paths._cloudredirect_so_relpath(paths.STEAM_CLIENT_64),
                         os.path.join("x86_64", "cloud_redirect.so"))

    def test_64bit_client_needs_the_x86_64_build(self):
        d = self._dir(have32=True, have64=False)
        self._client(paths.STEAM_CLIENT_64)
        self.assertFalse(paths.check_cloudredirect_installed())
        self.assertIsNone(paths.get_cloudredirect_so_path())
        # The 32-bit build is still there for the 32-bit client.
        self.assertTrue(paths.check_cloudredirect_installed(paths.STEAM_CLIENT_32))
        self.assertEqual(paths.get_cloudredirect_so_path(paths.STEAM_CLIENT_32),
                         os.path.join(d, "cloud_redirect.so"))

    def test_both_builds_each_client_its_own(self):
        d = self._dir(have32=True, have64=True)
        self._client(paths.STEAM_CLIENT_64)
        self.assertEqual(paths.get_cloudredirect_so_path(), os.path.join(d, "x86_64", "cloud_redirect.so"))
        self._client(paths.STEAM_CLIENT_32)
        self.assertEqual(paths.get_cloudredirect_so_path(), os.path.join(d, "cloud_redirect.so"))

    def test_32bit_client_ignores_an_x86_64_only_dir(self):
        self._dir(have32=False, have64=True)
        self._client(paths.STEAM_CLIENT_32)
        self.assertFalse(paths.check_cloudredirect_installed())
        self.assertTrue(paths.check_cloudredirect_installed(paths.STEAM_CLIENT_64))

    def test_mapped_is_matched_by_path_tail(self):
        seen = []
        self.patch("_is_mapped", lambda name: (seen.append(name), name.endswith("x86_64/cloud_redirect.so"))[1])
        self._client(paths.STEAM_CLIENT_64)
        self.assertTrue(paths.check_cloudredirect_active())
        self._client(paths.STEAM_CLIENT_32)
        self.assertFalse(paths.check_cloudredirect_active())
        self.assertEqual(seen, ["CloudRedirect/x86_64/cloud_redirect.so", "CloudRedirect/cloud_redirect.so"])
        # Both tails are in the one-scan name list, so the shared scan sees them.
        self.assertIn("CloudRedirect/x86_64/cloud_redirect.so", paths._MAPPED_NAMES)
        self.assertIn("CloudRedirect/cloud_redirect.so", paths._MAPPED_NAMES)


class HealthOnThe64BitClient(_Patching):
    def _ladder(self, mapped, cause=None, authed=True, coverage=True):
        self.patch("_cloudredirect_kill_switched", lambda: False)
        self.patch("check_cloudredirect_active", lambda arch=None: mapped)
        self.patch("_cloudredirect_log_inspect", lambda: ("2.6.6+2a48dac", cause))
        self.patch("_wrapper_coverage_present", lambda: coverage)
        self.patch("check_cloudredirect_authed", lambda: authed)

    def test_without_the_x86_64_build_it_is_not_installed(self):
        self._client(paths.STEAM_CLIENT_64)
        self.patch("check_cloudredirect_installed", lambda arch=None: False)
        self.assertEqual(paths.read_cloudredirect_health(),
                         {"state": "not_installed", "cause": None, "version": None, "action": "install"})

    def test_installed_not_mapped_is_not_loaded(self):
        self._client(paths.STEAM_CLIENT_64)
        self.patch("check_cloudredirect_installed", lambda arch=None: True)
        self._ladder(mapped=False)
        self.assertEqual(paths.read_cloudredirect_health()["state"], "not_loaded")

    def test_mapped_and_clean_is_healthy(self):
        self._client(paths.STEAM_CLIENT_64)
        self.patch("check_cloudredirect_installed", lambda arch=None: True)
        self._ladder(mapped=True)
        self.assertEqual(paths.read_cloudredirect_health(),
                         {"state": "healthy", "cause": None, "version": "2.6.6+2a48dac", "action": None})

    def test_mapped_without_tokens_is_not_authed(self):
        self._client(paths.STEAM_CLIENT_64)
        self.patch("check_cloudredirect_installed", lambda arch=None: True)
        self._ladder(mapped=True, authed=False)
        self.assertEqual(paths.read_cloudredirect_health()["state"], "not_authed")

    def test_an_init_failure_is_not_supported(self):
        self._client(paths.STEAM_CLIENT_64)
        self.patch("check_cloudredirect_installed", lambda arch=None: True)
        self._ladder(mapped=True, cause="incompatible")
        h = paths.read_cloudredirect_health()
        self.assertEqual((h["state"], h["cause"]), ("not_supported", "version"))

    def test_no_state_is_unavailable_any_more(self):
        self._client(paths.STEAM_CLIENT_64)
        self.patch("check_cloudredirect_installed", lambda arch=None: True)
        self._ladder(mapped=True)
        self.assertNotIn("unavailable", paths.read_cloudredirect_health()["state"])

    def test_32bit_client_is_unchanged(self):
        self._client(paths.STEAM_CLIENT_32)
        self.patch("check_cloudredirect_installed", lambda arch=None: True)
        self._ladder(mapped=False)
        self.assertEqual(paths.read_cloudredirect_health()["state"], "not_loaded")


if __name__ == "__main__":
    unittest.main()

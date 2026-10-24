"""unavailable_64: Steam runs its 64-bit client and a component has no build
for it (backend/paths.read_slssteam_health / read_cloudredirect_health).

SLSsteam reads it only when the stack is installed (a 32-bit build on disk)
and the x86_64 build is missing; a device with no build at all stays
not_installed so Quick Install is offered. CloudRedirect, 32-bit only, reads
it on the 64-bit client whatever else is true. Neither offers an action: a
restart or a reinstall changes nothing until a 64-bit build exists.

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths  # noqa: E402


class Unavailable64(unittest.TestCase):
    def setUp(self):
        self._saved = []

        def patch(name, value):
            self._saved.append((name, getattr(paths, name)))
            setattr(paths, name, value)
        self.patch = patch
        self.addCleanup(lambda: [setattr(paths, n, v) for n, v in reversed(self._saved)])
        # No Dev override, no kill switch.
        import dev
        self._dev_get = dev.get
        dev.get = lambda key: None
        self.addCleanup(lambda: setattr(dev, "get", self._dev_get))

    def _client(self, arch):
        patch = self.patch
        patch("steam_client_arch", lambda: arch)
        patch("steam_client_is_64", lambda: arch == paths.STEAM_CLIENT_64)

    def _slssteam_on_disk(self, have32, have64):
        self.patch("check_slssteam_installed",
                   lambda arch=None: have64 if (arch or paths.steam_client_arch()) == paths.STEAM_CLIENT_64 else have32)

    def test_slssteam_64bit_client_without_its_build(self):
        self._client(paths.STEAM_CLIENT_64)
        self._slssteam_on_disk(have32=True, have64=False)
        self.assertEqual(paths.read_slssteam_health(),
                         {"state": "unavailable_64", "cause": None, "action": None})

    def test_slssteam_fresh_device_stays_not_installed(self):
        self._client(paths.STEAM_CLIENT_64)
        self._slssteam_on_disk(have32=False, have64=False)
        self.assertEqual(paths.read_slssteam_health()["state"], "not_installed")

    def test_slssteam_32bit_client_never_reads_it(self):
        self._client(paths.STEAM_CLIENT_32)
        self._slssteam_on_disk(have32=False, have64=False)
        self.assertEqual(paths.read_slssteam_health()["state"], "not_installed")
        self._slssteam_on_disk(have32=True, have64=False)
        self.patch("verify_slssteam_injected", lambda: {"method": "wrapper_configured"})
        self.assertEqual(paths.read_slssteam_health()["state"], "not_loaded")

    def test_cloudredirect_on_the_64bit_client(self):
        self._client(paths.STEAM_CLIENT_64)
        self.patch("check_cloudredirect_installed", lambda: True)
        self.assertEqual(paths.read_cloudredirect_health(),
                         {"state": "unavailable_64", "cause": None, "version": None, "action": None})
        self.patch("check_cloudredirect_installed", lambda: False)
        self.assertEqual(paths.read_cloudredirect_health()["state"], "not_installed")

    def test_cloudredirect_on_the_32bit_client_is_unchanged(self):
        self._client(paths.STEAM_CLIENT_32)
        self.patch("check_cloudredirect_installed", lambda: True)
        self.patch("_cloudredirect_kill_switched", lambda: False)
        self.patch("check_cloudredirect_active", lambda: False)
        self.patch("_cloudredirect_log_inspect", lambda: (None, None))
        self.patch("_wrapper_coverage_present", lambda: True)
        self.assertEqual(paths.read_cloudredirect_health()["state"], "not_loaded")


if __name__ == "__main__":
    unittest.main()

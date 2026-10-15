"""The HTTP client never turns certificate verification off.

_make_ssl_context used to end in a CERT_NONE context when no CA bundle was
found anywhere, with a log warning nobody sees: zips, keys, the .so and fixes
would then download from whoever answers. Measured 2026-10-15 in the
codespace: Decky's bundled Python ships certifi and SteamOS has the system
bundle, so that branch never ran there; now it fails closed instead
(nosotros.md §2.12).

    python -m unittest discover -s tests
"""
import os
import ssl
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import http_client  # noqa: E402


class _NoPaths:
    cafile = None
    capath = None


class SslFailClosed(unittest.TestCase):
    def test_no_bundle_anywhere_keeps_verification_on(self):
        with mock.patch.dict(sys.modules, {"certifi": None}), \
             mock.patch.object(http_client, "_SYSTEM_CERT_FILES", []), \
             mock.patch.object(http_client.ssl, "get_default_verify_paths", return_value=_NoPaths()):
            ctx = http_client._make_ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_normal_path_keeps_verification_on(self):
        ctx = http_client._make_ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_no_cert_none_left_in_the_module(self):
        src = open(http_client.__file__, encoding="utf-8").read()
        self.assertNotIn("CERT_NONE", src)
        self.assertNotIn("check_hostname = False", src)


if __name__ == "__main__":
    unittest.main()

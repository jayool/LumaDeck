"""Credential files are written 0600 and tightened on load.

credentials.json (Hubcap key, Ryuu cookie, LuaTools session), api.json (Hubcap
key in the URL), ryuu_cookie.txt and luatools_session.json were written with
open("w") by the backend, which runs as root: 0644 under the usual umask, so
any process running as `deck` could read them (nosotros.md §2.10).

    python -m unittest discover -s tests
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import api_manifest  # noqa: E402
import luatools_auth  # noqa: E402
import utils  # noqa: E402


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


class WritePrivateText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_umask = os.umask(0o022)

    def tearDown(self):
        os.umask(self.old_umask)

    def test_new_file_is_0600(self):
        p = os.path.join(self.tmp, "c.json")
        utils.write_private_text(p, "{}")
        self.assertEqual(_mode(p), 0o600)
        with open(p) as fh:
            self.assertEqual(fh.read(), "{}")

    def test_existing_0644_file_is_tightened_and_rewritten(self):
        p = os.path.join(self.tmp, "c.json")
        with open(p, "w") as fh:
            fh.write("old")
        os.chmod(p, 0o644)
        utils.write_private_text(p, "new")
        self.assertEqual(_mode(p), 0o600)
        with open(p) as fh:
            self.assertEqual(fh.read(), "new")

    def test_make_private(self):
        p = os.path.join(self.tmp, "c.json")
        self.assertFalse(utils.make_private(p))  # missing: no error
        with open(p, "w") as fh:
            fh.write("x")
        os.chmod(p, 0o644)
        self.assertTrue(utils.make_private(p))
        self.assertEqual(_mode(p), 0o600)
        self.assertFalse(utils.make_private(p))  # already private: unchanged


class CredentialWriters(unittest.TestCase):
    """Every writer goes through write_private_text: the files land 0600."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings = os.path.join(self.tmp, "settings")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.settings)
        os.makedirs(self.data)
        self.old_umask = os.umask(0o022)
        self.patches = [
            mock.patch("paths.settings_dir", return_value=self.settings),
            mock.patch("paths.data_path", side_effect=lambda n: os.path.join(self.data, n)),
            mock.patch.object(api_manifest, "data_path", side_effect=lambda n: os.path.join(self.data, n)),
            mock.patch.object(luatools_auth, "data_path", side_effect=lambda n: os.path.join(self.data, n)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        os.umask(self.old_umask)

    def test_cred_store_ryuu_cookie_and_luatools_session(self):
        api_manifest.save_ryu_cookie("abc")
        luatools_auth._save_session({"access_token": "t"})
        for name in ("ryuu_cookie.txt", "luatools_session.json"):
            self.assertEqual(_mode(os.path.join(self.data, name)), 0o600, name)
        store = os.path.join(self.settings, "credentials.json")
        self.assertEqual(_mode(store), 0o600)
        with open(store) as fh:
            self.assertEqual(json.load(fh)["ryuu_cookie"], "session=abc")

    def test_api_json_with_hubcap_key(self):
        p = os.path.join(self.data, "api.json")
        with open(p, "w") as fh:
            json.dump({"api_list": [dict(a) for a in api_manifest.DEFAULT_API_LIST]}, fh)
        os.chmod(p, 0o644)
        api_manifest.update_hubcap_key("k" * 32)
        self.assertEqual(_mode(p), 0o600)
        with open(p) as fh:
            self.assertIn("k" * 32, fh.read())

    def test_tighten_on_load_fixes_old_files(self):
        for p in api_manifest.credential_files():
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write("{}")
            os.chmod(p, 0o644)
        self.assertEqual(api_manifest.tighten_credential_files(), 4)
        for p in api_manifest.credential_files():
            self.assertEqual(_mode(p), 0o600, p)
        self.assertEqual(api_manifest.tighten_credential_files(), 0)


if __name__ == "__main__":
    unittest.main()

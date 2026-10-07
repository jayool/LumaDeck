"""Saving an empty Hubcap key removes it (measured 2026-10-07: Settings
refused an empty key, so the only way to drop a Hubcap key was editing two
files by hand, and leaving either one restored it on the next plugin load).
Removal strips the key from api.json, disables the Hubcap entry (a keyless
request only earns a 401 and a misleading "key expired" row), and forgets the
settings-store mirror; saving a key again re-enables the entry.

    python -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import api_manifest  # noqa: E402


class HubcapKeyRemoval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = os.path.join(self.tmp, "credentials.json")
        self.api = os.path.join(self.tmp, "api.json")
        mock.patch.object(api_manifest, "_cred_store_path", lambda: self.store).start()
        mock.patch.object(api_manifest, "data_path",
                          lambda name: os.path.join(self.tmp, name)).start()
        self.addCleanup(mock.patch.stopall)
        with open(self.api, "w") as fh:
            json.dump({"api_list": [
                {"name": "Morrenus", "url": "https://hubcapmanifest.com/api/v1/manifest/<appid>?api_key=<moapikey>",
                 "success_code": 200, "unavailable_code": 404, "enabled": True},
                {"name": "Forced Ryu (Cookie)", "url": "https://generator.ryuu.lol/download?appid=<appid>&file_type=manifest",
                 "success_code": 200, "unavailable_code": 404, "enabled": True},
            ]}, fh)

    def entries(self):
        with open(self.api) as fh:
            return {a["name"]: a for a in json.load(fh)["api_list"]}

    def store_keys(self):
        if not os.path.exists(self.store):
            return set()
        with open(self.store) as fh:
            return set(json.load(fh))

    def test_empty_key_removes_everything(self):
        self.assertTrue(api_manifest.update_hubcap_key("smm_real")["success"])
        self.assertEqual(api_manifest._get_hubcap_key(), "smm_real")
        self.assertIn("hubcap_key", self.store_keys())

        res = api_manifest.update_hubcap_key("   ")
        self.assertTrue(res["success"])
        self.assertTrue(res.get("removed"))
        self.assertEqual(api_manifest._get_hubcap_key(), "")
        hub = self.entries()["Morrenus"]
        self.assertNotIn("api_key", hub["url"])
        self.assertFalse(hub["enabled"])
        self.assertNotIn("hubcap_key", self.store_keys())
        self.assertTrue(self.entries()["Forced Ryu (Cookie)"]["enabled"])

    def test_removed_key_is_not_restored_on_plugin_load(self):
        api_manifest.update_hubcap_key("smm_real")
        api_manifest.update_hubcap_key("")
        api_manifest.restore_credentials_from_settings()
        self.assertEqual(api_manifest._get_hubcap_key(), "")
        self.assertFalse(self.entries()["Morrenus"]["enabled"])

    def test_saving_again_re_enables_hubcap(self):
        api_manifest.update_hubcap_key("smm_real")
        api_manifest.update_hubcap_key("")
        api_manifest.update_hubcap_key("smm_new")
        hub = self.entries()["Morrenus"]
        self.assertTrue(hub["enabled"])
        self.assertEqual(api_manifest._get_hubcap_key(), "smm_new")
        self.assertIn("hubcap_key", self.store_keys())

    def test_disabled_hubcap_is_not_a_download_source(self):
        api_manifest.update_hubcap_key("")
        names = [a["name"] for a in api_manifest.load_api_manifest()]
        self.assertEqual(names, ["Forced Ryu (Cookie)"])


if __name__ == "__main__":
    unittest.main()

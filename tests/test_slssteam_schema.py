"""backend/slssteam_schema.py — the config-key reference and its refresh:
    python -m unittest discover -s tests

Pins: the reference is fetched from upstream's res/config.yaml (plain YAML, the
source the build embeds; the generated src/config_default.hpp left upstream's
git on dev@ae5cbf1), a valid fetch is cached as-is, garbage / a 404 / an
exception leave the cache alone, the bundled snapshot passes the same gate,
and completion appends only the keys the on-disk config lacks.
"""
import asyncio
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import slssteam_schema as ss  # noqa: E402


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class _Client:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.urls = resp, exc, []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        if self.exc:
            raise self.exc
        return self.resp


class Refresh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._cache = ss._CACHE_FILE, ss._CACHE_DIR
        ss._CACHE_DIR = self.tmp
        ss._CACHE_FILE = os.path.join(self.tmp, "ref.yaml")
        import http_client
        self._ensure = http_client.ensure_http_client
        self.addCleanup(lambda: setattr(http_client, "ensure_http_client", self._ensure))
        self.addCleanup(lambda: (setattr(ss, "_CACHE_FILE", self._cache[0]), setattr(ss, "_CACHE_DIR", self._cache[1])))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _client(self, client):
        import http_client
        async def ensure(context=""):
            return client
        http_client.ensure_http_client = ensure
        return client

    def test_fetches_res_config_yaml_and_caches_it_verbatim(self):
        text = ss._BUNDLED_YAML + "\n#A key SLSsteam added later\nNewKey: no\n"
        c = self._client(_Client(_Resp(200, text)))
        self.assertTrue(asyncio.run(ss.refresh_reference_cache()))
        self.assertEqual(c.urls, ["https://raw.githubusercontent.com/AceSLS/SLSsteam/main/res/config.yaml"])
        with open(ss._CACHE_FILE, encoding="utf-8") as f:
            self.assertEqual(f.read(), text)
        self.assertIn("NewKey", ss.present_top_level_keys(ss.load_reference_yaml()))

    def test_404_keeps_cache_and_bundled(self):
        self._client(_Client(_Resp(404, "Not Found")))
        self.assertFalse(asyncio.run(ss.refresh_reference_cache()))
        self.assertFalse(os.path.exists(ss._CACHE_FILE))
        self.assertEqual(ss.load_reference_yaml(), ss._BUNDLED_YAML)

    def test_garbage_is_rejected(self):
        self._client(_Client(_Resp(200, "<html>rate limited</html>")))
        self.assertFalse(asyncio.run(ss.refresh_reference_cache()))
        self.assertFalse(os.path.exists(ss._CACHE_FILE))

    def test_exception_never_raises(self):
        self._client(_Client(exc=RuntimeError("offline")))
        self.assertFalse(asyncio.run(ss.refresh_reference_cache()))
        self.assertEqual(ss.load_reference_yaml(), ss._BUNDLED_YAML)


class Reference(unittest.TestCase):
    def test_bundled_passes_the_gate(self):
        self.assertTrue(ss._looks_like_reference(ss._BUNDLED_YAML))

    def test_completion_appends_only_missing_keys(self):
        on_disk = "PlayNotOwnedGames: yes\nAdditionalApps:\n  - 480\n"
        new, added = ss.complete_config_text(on_disk, ss._BUNDLED_YAML)
        self.assertTrue(new.startswith(on_disk))                 # byte-for-byte prefix
        self.assertNotIn("AdditionalApps", added)
        self.assertIn("SafeMode", added)
        self.assertIn("DenuvoGames", added)
        again, added2 = ss.complete_config_text(new, ss._BUNDLED_YAML)
        self.assertEqual(again, new)                             # idempotent
        self.assertEqual(added2, [])


if __name__ == "__main__":
    unittest.main()

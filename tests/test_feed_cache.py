"""The 15 min feed cache (backend/feed_cache.py) on the status-surface fetchers:
a fresh disk copy is served without touching the network, a stale one is
refetched, `force` always fetches, and a failed fetch falls back to the copy."""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import feed_cache  # noqa: E402
import headcrab_compat as hc  # noqa: E402
import self_update as su  # noqa: E402
import steam_update_gate as gate  # noqa: E402

FEED = "SafeModeHashes:\n  20260922150000:\n    - abc #x\n"


class _NoNetwork:
    """An HTTP client that fails the test if it is ever asked."""
    async def get(self, *a, **k):
        raise AssertionError("network fetch attempted while the cache was fresh")


class _Resp:
    def __init__(self, status, text="", data=None):
        self.status_code = status
        self.text = text
        self._data = data

    def json(self):
        return self._data


class _Client:
    def __init__(self, resp):
        self.resp = resp
        self.calls = 0

    async def get(self, *a, **k):
        self.calls += 1
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


async def _no_network(*a, **k):
    return _NoNetwork()


class FreshTests(unittest.TestCase):
    def test_fresh_is_by_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f")
            self.assertFalse(feed_cache.fresh(p))
            open(p, "w").write("x")
            self.assertTrue(feed_cache.fresh(p))
            _age(p, feed_cache.FEED_TTL + 5)
            self.assertFalse(feed_cache.fresh(p))


class SlssteamFeedTests(unittest.TestCase):
    def test_fresh_copy_skips_the_network(self):
        with tempfile.TemporaryDirectory() as d:
            cache = os.path.join(d, "sls.yaml")
            open(cache, "w").write(FEED)
            with mock.patch.object(gate, "_SLS_CACHE", cache), \
                 mock.patch.object(gate, "ensure_http_client", _no_network):
                self.assertEqual(asyncio.run(gate.slssteam_updates_text()), FEED)

    def test_stale_copy_and_force_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            cache = os.path.join(d, "sls.yaml")
            open(cache, "w").write(FEED)
            client = _Client(_Resp(200, FEED + "    - def #y\n"))

            async def _client(*a, **k):
                return client
            with mock.patch.object(gate, "_SLS_CACHE", cache), \
                 mock.patch.object(gate, "_CACHE_DIR", d), \
                 mock.patch.object(gate, "ensure_http_client", _client):
                asyncio.run(gate.slssteam_updates_text(force=True))
                self.assertEqual(client.calls, 1)
                _age(cache, feed_cache.FEED_TTL + 5)
                asyncio.run(gate.slssteam_updates_text())
                self.assertEqual(client.calls, 2)
                self.assertIn("def", open(cache).read())

    def test_failed_fetch_uses_the_copy_whatever_its_age(self):
        with tempfile.TemporaryDirectory() as d:
            cache = os.path.join(d, "sls.yaml")
            open(cache, "w").write(FEED)
            _age(cache, 10 * feed_cache.FEED_TTL)
            client = _Client(OSError("offline"))

            async def _client(*a, **k):
                return client
            with mock.patch.object(gate, "_SLS_CACHE", cache), \
                 mock.patch.object(gate, "ensure_http_client", _client):
                self.assertEqual(asyncio.run(gate.slssteam_updates_text()), FEED)


class HeadcrabFeedTests(unittest.TestCase):
    def test_fresh_copies_skip_the_network(self):
        with tempfile.TemporaryDirectory() as d:
            tgt, ll, grp = (os.path.join(d, n) for n in ("t", "ll", "g"))
            open(tgt, "w").write("1788652215")
            open(ll, "w").write(FEED)
            open(grp, "w").write("20260922150000")
            with mock.patch.object(hc, "_CACHE_FILE", tgt), \
                 mock.patch.object(hc, "_LL_CACHE_FILE", ll), \
                 mock.patch.object(hc, "_REL_GROUP_CACHE_FILE", grp), \
                 mock.patch.object(hc, "ensure_http_client", _no_network):
                self.assertEqual(asyncio.run(hc.headcrab_target()), 1788652215)
                self.assertEqual(asyncio.run(hc._lumalinux_updates_text()), FEED)
                self.assertEqual(asyncio.run(hc.latest_release_group()), "20260922150000")

    def test_force_fetches_even_when_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            tgt = os.path.join(d, "t")
            open(tgt, "w").write("1788652215")
            client = _Client(_Resp(200, "HeadcrabCompatibleClientVer=1791918634\n"))

            async def _client(*a, **k):
                return client
            with mock.patch.object(hc, "_CACHE_FILE", tgt), \
                 mock.patch.object(hc, "_CACHE_DIR", d), \
                 mock.patch.object(hc, "ensure_http_client", _client):
                self.assertEqual(asyncio.run(hc.headcrab_target(force=True)), 1791918634)
                self.assertEqual(client.calls, 1)
                self.assertEqual(open(tgt).read(), "1791918634")


class PluginReleaseTests(unittest.TestCase):
    def _run(self, d, client, force=False, installed="0.11.3"):
        async def _client(*a, **k):
            return client
        with mock.patch.object(su, "_release_cache_path", lambda: os.path.join(d, "plugin_release.json")), \
             mock.patch.object(su, "_installed_version", lambda: installed), \
             mock.patch.object(su, "ensure_http_client", _client):
            return asyncio.run(su.check_plugin_update(force=force))

    def test_fetch_writes_the_cache_and_a_fresh_cache_skips_the_network(self):
        with tempfile.TemporaryDirectory() as d:
            data = {"tag_name": "v0.12.0",
                    "assets": [{"name": "LumaDeck.zip", "browser_download_url": "https://x/LumaDeck.zip"}]}
            client = _Client(_Resp(200, data=data))
            r = self._run(d, client)
            self.assertTrue(r["success"] and r["has_update"] and r["latest"] == "0.12.0")
            self.assertEqual(client.calls, 1)
            cached = json.load(open(os.path.join(d, "plugin_release.json")))
            self.assertEqual(cached["tag"], "v0.12.0")
            r2 = self._run(d, _NoNetwork())
            self.assertEqual(r2["latest"], "0.12.0")
            self.assertTrue(r2["has_update"])

    def test_failed_fetch_falls_back_to_the_cache(self):
        with tempfile.TemporaryDirectory() as d:
            json.dump({"tag": "v0.11.3", "download_url": "https://x/LumaDeck.zip"},
                      open(os.path.join(d, "plugin_release.json"), "w"))
            _age(os.path.join(d, "plugin_release.json"), 10 * feed_cache.FEED_TTL)
            r = self._run(d, _Client(OSError("offline")))
            self.assertTrue(r["success"])
            self.assertEqual(r["latest"], "0.11.3")
            self.assertFalse(r["has_update"])

    def test_no_cache_and_no_network_reports_failure(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run(d, _Client(OSError("offline")))
            self.assertFalse(r["success"])


if __name__ == "__main__":
    unittest.main()


class ClientHashTests(unittest.TestCase):
    """current_client_hash keeps the sha256 of steamclient.so on disk, keyed by
    (path, size, mtime): a new backend process reuses it without reading the
    40 MB file, and a changed file (a Steam update) is hashed again."""

    def _setup(self, d, body=b"steamclient"):
        root = os.path.join(d, "steam")
        os.makedirs(os.path.join(root, "ubuntu12_32"))
        so = os.path.join(root, "ubuntu12_32", "steamclient.so")
        open(so, "wb").write(body)
        return root, so

    def test_disk_copy_is_reused_by_a_fresh_process(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            root, so = self._setup(d)
            cache = os.path.join(d, "client_hash.json")
            with mock.patch.object(gate, "find_steam_root", lambda: root), \
                 mock.patch.object(gate, "_HASH_CACHE_FILE", cache), \
                 mock.patch.object(gate, "_CACHE_DIR", d), \
                 mock.patch.dict(gate._HASH_CACHE, {}, clear=True):
                sha = gate.current_client_hash()
                self.assertEqual(sha, hashlib.sha256(b"steamclient").hexdigest())
                self.assertEqual(json.load(open(cache))["sha256"], sha)
                # A fresh process: empty memory cache, and the file must not be read.
                gate._HASH_CACHE.clear()
                real_open = open

                def guarded_open(path, *a, **k):
                    if str(path) == so:
                        raise AssertionError("steamclient.so was hashed again")
                    return real_open(path, *a, **k)
                with mock.patch("builtins.open", guarded_open):
                    self.assertEqual(gate.current_client_hash(), sha)

    def test_a_changed_file_is_hashed_again(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            root, so = self._setup(d)
            cache = os.path.join(d, "client_hash.json")
            with mock.patch.object(gate, "find_steam_root", lambda: root), \
                 mock.patch.object(gate, "_HASH_CACHE_FILE", cache), \
                 mock.patch.object(gate, "_CACHE_DIR", d), \
                 mock.patch.dict(gate._HASH_CACHE, {}, clear=True):
                gate.current_client_hash()
                open(so, "wb").write(b"a newer steamclient")
                _age(so, -5)  # a later mtime, as an update would leave
                gate._HASH_CACHE.clear()
                self.assertEqual(gate.current_client_hash(),
                                 hashlib.sha256(b"a newer steamclient").hexdigest())
                self.assertEqual(json.load(open(cache))["size"], len(b"a newer steamclient"))

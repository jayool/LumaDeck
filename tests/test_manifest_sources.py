"""manifests.resolve_manifest: the order of the online sources (RESEARCH §19.4,
updated 2026-10-07 when P-ToyStore vanished):

    depotcache -> own archive -> luastools -> Hubcap single manifest -> Hubcap zip

The single manifest (`/generate/manifest`, `single` quota) needs the Hubcap
key from api.json, is tried once per depot+gid per day, and serves any gid;
the zip only the current one. Network stubbed, Steam root in a temp dir.

    python -m unittest discover -s tests
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import api_manifest  # noqa: E402
import manifests  # noqa: E402

APP, DEPOT, GID = 1942280, 1942281, 2046527723717816735
HUBCAP = {"name": "Morrenus", "url": "https://hubcapmanifest.com/api/v1/manifest/<appid>?api_key=k3y", "enabled": True}


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def fake_manifest(depot=DEPOT, gid=GID):
    """A plain depotcache manifest: empty payload block, then the metadata
    block carrying depot (field 1) and gid (field 2)."""
    import struct
    meta = b"\x08" + _varint(depot) + b"\x10" + _varint(gid)
    return (manifests.MANIFEST_MAGIC + struct.pack("<I", 0)
            + struct.pack("<II", 0x1F4812BE, len(meta)) + meta)


class FakeResp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


class FakeClient:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    async def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers or {}))
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return FakeResp(404)


class ManifestSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.depotcache = os.path.join(self.tmp, "depotcache")
        os.makedirs(self.depotcache)
        self.client = FakeClient({})
        self.apis = [dict(HUBCAP)]
        self.zip_calls = []
        self._orig = []

        def patch(mod, name, value):
            self._orig.append((mod, name, getattr(mod, name)))
            setattr(mod, name, value)

        async def client(_ctx=""):
            return self.client

        async def zip_stub(appid, **kw):
            self.zip_calls.append(appid)
            return None
        patch(manifests, "ensure_http_client", client)
        patch(manifests, "get_depotcache_dir", lambda steam_root=None: self.depotcache)
        patch(manifests, "_DATA_ROOT", os.path.join(self.tmp, "data"))
        patch(manifests, "_HUBCAP_ATTEMPTS", os.path.join(self.tmp, "attempts.json"))
        patch(manifests, "fetch_game_zip", zip_stub)
        patch(api_manifest, "load_api_manifest", lambda: self.apis)

    def tearDown(self):
        for mod, name, value in self._orig:
            setattr(mod, name, value)

    def resolve(self, **kw):
        return asyncio.run(manifests.resolve_manifest(APP, DEPOT, GID, **kw))

    def urls(self):
        return [u for u, _ in self.client.calls]

    def test_luastools_first_then_hubcap_single_then_zip(self):
        self.client.routes = {"/generate/manifest?": FakeResp(200, fake_manifest())}
        path, source = self.resolve(current_gid=GID)
        self.assertEqual(source, "hubcap-single")
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.path.isfile(os.path.join(manifests.archive_dir(APP), manifests.manifest_name(DEPOT, GID))))
        self.assertIn("manifest.luastools.xyz", self.urls()[0])
        single = self.urls()[1]
        self.assertTrue(single.startswith("https://hubcapmanifest.com/api/v1/generate/manifest?"))
        self.assertIn(f"depot_id={DEPOT}", single)
        self.assertIn(f"manifest_id={GID}", single)
        self.assertEqual(self.client.calls[1][1].get("Authorization"), "Bearer k3y")
        self.assertNotIn("api_key", single)
        self.assertEqual(self.zip_calls, [], "the zip is the last resort")

    def test_luastools_hit_asks_hubcap_nothing(self):
        self.client.routes = {"manifest.luastools.xyz": FakeResp(200, fake_manifest())}
        path, source = self.resolve(current_gid=GID)
        self.assertEqual(source, "luastools")
        self.assertEqual(len(self.client.calls), 1)

    def test_single_serves_an_old_build_the_zip_cannot(self):
        self.client.routes = {"/generate/manifest?": FakeResp(200, fake_manifest())}
        path, source = self.resolve(current_gid=GID + 1)
        self.assertEqual(source, "hubcap-single")
        self.assertEqual(self.zip_calls, [])

    def test_no_hubcap_key_skips_the_single_and_still_tries_the_zip(self):
        self.apis[0]["url"] = "https://hubcapmanifest.com/api/v1/manifest/<appid>"
        path, why = self.resolve(current_gid=GID)
        self.assertIsNone(path)
        self.assertIn("no Hubcap key", why)
        self.assertEqual(len(self.client.calls), 1, "only luastools was asked")
        self.assertEqual(self.zip_calls, [APP])

    def test_one_single_attempt_per_depot_gid_per_day(self):
        self.client.routes = {"/generate/manifest?": FakeResp(500)}
        path, why = self.resolve(current_gid=GID + 1)
        self.assertIsNone(path)
        self.assertIn("could not generate", why)
        n = len(self.client.calls)
        path, why = self.resolve(current_gid=GID + 1)
        self.assertIn("already tried today", why)
        self.assertEqual(len(self.client.calls), n + 1, "luastools again, Hubcap single not")
        # Another gid of the same depot has its own budget.
        with open(manifests._HUBCAP_ATTEMPTS) as fh:
            data = json.load(fh)
        self.assertIn(f"single:{DEPOT}_{GID}", data)
        self.assertTrue(manifests.hubcap_single_budget_ok(DEPOT, GID + 1))

    def test_single_body_for_another_gid_is_rejected(self):
        self.client.routes = {"/generate/manifest?": FakeResp(200, fake_manifest(gid=GID + 7))}
        path, why = self.resolve(current_gid=GID + 1)
        self.assertIsNone(path)
        self.assertIn("could not generate", why)
        self.assertFalse(os.listdir(self.depotcache))

    def test_allow_hubcap_false_gates_the_zip_not_the_single(self):
        # pins.py resolves the INSTALLED build's manifests with allow_hubcap=False
        # (the zip only has the current build); the single manifest serves it.
        self.client.routes = {"/generate/manifest?": FakeResp(200, fake_manifest())}
        path, source = self.resolve(allow_hubcap=False, current_gid=GID)
        self.assertEqual(source, "hubcap-single")
        self.assertEqual(self.zip_calls, [])
        self.client.routes = {}
        self.client.calls.clear()
        os.remove(path)
        os.remove(os.path.join(manifests.archive_dir(APP), manifests.manifest_name(DEPOT, GID)))
        os.remove(manifests._HUBCAP_ATTEMPTS)
        path, why = self.resolve(allow_hubcap=False, current_gid=GID)
        self.assertIsNone(path)
        self.assertIn("could not generate", why)
        self.assertEqual(self.zip_calls, [], "no zip without allow_hubcap")


if __name__ == "__main__":
    unittest.main()

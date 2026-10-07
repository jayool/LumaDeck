"""ryuu_cookie: a Ryuu `session` cookie is not a login. generator.ryuu.lol sets
it on the first page load, before the Discord login (measured 2026-10-07: the
imported cookie got 403 "You must be logged in to download."). connect_ryuu
must keep waiting while the browser holds that anonymous session, and only
save a cookie whose home page carries the user marker; the manual import must
refuse an anonymous one.

    python -m unittest discover -s tests
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import api_manifest  # noqa: E402
import ryuu_cookie  # noqa: E402

ANON_HTML = "<script>const el = document.querySelector('#u'); el.getAttribute('data-user-id');</script>"
LOGGED_HTML = '<div id="u" data-user-id="123456789012345678"></div>' + ANON_HTML


class Marker(unittest.TestCase):
    def test_anonymous_page_has_the_string_only_inside_the_script(self):
        self.assertFalse(ryuu_cookie._html_shows_login(ANON_HTML))

    def test_logged_in_page_carries_the_attribute(self):
        self.assertTrue(ryuu_cookie._html_shows_login(LOGGED_HTML))

    def test_empty_attribute_is_not_a_login(self):
        self.assertFalse(ryuu_cookie._html_shows_login('<div data-user-id=""></div>'))


class ConnectRyuu(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.harvests = []
        self.verdicts = {}
        self.checks = []
        self._orig = []

        def patch(mod, name, value):
            self._orig.append((mod, name, getattr(mod, name)))
            setattr(mod, name, value)

        def harvest():
            return self.harvests.pop(0) if self.harvests else None

        def check(value):
            self.checks.append(value)
            return self.verdicts.get(value)

        self.real_sleep = asyncio.sleep

        async def nosleep(_s):
            await self.real_sleep(0)
        patch(ryuu_cookie, "_harvest_ryuu_once", harvest)
        patch(ryuu_cookie, "_session_logged_in", check)
        patch(ryuu_cookie.asyncio, "sleep", nosleep)
        patch(api_manifest, "save_ryu_cookie", lambda v: self.saved.append(v))
        patch(api_manifest, "save_ryu_cookie_expiry", lambda iso: None)

    def tearDown(self):
        for mod, name, value in self._orig:
            setattr(mod, name, value)

    def test_anonymous_session_is_not_saved_login_is(self):
        self.harvests = [("anon", None), ("anon", None), ("logged", "2026-11-06T00:00:00")]
        self.verdicts = {"anon": False, "logged": True}
        res = asyncio.run(ryuu_cookie.connect_ryuu(timeout_s=5))
        self.assertTrue(res["success"], res)
        self.assertEqual(self.saved, ["logged"])
        self.assertEqual(self.checks, ["anon", "logged"], "each cookie value is checked once")

    def test_unverifiable_session_is_saved_as_before(self):
        self.harvests = [("v", None)]
        self.verdicts = {"v": None}
        res = asyncio.run(ryuu_cookie.connect_ryuu(timeout_s=5))
        self.assertTrue(res["success"])
        self.assertEqual(self.saved, ["v"])

    def test_cancel_while_anonymous(self):
        self.harvests = [("anon", None)] * 50
        self.verdicts = {"anon": False}

        async def run():
            task = asyncio.ensure_future(ryuu_cookie.connect_ryuu(timeout_s=5))
            await self.real_sleep(0.05)
            ryuu_cookie.cancel_connect_ryuu()
            return await task
        res = asyncio.run(run())
        self.assertFalse(res["success"])
        self.assertTrue(res.get("cancelled"))
        self.assertEqual(self.saved, [])


if __name__ == "__main__":
    unittest.main()

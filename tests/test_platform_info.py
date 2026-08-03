"""Characterization + unit tests for backend/platform_info.py.

The SteamOS cases are the non-regression guardrail: they pin the values the
plugin resolved by hardcoding before platform_info existed. If a SteamOS
assertion here changes, the Steam Deck path has regressed — treat it as a red
alarm, not a test to "update".

Pure `_*` helpers are tested with fixtures, so this runs anywhere:
    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import platform_info as p  # noqa: E402


STEAMOS_OSR = """\
NAME="SteamOS"
ID=steamos
ID_LIKE=arch
PRETTY_NAME="SteamOS Holo"
VERSION_ID=3.7
"""

CACHYOS_OSR = """\
NAME="CachyOS"
# a comment line
ID=cachyos
ID_LIKE=arch
PRETTY_NAME="CachyOS"
"""

UBUNTU_OSR = """\
NAME="Ubuntu"
ID=ubuntu
ID_LIKE=debian
"""

BAZZITE_OSR = """\
NAME="Bazzite"
ID=bazzite
ID_LIKE="fedora"
"""

VOID_OSR = """\
NAME="Void"
ID=void
"""

ARCH_OSR = """\
NAME="Arch Linux"
ID=arch
"""


class TestOsRelease(unittest.TestCase):
    def test_parse_strips_quotes_and_comments(self):
        osr = p._parse_os_release(STEAMOS_OSR)
        self.assertEqual(osr["ID"], "steamos")
        self.assertEqual(osr["NAME"], "SteamOS")  # quotes stripped
        self.assertEqual(osr["ID_LIKE"], "arch")

    def test_parse_skips_comments_and_blanks(self):
        osr = p._parse_os_release(CACHYOS_OSR)
        self.assertEqual(osr["ID"], "cachyos")
        self.assertNotIn("# a comment line", osr)

    def test_distro_id(self):
        self.assertEqual(p._distro_id(p._parse_os_release(STEAMOS_OSR)), "steamos")
        self.assertEqual(p._distro_id(p._parse_os_release(CACHYOS_OSR)), "cachyos")

    def test_distro_id_empty_defaults_to_steamos(self):
        # Unknown / unreadable os-release => SteamOS identity (non-regression).
        self.assertEqual(p._distro_id({}), "steamos")
        self.assertEqual(p._distro_id({"ID": ""}), "steamos")

    def test_arch_like(self):
        self.assertTrue(p._is_arch_like(p._parse_os_release(STEAMOS_OSR)))
        self.assertTrue(p._is_arch_like(p._parse_os_release(CACHYOS_OSR)))
        self.assertTrue(p._is_arch_like({"ID": "arch"}))
        self.assertFalse(p._is_arch_like(p._parse_os_release(UBUNTU_OSR)))


class TestDistroPredicates(unittest.TestCase):
    """1:1 parity with headcrab.sh's steamoscheck/cachyoscheck/bazzitecheck/
    voidcheck/archcheck/debiancheck."""

    def test_exact_id_predicates(self):
        steamos = p._parse_os_release(STEAMOS_OSR)
        cachyos = p._parse_os_release(CACHYOS_OSR)
        bazzite = p._parse_os_release(BAZZITE_OSR)
        void = p._parse_os_release(VOID_OSR)

        self.assertTrue(p._is_steamos(steamos))
        self.assertTrue(p._is_cachyos(cachyos))
        self.assertTrue(p._is_bazzite(bazzite))
        self.assertTrue(p._is_void(void))

        # Mutually exclusive on the exact-ID checks.
        self.assertFalse(p._is_cachyos(steamos))
        self.assertFalse(p._is_steamos(cachyos))
        self.assertFalse(p._is_bazzite(void))

    def test_arch_like_via_id_or_id_like(self):
        # cachyos matches archcheck via its own token; steamos via ID_LIKE=arch.
        self.assertTrue(p._is_arch_like(p._parse_os_release(CACHYOS_OSR)))
        self.assertTrue(p._is_arch_like(p._parse_os_release(STEAMOS_OSR)))
        self.assertTrue(p._is_arch_like(p._parse_os_release(ARCH_OSR)))
        self.assertFalse(p._is_arch_like(p._parse_os_release(BAZZITE_OSR)))
        self.assertFalse(p._is_arch_like(p._parse_os_release(UBUNTU_OSR)))

    def test_debian_like(self):
        self.assertTrue(p._is_debian_like(p._parse_os_release(UBUNTU_OSR)))
        self.assertTrue(p._is_debian_like({"ID": "debian"}))
        self.assertFalse(p._is_debian_like(p._parse_os_release(CACHYOS_OSR)))


class TestRealUser(unittest.TestCase):
    def test_steamos_root_backend_resolves_deck(self):
        # SteamOS characterization: Decky as root, no SUDO_USER, uid 1000 == deck.
        self.assertEqual(p._resolve_real_user({}, "deck", euid=0), "deck")

    def test_root_backend_resolves_uid1000_on_other_distro(self):
        self.assertEqual(p._resolve_real_user({}, "jayo", euid=0), "jayo")

    def test_sudo_user_wins(self):
        self.assertEqual(p._resolve_real_user({"SUDO_USER": "alice"}, "deck", euid=0), "alice")

    def test_sudo_user_root_is_ignored(self):
        self.assertEqual(p._resolve_real_user({"SUDO_USER": "root"}, "bob", euid=0), "bob")

    def test_non_root_trusts_login_env(self):
        self.assertEqual(p._resolve_real_user({"LOGNAME": "alice"}, None, euid=1000), "alice")
        self.assertEqual(p._resolve_real_user({"USER": "carol"}, None, euid=1000), "carol")

    def test_last_resort_is_deck(self):
        self.assertEqual(p._resolve_real_user({}, None, euid=0), "deck")


class TestRealUid(unittest.TestCase):
    def test_valid_uid_passthrough(self):
        self.assertEqual(p._resolve_real_uid(1000), 1000)   # SteamOS: deck
        self.assertEqual(p._resolve_real_uid(1001), 1001)
        self.assertEqual(p._resolve_real_uid(0), 0)

    def test_invalid_falls_back_to_1000(self):
        self.assertEqual(p._resolve_real_uid(None), 1000)
        self.assertEqual(p._resolve_real_uid(-1), 1000)
        self.assertEqual(p._resolve_real_uid("nope"), 1000)


class TestRealHome(unittest.TestCase):
    def test_prefers_passwd_home(self):
        self.assertEqual(p._resolve_real_home("deck", "/home/deck", {}), "/home/deck")

    def test_ignores_root_home_env(self):
        # Decky-as-root: $HOME is /root; must not leak into the real user's home.
        self.assertEqual(p._resolve_real_home("jayo", None, {"HOME": "/root"}), "/home/jayo")

    def test_uses_home_env_when_not_root(self):
        self.assertEqual(p._resolve_real_home("alice", None, {"HOME": "/home/alice"}), "/home/alice")

    def test_falls_back_to_home_slash_user(self):
        self.assertEqual(p._resolve_real_home("bob", None, {}), "/home/bob")


class TestSteamFlavor(unittest.TestCase):
    def test_native_wins(self):
        self.assertEqual(p._detect_steam_flavor(native_exists=True, flatpak_exists=True), "native")

    def test_flatpak_only(self):
        self.assertEqual(p._detect_steam_flavor(native_exists=False, flatpak_exists=True), "flatpak")

    def test_unknown_defaults_native(self):
        self.assertEqual(p._detect_steam_flavor(native_exists=False, flatpak_exists=False), "native")


class TestSession(unittest.TestCase):
    def test_family_steamos(self):
        self.assertEqual(p._session_family("steamos"), "steamos")

    def test_family_cachyos(self):
        self.assertEqual(p._session_family("cachyos"), "cachyos")

    def test_family_unknown(self):
        self.assertEqual(p._session_family("ubuntu"), "unknown")

    def test_gamescope_running(self):
        self.assertTrue(p._gamescope_running(["systemd\n", "gamescope\n", "steam\n"]))
        self.assertFalse(p._gamescope_running(["systemd\n", "steam\n"]))


class TestSteamOsNonRegressionSummary(unittest.TestCase):
    """The whole-summary guardrail: a simulated SteamOS box must resolve to the
    exact facts the plugin hardcoded before this module."""

    def test_summary_shape_on_steamos_like_inputs(self):
        # Drive the pure helpers with SteamOS inputs and assert the canonical
        # values. (summary() itself reads the real system; here we assert the
        # building blocks it composes.)
        osr = p._parse_os_release(STEAMOS_OSR)
        self.assertEqual(p._distro_id(osr), "steamos")
        self.assertEqual(p._resolve_real_user({}, "deck", euid=0), "deck")
        self.assertEqual(p._resolve_real_home("deck", "/home/deck", {}), "/home/deck")
        self.assertEqual(p._detect_steam_flavor(True, False), "native")
        self.assertEqual(p._session_family("steamos"), "steamos")


if __name__ == "__main__":
    unittest.main()

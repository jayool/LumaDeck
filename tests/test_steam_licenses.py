"""steam_licenses: Steam's packageinfo.vdf → the AppIDs the account has.

The fixture is built here in the exact binary layout Steam writes (measured
on a real v28 file, 2026-10-06): magic, universe, then per package the id,
20-byte SHA, change number, PICS token, a binary KeyValue tree rooted in a
node named after the package, and the document terminator.

    python -m unittest discover -s tests
"""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import steam_licenses  # noqa: E402


def kv_node(name: str, children: bytes) -> bytes:
    return b"\x00" + name.encode() + b"\x00" + children + b"\x08"


def kv_int(name: str, value: int) -> bytes:
    return b"\x02" + name.encode() + b"\x00" + struct.pack("<i", value)


def kv_str(name: str, value: str) -> bytes:
    return b"\x01" + name.encode() + b"\x00" + value.encode() + b"\x00"


def package(pid: int, appids, billingtype=10, extra=b"") -> bytes:
    apps = b"".join(kv_int(str(i), a) for i, a in enumerate(appids))
    body = (kv_int("packageid", pid) + kv_int("billingtype", billingtype)
            + kv_node("appids", apps) + kv_node("depotids", b"") + extra)
    tree = kv_node(str(pid), body) + b"\x08"          # root node + document terminator
    return struct.pack("<I", pid) + b"\x00" * 20 + struct.pack("<I", 7) + struct.pack("<Q", 0) + tree


def packageinfo(*packages: bytes, version=0x28) -> bytes:
    return struct.pack("<II", 0x06565500 | version, 1) + b"".join(packages) + struct.pack("<I", 0xFFFFFFFF)


class ParsePackageinfo(unittest.TestCase):
    def test_apps_per_package_including_package_zero(self):
        data = packageinfo(
            package(0, [5, 7, 8, 440, 480], billingtype=0),
            package(33877, [262060]),
            package(95029, [445700], billingtype=12,
                    extra=kv_node("extended", kv_str("name", "x") + kv_int("freeondemand", 1))),
        )
        pk = steam_licenses.parse_packageinfo(data)
        self.assertEqual(set(pk), {0, 33877, 95029})
        self.assertEqual(pk[0], {5, 7, 8, 440, 480})
        self.assertEqual(pk[33877], {262060})
        self.assertEqual(pk[95029], {445700})

    def test_older_header_without_token(self):
        pkg = package(33877, [262060])
        # strip the 8-byte token from the header for a v27 file
        pkg = pkg[:4 + 20 + 4] + pkg[4 + 20 + 4 + 8:]
        pk = steam_licenses.parse_packageinfo(packageinfo(pkg, version=0x27))
        self.assertEqual(pk[33877], {262060})

    def test_not_a_packageinfo(self):
        with self.assertRaises(ValueError):
            steam_licenses.parse_packageinfo(b"VDF\x00" * 8)


class LicensedAppids(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "packageinfo.vdf")
        self._orig = steam_licenses.packageinfo_path
        steam_licenses.packageinfo_path = lambda: self.path
        steam_licenses._cache.update({"path": "", "mtime": -1.0, "size": -1, "apps": set()})

    def tearDown(self):
        steam_licenses.packageinfo_path = self._orig

    def test_owned_free_and_package_zero_count_added_does_not(self):
        with open(self.path, "wb") as fh:
            fh.write(packageinfo(package(0, [440, 480], billingtype=0), package(33877, [262060])))
        self.assertTrue(steam_licenses.is_licensed(262060))   # bought
        self.assertTrue(steam_licenses.is_licensed(440))      # free, package 0
        self.assertFalse(steam_licenses.is_licensed(1942280)) # added by LumaDeck: in no package
        self.assertFalse(steam_licenses.is_licensed(580100))  # paid DLC the account lacks

    def test_unreadable_file_means_nothing_licensed(self):
        with open(self.path, "wb") as fh:
            fh.write(b"\x28\x55\x56\x06\x01\x00\x00\x00" + b"\xff" * 40)
        self.assertEqual(steam_licenses.licensed_appids(), set())

    def test_cache_follows_the_file(self):
        with open(self.path, "wb") as fh:
            fh.write(packageinfo(package(33877, [262060])))
        self.assertTrue(steam_licenses.is_licensed(262060))
        with open(self.path, "wb") as fh:                      # the game got refunded
            fh.write(packageinfo(package(0, [480], billingtype=0)) + b"\x00")  # size changes
        self.assertFalse(steam_licenses.is_licensed(262060))

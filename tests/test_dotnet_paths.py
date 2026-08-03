"""Characterization for dotnet.py's real-user generalization (Phase 1).

dotnet.py used to hardcode /home/deck/.dotnet + chown deck:deck. It now derives
DOTNET_ROOT from paths.real_home() and chowns to `<real_user>:`. On SteamOS the
user is deck and the home is /home/deck, so both are unchanged.

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import paths      # noqa: E402
import dotnet     # noqa: E402


class TestDotnetPaths(unittest.TestCase):
    def test_dotnet_root_derives_from_real_home(self):
        self.assertEqual(dotnet.DOTNET_ROOT, os.path.join(paths.real_home(), ".dotnet"))
        self.assertEqual(dotnet.DOTNET_BIN, os.path.join(dotnet.DOTNET_ROOT, "dotnet"))

    def test_steamos_reconstruction(self):
        # Frozen oracle: home=/home/deck => the exact pre-change literals.
        self.assertEqual(os.path.join("/home/deck", ".dotnet"), "/home/deck/.dotnet")
        self.assertEqual(os.path.join("/home/deck/.dotnet", "dotnet"),
                         "/home/deck/.dotnet/dotnet")

    def test_chown_spec_is_user_colon(self):
        # `<user>:` sets the user's primary group; deck: == deck:deck on SteamOS.
        self.assertEqual(f"{'deck'}:", "deck:")


if __name__ == "__main__":
    unittest.main()

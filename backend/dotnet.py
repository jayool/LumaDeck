"""Auto-install .NET 9 runtime when missing.

Ports the install logic from niwia/ASSella (src/utils/helpers.py:_install_dotnet_9_linux)
with three adaptations for LumaDeck:

  1. Path hardcoded to /home/deck/.dotnet. LumaDeck runs as root via Decky's
     `_root` flag; os.path.expanduser("~/.dotnet") would resolve to /root/.dotnet,
     which neither LumaDeck nor ACCELA look at later.
  2. HOME=/home/deck is forced in the subprocess env so dotnet-install.sh's
     internal $HOME-based path resolution targets the user's home, not root's.
  3. chown -R deck:deck after install so the resulting tree is owned by the
     user. Otherwise the files end up owned by root and the user couldn't
     update or replace them without sudo.

End state: /home/deck/.dotnet/dotnet exists, owned by deck:deck. ACCELA's
own get_dotnet_path() points at the same location, so the two tools find
each other's installs transparently.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

from subprocess_env import clean_env

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


DOTNET_ROOT = "/home/deck/.dotnet"
DOTNET_BIN = "/home/deck/.dotnet/dotnet"
DECK_USER = "deck"
DECK_GROUP = "deck"
DOTNET_INSTALL_URL = "https://dot.net/v1/dotnet-install.sh"


def find_dotnet_path() -> Optional[str]:
    """Return the path to a working .NET 9 binary, or None.

    Checks the system PATH plus our deployed location, and validates each
    candidate by running `dotnet --list-runtimes` and looking for the
    "Microsoft.NETCore.App 9." signature. Accepts only .NET 9 — older or
    newer major versions are ignored, matching ASSella's gate.
    """
    candidates: list[str] = []

    system_dotnet = shutil.which("dotnet")
    if system_dotnet:
        candidates.append(system_dotnet)

    if DOTNET_BIN not in candidates:
        candidates.append(DOTNET_BIN)

    for path in candidates:
        try:
            result = subprocess.run(
                [path, "--list-runtimes"],
                capture_output=True,
                text=True,
                timeout=10,
                env=clean_env(DOTNET_ROOT=os.path.dirname(path)),
            )
            if "Microsoft.NETCore.App 9." in result.stdout:
                logger.info("dotnet: found .NET 9 runtime at %s", path)
                return path
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug("dotnet: probe failed for %s: %s", path, e)

    return None


def _install_dotnet_9_linux() -> bool:
    """Download Microsoft's dotnet-install.sh and run it into /home/deck/.dotnet.

    Adapted from niwia/ASSella:_install_dotnet_9_linux with the three changes
    documented in the module docstring. Returns True on success, False on any
    failure (network, disk, exec); logs the reason in each case.
    """
    try:
        os.makedirs(DOTNET_ROOT, exist_ok=True)

        env = clean_env(DOTNET_ROOT=DOTNET_ROOT, HOME="/home/deck")

        install_script = os.path.join(DOTNET_ROOT, "dotnet-install.sh")

        logger.info("dotnet: downloading installer script from %s", DOTNET_INSTALL_URL)
        if shutil.which("curl"):
            download_cmd = ["curl", "-sSL", "-o", install_script, DOTNET_INSTALL_URL]
        elif shutil.which("wget"):
            download_cmd = ["wget", "-q", "-O", install_script, DOTNET_INSTALL_URL]
        else:
            logger.error("dotnet: neither curl nor wget available")
            return False

        dl = subprocess.run(
            download_cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if dl.returncode != 0:
            logger.error("dotnet: download failed (exit %d): %s",
                         dl.returncode, dl.stderr.strip() or "(no stderr)")
            return False

        os.chmod(install_script, 0o755)

        logger.info("dotnet: running installer (channel 9.0, runtime only)")
        result = subprocess.run(
            [install_script, "--channel", "9.0", "--runtime", "dotnet"],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )

        # Clean up the install script regardless of outcome — keeping it around
        # just litters the dotnet root with an unused bash file.
        try:
            os.remove(install_script)
        except OSError:
            pass

        if result.returncode != 0:
            logger.error("dotnet: install failed (exit %d)", result.returncode)
            logger.error("dotnet: stdout: %s", result.stdout)
            logger.error("dotnet: stderr: %s", result.stderr)
            return False

        logger.info("dotnet: install completed")

        # chown -R so the user owns the install. LumaDeck runs as root, but
        # the .NET tree should belong to the user so future updates / removals
        # work from the user's session without sudo.
        chown = subprocess.run(
            ["chown", "-R", f"{DECK_USER}:{DECK_GROUP}", DOTNET_ROOT],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if chown.returncode != 0:
            logger.warning(
                "dotnet: chown to %s:%s failed: %s. .NET is installed but owned "
                "by root; user can run `sudo chown -R %s:%s %s` to fix.",
                DECK_USER, DECK_GROUP,
                chown.stderr.strip() or "(no stderr)",
                DECK_USER, DECK_GROUP, DOTNET_ROOT,
            )

        return True

    except subprocess.TimeoutExpired:
        logger.error("dotnet: timeout during install")
        return False
    except (OSError, subprocess.SubprocessError) as e:
        logger.error("dotnet: install raised: %s", e)
        return False


def ensure_dotnet_available() -> bool:
    """Make sure .NET 9 is available; install it if it's missing.

    Mirror of ASSella's ensure_dotnet_availability(): probe first, install
    only on miss, re-probe after install to confirm, then update the current
    process's env vars so the rest of the plugin sees dotnet without needing
    a Decky restart.
    """
    if find_dotnet_path():
        return True

    logger.warning("dotnet: .NET 9 not found, attempting automatic installation")
    if not _install_dotnet_9_linux():
        logger.error("dotnet: automatic installation failed")
        return False

    dotnet_path = find_dotnet_path()
    if not dotnet_path:
        logger.warning("dotnet: install reported success but binary not detected")
        return False

    # Make this process see the new install without a restart.
    os.environ["DOTNET_ROOT"] = os.path.dirname(dotnet_path)
    current_path = os.environ.get("PATH", "")
    if DOTNET_ROOT not in current_path.split(os.pathsep):
        os.environ["PATH"] = DOTNET_ROOT + os.pathsep + current_path

    logger.info("dotnet: now available at %s", dotnet_path)
    return True

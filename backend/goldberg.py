"""Goldberg Steam Emulator management for LumaDeck.

Applies/removes the Goldberg (gbe_fork) Steam emulator over a game's steam_api
libraries. The emulator binaries ship under backend/deps/Goldberg, fetched into
the plugin build from Detanup01/gbe_fork (see release.yml) — so this no longer
depends on the ACCELA AppImage.

steam_interfaces.txt is generated in pure Python by scanning the ORIGINAL
steam_api binary for interface-version strings (SteamUser021, …). gbe_fork
needs that file to expose the right interface versions; scanning the binary
avoids bundling and running the generate_interfaces helper.

Bundled layout (backend/deps/Goldberg/):
    steam_api.dll        steam_api64.dll        (Windows / Proton games)
    libsteam_api.so      libsteam_api64.so      (native Linux games)
    steam_settings/      (configs.user.ini, configs.overlay.ini, …)
"""

from __future__ import annotations

import os
import re
import shutil

from paths import backend_path, data_path

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# steam_api interface families. gbe_fork's steam_interfaces.txt lists the
# concrete versioned names (e.g. "SteamUser021") the emulator should expose;
# they appear verbatim as strings inside the original steam_api binary.
_INTERFACE_NAMES = [
    b"SteamClient", b"SteamGameServer", b"SteamGameServerStats", b"SteamUser",
    b"SteamFriends", b"SteamUtils", b"SteamMatchMaking", b"SteamMatchMakingServers",
    b"SteamUserStats", b"SteamApps", b"SteamNetworkingSockets", b"SteamNetworkingUtils",
    b"SteamNetworkingMessages", b"SteamNetworking", b"SteamRemoteStorage",
    b"SteamScreenshots", b"SteamHTTP", b"SteamController", b"SteamUGC",
    b"SteamAppList", b"SteamMusicRemote", b"SteamMusic", b"SteamHTMLSurface",
    b"SteamInventory", b"SteamVideo", b"SteamParentalSettings", b"SteamInput",
    b"SteamParties", b"SteamRemotePlay", b"SteamGameSearch", b"SteamTimeline",
]
_INTERFACE_RE = re.compile(rb"((?:" + b"|".join(_INTERFACE_NAMES) + rb")\d{3})")

_WIN_APIS = ("steam_api.dll", "steam_api64.dll")
_LINUX_API = "libsteam_api.so"


def _get_goldberg_dir() -> str | None:
    """Directory holding the bundled Goldberg binaries, or None if missing.

    1. backend/deps/Goldberg — fetched into the plugin build (the normal case).
    2. data_path("goldberg") — legacy cache from the old ACCELA-extraction
       path, kept so an existing install still resolves.
    """
    bundled = backend_path(os.path.join("deps", "Goldberg"))
    if os.path.isdir(bundled) and (
        os.path.exists(os.path.join(bundled, "steam_api64.dll"))
        or os.path.exists(os.path.join(bundled, "libsteam_api64.so"))
    ):
        return bundled

    legacy = data_path("goldberg")
    if os.path.isdir(legacy) and os.path.exists(os.path.join(legacy, "steam_api64.dll")):
        return legacy

    return None


def _scan_interfaces(bin_path: str) -> list[str]:
    """Return the sorted, de-duplicated interface-version strings found in a
    steam_api binary (e.g. ["SteamApps008", "SteamUser021", …])."""
    try:
        with open(bin_path, "rb") as f:
            data = f.read()
    except OSError as e:
        logger.warning(f"LumaDeck/Goldberg: cannot read {bin_path}: {e}")
        return []
    found = {m.group(1).decode("ascii", "ignore") for m in _INTERFACE_RE.finditer(data)}
    return sorted(found)


def _write_interfaces(original_bin: str, settings_dir: str) -> int:
    """Scan the original steam_api binary and write steam_interfaces.txt into
    the game's steam_settings dir. Returns the number of interfaces written."""
    ifaces = _scan_interfaces(original_bin)
    if not ifaces:
        return 0
    os.makedirs(settings_dir, exist_ok=True)
    with open(os.path.join(settings_dir, "steam_interfaces.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(ifaces) + "\n")
    return len(ifaces)


def _elf_is_64bit(path: str) -> bool | None:
    """True/False for a 64/32-bit ELF, or None if not a readable ELF."""
    try:
        with open(path, "rb") as f:
            head = f.read(5)
    except OSError:
        return None
    if len(head) < 5 or head[:4] != b"\x7fELF":
        return None
    return head[4] == 2  # EI_CLASS: 1 = 32-bit, 2 = 64-bit


def _linux_source_for(original_so: str, goldberg_dir: str) -> str | None:
    """Pick the bundled libsteam_api of the same arch as the game's .so."""
    is64 = _elf_is_64bit(original_so)
    if is64 is None:
        return None
    name = "libsteam_api64.so" if is64 else "libsteam_api.so"
    src = os.path.join(goldberg_dir, name)
    return src if os.path.exists(src) else None


def check_goldberg_status(install_path: str) -> dict:
    """Check if Goldberg is applied to a game directory (any .valve backup)."""
    try:
        if not install_path or not os.path.exists(install_path):
            return {"success": True, "applied": False, "reason": "Path not found"}

        for _root, _, files in os.walk(install_path):
            for fname in files:
                if fname.lower() in (
                    "steam_api.dll.valve", "steam_api64.dll.valve",
                    "libsteam_api.so.valve",
                ):
                    return {"success": True, "applied": True}

        return {"success": True, "applied": False}
    except Exception as e:
        return {"success": False, "error": str(e)}


def apply_goldberg(install_path: str, appid: int) -> dict:
    """Apply the Goldberg emulator to every steam_api library under install_path."""
    try:
        if not install_path or not os.path.exists(install_path):
            return {"success": False, "error": "Game directory not found"}

        goldberg_dir = _get_goldberg_dir()
        if not goldberg_dir:
            return {"success": False, "error": "Goldberg files not found in this build."}

        # Directories that hold at least one steam_api library.
        found_dirs = set()
        for root, _, files in os.walk(install_path):
            lower = {f.lower() for f in files}
            if lower & {*_WIN_APIS, _LINUX_API}:
                found_dirs.add(root)

        if not found_dirs:
            return {"success": False, "error": "No steam_api libraries found in game directory"}

        modified_count = 0
        for dest_dir in found_dirs:
            settings_dir = os.path.join(dest_dir, "steam_settings")

            # --- Windows steam_api DLLs -----------------------------------
            for base in _WIN_APIS:
                src_path = os.path.join(dest_dir, base)
                if not os.path.exists(src_path):
                    continue
                gb_src = os.path.join(goldberg_dir, base)
                if not os.path.exists(gb_src):
                    logger.warning(f"LumaDeck/Goldberg: bundled {base} missing")
                    continue
                # Generate interfaces from the PRISTINE original. On a re-apply
                # src_path is already the emulator DLL and the real one is in
                # .valve, so scan the backup when it exists.
                backup = src_path + ".valve"
                original = backup if os.path.exists(backup) else src_path
                n = _write_interfaces(original, settings_dir)
                logger.info(f"LumaDeck/Goldberg: {base} -> {n} interfaces")
                if not os.path.exists(backup):
                    os.replace(src_path, backup)
                elif os.path.exists(src_path):
                    os.remove(src_path)
                shutil.copy2(gb_src, src_path)

            # --- Native Linux libsteam_api.so -----------------------------
            so_path = os.path.join(dest_dir, _LINUX_API)
            if os.path.exists(so_path):
                backup = so_path + ".valve"
                # Detect arch from whichever copy is the pristine original.
                arch_ref = backup if os.path.exists(backup) else so_path
                gb_src = _linux_source_for(arch_ref, goldberg_dir)
                if gb_src:
                    # arch_ref is the pristine original (.valve on re-apply).
                    n = _write_interfaces(arch_ref, settings_dir)
                    logger.info(f"LumaDeck/Goldberg: {_LINUX_API} -> {n} interfaces")
                    if not os.path.exists(backup):
                        os.replace(so_path, backup)
                    elif os.path.exists(so_path):
                        os.remove(so_path)
                    shutil.copy2(gb_src, so_path)
                else:
                    logger.warning(f"LumaDeck/Goldberg: no matching-arch .so for {so_path}")

            # --- steam_settings + steam_appid.txt -------------------------
            gb_settings = os.path.join(goldberg_dir, "steam_settings")
            if os.path.isdir(gb_settings):
                # Merge the bundled settings without clobbering the generated
                # steam_interfaces.txt.
                os.makedirs(settings_dir, exist_ok=True)
                for item in os.listdir(gb_settings):
                    if item == "steam_interfaces.txt":
                        continue
                    s = os.path.join(gb_settings, item)
                    d = os.path.join(settings_dir, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)
                    else:
                        shutil.copy2(s, d)

            with open(os.path.join(dest_dir, "steam_appid.txt"), "w", encoding="utf-8") as f:
                f.write(str(appid))

            modified_count += 1

        logger.info(f"LumaDeck: Applied Goldberg to {modified_count} dir(s) in {install_path}")
        return {"success": True, "message": f"Goldberg applied to {modified_count} location(s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def remove_goldberg(install_path: str, appid: int) -> dict:
    """Remove Goldberg and restore the original steam_api libraries from .valve."""
    try:
        if not install_path or not os.path.exists(install_path):
            return {"success": False, "error": "Game directory not found"}

        found_dirs = set()
        for root, _, files in os.walk(install_path):
            for fname in files:
                if fname.lower() in (
                    "steam_api.dll.valve", "steam_api64.dll.valve",
                    "libsteam_api.so.valve",
                ):
                    found_dirs.add(root)

        if not found_dirs:
            return {"success": False, "error": "No Goldberg installation found (no .valve backups)"}

        modified_count = 0
        for dest_dir in found_dirs:
            libs = (*_WIN_APIS, _LINUX_API)

            # Restore each library from its .valve backup; drop the emulator
            # copy where no backup exists (it was added, not replaced).
            for base in libs:
                valve_path = os.path.join(dest_dir, base + ".valve")
                live_path = os.path.join(dest_dir, base)
                if os.path.exists(valve_path):
                    os.replace(valve_path, live_path)
                elif os.path.exists(live_path):
                    os.remove(live_path)

            # Remove the steam_settings we dropped and the generated interfaces.
            settings_dir = os.path.join(dest_dir, "steam_settings")
            if os.path.isdir(settings_dir):
                shutil.rmtree(settings_dir, ignore_errors=True)

            # Remove steam_appid.txt if it's the one we wrote (or empty).
            appid_file = os.path.join(dest_dir, "steam_appid.txt")
            if os.path.exists(appid_file):
                try:
                    with open(appid_file, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if not content or content == str(appid):
                        os.remove(appid_file)
                except Exception:
                    pass

            modified_count += 1

        logger.info(f"LumaDeck: Removed Goldberg from {modified_count} dir(s) in {install_path}")
        return {"success": True, "message": f"Goldberg removed from {modified_count} location(s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}

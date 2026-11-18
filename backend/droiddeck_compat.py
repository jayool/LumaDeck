"""Read-only DroidDeck detection and Steam home selection.

This module never changes Steam or game entitlements.
"""
from __future__ import annotations

import glob
import os
from typing import Mapping, Optional


def is_droiddeck(environ: Optional[Mapping[str, str]] = None,
                 home: Optional[str] = None) -> bool:
    env = os.environ if environ is None else environ
    override = env.get("LUMADECK_DROIDDECK", "").strip().lower()
    if override in ("0", "false", "no"):
        return False
    if override in ("1", "true", "yes"):
        return True
    if env.get("DD_STEAM_CLIENT_ARCH") in ("arm64", "aarch64", "x86_64"):
        return True
    homes = [home] if home else [env.get("HOME"), "/root"]
    for candidate in filter(None, homes):
        if (os.path.isfile(os.path.join(candidate, ".droiddeck-decky-enabled"))
                and os.path.isdir(os.path.join(candidate, "homebrew", "services"))):
            return True
    return False


def selected_client(environ: Optional[Mapping[str, str]] = None,
                    proc_root: Optional[str] = "/proc") -> str:
    env = os.environ if environ is None else environ
    explicit = env.get("LUMADECK_DROIDDECK_CLIENT") or env.get("DD_STEAM_CLIENT_ARCH")
    if explicit in ("x86_64", "amd64"):
        return "x86_64"
    if explicit in ("arm64", "aarch64"):
        return "arm64"
    if proc_root:
        for path in glob.glob(os.path.join(proc_root, "[0-9]*", "cmdline")):
            try:
                with open(path, "rb") as stream:
                    command = stream.read(4096).split(b"\0", 1)[0]
            except OSError:
                continue
            if command.endswith(b"/steamrt64/steam"):
                return "x86_64"
            if command.endswith(b"/steamrtarm64/steam"):
                return "arm64"
    return "arm64"


def steam_roots(real_home: str,
                environ: Optional[Mapping[str, str]] = None,
                proc_root: Optional[str] = "/proc") -> list[str]:
    """The selected client's Steam root wins; the other is a fallback."""
    env = os.environ if environ is None else environ
    native = [os.path.join(real_home, ".local", "share", "Steam"),
              os.path.join(real_home, ".steam", "steam")]
    x64_home = env.get("DD_X64_HOME") or os.path.join(real_home, ".droiddeck-x64")
    if not os.path.isabs(x64_home):
        x64_home = os.path.join(real_home, ".droiddeck-x64")
    x64 = [os.path.join(x64_home, ".local", "share", "Steam"),
           os.path.join(x64_home, ".steam", "steam")]
    roots = (x64 + native) if selected_client(env, proc_root) == "x86_64" else (native + x64)
    explicit = env.get("LUMADECK_STEAM_ROOT", "")
    if explicit and os.path.isabs(explicit):
        roots.insert(0, os.path.normpath(explicit))
    return list(dict.fromkeys(roots))

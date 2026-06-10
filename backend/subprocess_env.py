"""Subprocess environment helper.

Decky's PluginLoader is a PyInstaller binary that sets
``LD_LIBRARY_PATH=/tmp/_MEIxxxxxx/`` pointing at its own bundled libraries.
Plugin processes inherit that env var and subprocesses (curl, bash, wget…)
in turn inherit it from the plugin. When such a subprocess starts, the
dynamic linker resolves ``libssl.so.3`` from ``/tmp/_MEIxxxxxx/`` first —
where PyInstaller bundles an older libssl — instead of ``/usr/lib/``, and
the binary aborts with::

    curl: /tmp/_MEIxxxxxx/libssl.so.3: version `OPENSSL_3.2.0' not found

Pass ``env=clean_env()`` to every ``subprocess.run`` / ``asyncio.create_subprocess_*``
call that runs a system binary so the linker uses the system libs.
"""

from __future__ import annotations

import os


_PYINSTALLER_KEYS = (
    "LD_LIBRARY_PATH",
    "_PYI_APPLICATION_HOME_DIR",
    "_PYI_PARENT_PROCESS_LEVEL",
    "_PYI_LINUX_PROCESS_NAME",
)


def clean_env(**overrides: str) -> dict:
    """Return ``os.environ`` minus PyInstaller's bundled-lib vars, plus overrides.

    Use as ``env=clean_env()`` when invoking system binaries via subprocess
    from a Decky plugin. Optional kwargs add or override variables, e.g.
    ``env=clean_env(HOME="/home/deck", DOTNET_ROOT="/home/deck/.dotnet")``.
    """
    env = os.environ.copy()
    for key in _PYINSTALLER_KEYS:
        env.pop(key, None)
    if overrides:
        env.update(overrides)
    return env

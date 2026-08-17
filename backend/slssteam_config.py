"""
SLSsteam version lookup.

Reads the SLSsteam release tag that ``setup.sh`` records on disk. Nothing here
touches ``config.yaml``: every edit to that file goes through the append-only /
line-based helpers in ``slssteam_ops.py`` (per-key edits) and
``slssteam_schema.py`` (schema completion), which never rewrite the file wholesale.

Historical note — do not reintroduce a dict round-trip. This module used to also
expose ``read_config`` / ``get_value`` / ``set_value`` on top of a flat
``key: value`` parser. That parser stripped each line before parsing, so it
dropped every nested block (``AdditionalApps`` list items, ``FakeAppIds`` /
``DlcData`` / ``ManifestIds`` / ``CDKeys`` / ``DenuvoGames`` map entries) and
promoted nested entries to top-level keys. Reading was therefore misleading and
writing was destructive: a single ``set_value`` would have rewritten config.yaml
as flat lines, emptying ``AdditionalApps`` and silently un-owning every game the
plugin had added. Nothing ever called them (no ``api.ts`` wrapper, no page), so
they were removed rather than repaired. If a generic config setter is ever
needed, build it on the in-place regex edit + atomic replace + hot-reload poke
pattern used by ``installer.py``'s flag helpers, and make it refuse nested keys.
"""

from __future__ import annotations

import os
from typing import Optional

from paths import get_slssteam_config_dir


def get_sls_version() -> Optional[str]:
    """The installed SLSsteam version — a build timestamp like '20260801163409'.

    SLSsteam embeds its version only inside the compiled .so and writes nothing
    readable to disk (its config.yaml has no version field), so setup.sh records
    the release tag it pulled at install time into `.slssteam.version` beside the
    config. None when that file is absent (a pre-this-feature install, or an
    install where the tag couldn't be resolved) — the update check then reports
    "no update", the safe default."""
    path = os.path.join(get_slssteam_config_dir(), ".slssteam.version")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            version = fh.read().strip()
        return version or None
    except Exception:
        return None

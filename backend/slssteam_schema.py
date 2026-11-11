"""SLSsteam config.yaml schema completion (append-only).

Why this exists
---------------
SLSsteam writes its FULL default config only when the file is ABSENT (its
``createFile()`` is create-if-missing; it never migrates or rewrites an existing
file). It DOES, however, validate on load and toast the keys it is missing when
the on-disk config lacks keys the running SLSsteam expects. Since SLSsteam
``1250950`` (2026-07-26) that toast enumerates them one per line
(``"Config loading errors:\nMissing CDKeys\nMissing LogLevels"``); before that it
was the single ``"Issues during config loading encountered! Missing key(s)"``.

So a config that predates newer SLSsteam keys — or one that some tool seeded
partial before SLSsteam's first run — stays incomplete forever and toasts on
every launch. Reinstalling does not fix it (the file exists → SLSsteam won't
rewrite it).

This module reconciles the on-disk config against SLSsteam's current default
key-set by APPENDING any missing top-level keys (with their default block +
comment). It is APPEND-ONLY: it never edits or deletes an existing byte, so it
cannot lose the user's values (AdditionalApps, ManifestIds, flag choices, …) or
corrupt nested structures. Idempotent.

The reference key-set is SLSsteam's own ``res/config.yaml`` (the default config
its build embeds into the binary), fetched from ``main`` on every LumaDeck start
and cached under ``~/.cache/lumadeck``. There is deliberately no bundled copy:
installing or updating SLSsteam already needs the network, so the cache is
filled on the first start that has it, and a copy pasted here only drifted
(the last one predated ``Plugins``, ``SmartTickets`` and ``LaunchOptions``).
With no cached reference, completion is a no-op (worst case: the toast persists
until the next start with network; never a partial write).
"""

from __future__ import annotations

import os
import re
from typing import List, Tuple

from paths import get_slssteam_config_path, real_home

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


# Raw URL of SLSsteam's default config (the YAML its build embeds; shipped in
# every release zip). Plain YAML, no unwrapping needed.
_CONFIG_DEFAULT_URL = "https://raw.githubusercontent.com/AceSLS/SLSsteam/main/res/config.yaml"
_CACHE_DIR = os.path.join(real_home(), ".cache/lumadeck")
_CACHE_FILE = os.path.join(_CACHE_DIR, "slssteam_config_default.yaml")
_FETCH_TIMEOUT = 8.0

# A top-level key line: starts at column 0 (no indent), not a comment, `name:`.
_TOP_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:")


def _is_top_key(line: str) -> bool:
    return bool(line) and not line[0].isspace() and not line.lstrip().startswith("#") \
        and _TOP_KEY.match(line) is not None


def _top_key_name(line: str):
    m = _TOP_KEY.match(line)
    return m.group(1) if m else None


def present_top_level_keys(content: str) -> set:
    """Names of keys present as a top-level (column-0, non-comment) line."""
    return {_top_key_name(l) for l in content.splitlines() if _is_top_key(l)}


def _looks_like_reference(yaml_text: str) -> bool:
    """Sanity gate before trusting a reference: must carry the keys we key the
    whole thing on, so a garbled fetch/parse never drives the completion."""
    if not yaml_text:
        return False
    keys = present_top_level_keys(yaml_text)
    return {"SafeMode", "AdditionalApps", "DisableCloud"} <= keys and len(keys) >= 20


def split_blocks(yaml_text: str) -> List[Tuple[str, str]]:
    """Split a default-config YAML into ordered (key, block_text) pairs, where a
    block = its leading comment/blank lines + the top-level key line + any nested
    (indented) lines. Appending a block reproduces the canonical formatting.

    Trailing comment/blank lines after a key's nested content are treated as the
    LEADING comments of the NEXT key (that's how the canonical file is laid out).
    """
    blocks: List[Tuple[str, List[str]]] = []
    pending: List[str] = []          # comment/blank lines waiting for their key
    cur_key = None
    cur_lines: List[str] = []

    def flush():
        if cur_key is not None:
            blocks.append((cur_key, cur_lines))

    for line in yaml_text.splitlines():
        if _is_top_key(line):
            flush()
            cur_key = _top_key_name(line)
            cur_lines = pending + [line]
            pending = []
        elif cur_key is None:
            pending.append(line)                       # preamble before first key
        elif line.strip() == "" or line.lstrip().startswith("#"):
            pending.append(line)                       # maybe trailing -> next key
        elif line[0].isspace():
            cur_lines.extend(pending)                  # nested value of current key
            pending = []
            cur_lines.append(line)
        else:
            pending.append(line)                       # defensive; shouldn't happen
    flush()
    return [(k, "\n".join(ls)) for k, ls in blocks]


def complete_config_text(content: str, reference_yaml: str):
    """APPEND-ONLY completion. Returns (new_content, added_key_names).

    The original `content` is preserved byte-for-byte as a prefix of the result;
    only top-level keys absent from it are appended (with their default block).
    """
    reference = split_blocks(reference_yaml)
    if not reference:
        return content, []
    present = present_top_level_keys(content)
    missing = [(k, b) for k, b in reference if k not in present]
    if not missing:
        return content, []

    added = [k for k, _ in missing]
    header = "# --- keys added by LumaDeck to match SLSsteam's current schema ---"
    tail = "\n\n".join(b for _, b in missing)
    sep = "" if content.endswith("\n") else "\n"
    new_content = content + sep + "\n" + header + "\n" + tail + "\n"
    return new_content, added


def _cache_path() -> str:
    return _CACHE_FILE


def load_reference_yaml() -> str:
    """The reference YAML to complete against: the fetched cache if present and
    valid, else "" (no reference: completion does nothing)."""
    try:
        if os.path.isfile(_CACHE_FILE):
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = f.read()
            if _looks_like_reference(cached):
                return cached
            logger.info("slssteam_schema: cached reference didn't validate; no reference")
    except Exception as exc:
        logger.warning(f"slssteam_schema: cache read failed ({exc}); no reference")
    return ""


async def refresh_reference_cache() -> bool:
    """Best-effort: fetch res/config.yaml, validate it, cache it to disk. Returns
    True on a successful refresh. Never raises. On any failure the existing
    cache (if any) keeps being used."""
    try:
        from http_client import ensure_http_client
        client = await ensure_http_client(context="slssteam_schema")
        resp = await client.get(_CONFIG_DEFAULT_URL, timeout=_FETCH_TIMEOUT)
        if resp.status_code != 200:
            logger.info(f"slssteam_schema: HTTP {resp.status_code} for res/config.yaml; keeping cache")
            return False
        yaml_text = resp.text or ""
        if not _looks_like_reference(yaml_text):
            logger.info("slssteam_schema: fetched res/config.yaml didn't validate; keeping cache")
            return False
        os.makedirs(_CACHE_DIR, exist_ok=True)
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(yaml_text)
        os.replace(tmp, _CACHE_FILE)
        return True
    except Exception as exc:
        logger.info(f"slssteam_schema: reference refresh failed ({exc}); using cache if any")
        return False


def complete_slssteam_config(config_path: str | None = None) -> dict:
    """Append any missing SLSsteam keys to config.yaml (append-only, atomic).

    Returns {"completed": bool, "added": [...], "reason": str}. No-op (and never
    a write) when the config is absent, already complete, or no valid reference
    is available."""
    path = config_path or get_slssteam_config_path()
    if not os.path.isfile(path):
        return {"completed": False, "added": [], "reason": "config not present"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return {"completed": False, "added": [], "reason": f"read failed: {exc}"}

    reference = load_reference_yaml()
    if not reference:
        return {"completed": False, "added": [], "reason": "no reference available"}
    new_content, added = complete_config_text(content, reference)
    if not added:
        return {"completed": False, "added": [], "reason": "already complete"}

    # Belt-and-suspenders: never write unless the original is preserved verbatim.
    if not new_content.startswith(content):
        logger.warning("slssteam_schema: completion would not preserve original; aborting write")
        return {"completed": False, "added": [], "reason": "safety check failed"}
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp, path)
    except Exception as exc:
        return {"completed": False, "added": [], "reason": f"write failed: {exc}"}
    logger.info(f"slssteam_schema: completed config with {len(added)} missing key(s): {added}")
    return {"completed": True, "added": added, "reason": "ok"}

"""Generic helpers for file and data handling in the LumaDeck backend."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from paths import backend_path


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return ""


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


PRIVATE_MODE = 0o600


def write_private_text(path: str, text: str) -> None:
    """write_text for files that hold a credential (Hubcap key, Ryuu cookie,
    LuaTools session). The file is created 0600 and, if it already exists with
    looser permissions, tightened before it is rewritten. The backend runs as
    root and is the only reader; anything running as `deck` (a game, a fix,
    another plugin) could read a 0644 copy."""
    make_private(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def make_private(path: str) -> bool:
    """chmod 0600 an existing credential file; True if it changed. Missing
    file or any error: False, never raises (called on every plugin load)."""
    try:
        if not os.path.isfile(path):
            return False
        if (os.stat(path).st_mode & 0o777) == PRIVATE_MODE:
            return False
        os.chmod(path, PRIVATE_MODE)
        return True
    except Exception:
        return False


def read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def write_json(path: str, data: Dict[str, Any]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except Exception:
        pass


def count_apis(text: str) -> int:
    try:
        data = json.loads(text)
        apis = data.get("api_list", [])
        if isinstance(apis, list):
            return len(apis)
    except Exception:
        pass
    return text.count('"name"')


def normalize_manifest_text(text: str) -> str:
    content = (text or "").strip()
    if not content:
        return content

    content = re.sub(r",\s*]", "]", content)
    content = re.sub(r",\s*}\s*$", "}", content)

    if content.startswith('"api_list"') or content.startswith("'api_list'") or content.startswith("api_list"):
        if not content.startswith("{"):
            content = "{" + content
        if not content.endswith("}"):
            content = content.rstrip(",") + "}"

    try:
        json.loads(content)
        return content
    except Exception:
        return text


def ensure_temp_download_dir() -> str:
    root = backend_path("temp_dl")
    try:
        os.makedirs(root, exist_ok=True)
    except Exception:
        pass
    return root

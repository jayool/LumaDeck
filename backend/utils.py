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

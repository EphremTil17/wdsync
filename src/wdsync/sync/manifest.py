from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

_MANIFEST_FILENAME = "manifest.json"
_MANIFEST_VERSION = 2


def manifest_path(state_path: Path) -> Path:
    return state_path / _MANIFEST_FILENAME


def read_manifest(state_path: Path) -> frozenset[str]:
    path = manifest_path(state_path)
    if not path.exists():
        return frozenset()
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return frozenset()
        data = cast(dict[str, Any], raw)
        version = data.get("version")
        if version == 1:
            items = data.get("untracked", [])
        elif version == _MANIFEST_VERSION:
            items = data.get("mirrored_paths", [])
        else:
            return frozenset()
        if not isinstance(items, list):
            return frozenset()
        strings: list[str] = []
        for item in cast(list[Any], items):
            if isinstance(item, str):
                strings.append(item)
        return frozenset(strings)
    except (json.JSONDecodeError, OSError):
        return frozenset()


def write_manifest(state_path: Path, mirrored_paths: frozenset[str]) -> None:
    path = manifest_path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": _MANIFEST_VERSION,
        "mirrored_paths": sorted(mirrored_paths),
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

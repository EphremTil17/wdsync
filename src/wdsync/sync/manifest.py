from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

_MANIFEST_FILENAME = "manifest.json"
_MANIFEST_VERSION = 1


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
        if data.get("version") != _MANIFEST_VERSION:
            return frozenset()
        untracked = data.get("untracked", [])
        if not isinstance(untracked, list):
            return frozenset()
        items = cast(list[Any], untracked)
        return frozenset(p for p in items if isinstance(p, str))
    except (json.JSONDecodeError, OSError):
        return frozenset()


def write_manifest(state_path: Path, untracked_paths: frozenset[str]) -> None:
    path = manifest_path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": _MANIFEST_VERSION,
        "untracked": sorted(untracked_paths),
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

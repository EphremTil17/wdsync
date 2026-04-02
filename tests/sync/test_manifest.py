from __future__ import annotations

import json
from pathlib import Path

from wdsync.sync.manifest import manifest_path, read_manifest, write_manifest


def test_read_manifest_returns_empty_when_no_file(tmp_path: Path) -> None:
    assert read_manifest(tmp_path) == frozenset()


def test_write_and_read_manifest_roundtrip(tmp_path: Path) -> None:
    paths = frozenset({"a.txt", "dir/b.txt"})

    write_manifest(tmp_path, paths)
    result = read_manifest(tmp_path)

    assert result == paths


def test_manifest_path_is_manifest_json(tmp_path: Path) -> None:
    path = manifest_path(tmp_path)

    assert path.name == "manifest.json"
    assert path.parent == tmp_path


def test_read_manifest_handles_corrupt_json(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("not json", encoding="utf-8")

    assert read_manifest(tmp_path) == frozenset()


def test_read_manifest_handles_wrong_version(tmp_path: Path) -> None:
    data = {"version": 999, "untracked": ["a.txt"]}
    (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")

    assert read_manifest(tmp_path) == frozenset()


def test_read_manifest_supports_legacy_untracked_schema(tmp_path: Path) -> None:
    data = {"version": 1, "untracked": ["a.txt"]}
    (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")

    assert read_manifest(tmp_path) == frozenset({"a.txt"})


def test_write_manifest_creates_parent_if_needed(tmp_path: Path) -> None:
    state = tmp_path / "wdsync"
    write_manifest(state, frozenset({"x.txt"}))

    assert manifest_path(state).exists()
    assert read_manifest(state) == frozenset({"x.txt"})


def test_write_manifest_empty_set(tmp_path: Path) -> None:
    write_manifest(tmp_path, frozenset())
    result = read_manifest(tmp_path)

    assert result == frozenset()

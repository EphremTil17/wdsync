from __future__ import annotations

import json
from pathlib import Path

from wdsync.manifest import manifest_path, read_manifest, write_manifest


def test_read_manifest_returns_empty_when_no_file(tmp_path: Path) -> None:
    assert read_manifest(tmp_path) == frozenset()


def test_write_and_read_manifest_roundtrip(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    paths = frozenset({"a.txt", "dir/b.txt"})

    write_manifest(tmp_path, paths)
    result = read_manifest(tmp_path)

    assert result == paths


def test_manifest_path_is_inside_git_dir(tmp_path: Path) -> None:
    path = manifest_path(tmp_path)

    assert ".git" in path.parts
    assert path.name == ".wdsync-manifest"


def test_read_manifest_handles_corrupt_json(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / ".wdsync-manifest").write_text("not json", encoding="utf-8")

    assert read_manifest(tmp_path) == frozenset()


def test_read_manifest_handles_wrong_version(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    data = {"version": 999, "untracked": ["a.txt"]}
    (git_dir / ".wdsync-manifest").write_text(json.dumps(data), encoding="utf-8")

    assert read_manifest(tmp_path) == frozenset()


def test_write_manifest_creates_git_dir_if_needed(tmp_path: Path) -> None:
    write_manifest(tmp_path, frozenset({"x.txt"}))

    assert manifest_path(tmp_path).exists()
    assert read_manifest(tmp_path) == frozenset({"x.txt"})


def test_write_manifest_empty_set(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    write_manifest(tmp_path, frozenset())
    result = read_manifest(tmp_path)

    assert result == frozenset()

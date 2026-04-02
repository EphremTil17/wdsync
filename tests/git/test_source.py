from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from wdsync.core.models import DirectionConfig
from wdsync.core.runner import CommandRunner
from wdsync.git.source import read_source_head, read_source_state


def test_read_source_head_returns_none_without_commits(
    tmp_path: Path,
    git_runner: CommandRunner,
    direction_config_factory: Callable[..., DirectionConfig],
) -> None:
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    subprocess.run(["git", "-C", str(source_repo), "init", "-q"], check=True, capture_output=True)
    dest_repo = tmp_path / "dest"
    dest_repo.mkdir()
    dconfig = direction_config_factory(source_repo, dest_repo)

    assert read_source_head(dconfig, git_runner) is None


def test_read_source_state_reads_head_and_dirty_entries(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    direction_config_factory: Callable[..., DirectionConfig],
) -> None:
    source_repo = repo_factory("source", files={"tracked.txt": "base\n"})
    dest_repo = repo_factory("dest", clone_from=source_repo)
    (source_repo / "tracked.txt").write_text("updated\n", encoding="utf-8")
    (source_repo / "new.txt").write_text("fresh\n", encoding="utf-8")

    dconfig = direction_config_factory(source_repo, dest_repo)
    state = read_source_state(dconfig, git_runner)

    assert state.head is not None
    assert {entry.raw_xy for entry in state.entries} == {" M", "??"}

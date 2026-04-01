from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from wdsync.core.models import DirectionConfig, SyncDirection
from wdsync.core.runner import CommandRunner
from wdsync.git.dest import read_destination_head, read_destination_state


def _dest_dconfig(repo: Path) -> DirectionConfig:
    return DirectionConfig(
        direction=SyncDirection.FETCH,
        source_root=repo,
        source_root_native=str(repo),
        source_git="git",
        dest_root=repo,
        dest_root_native=str(repo),
        dest_git="git",
    )


def test_read_destination_state_counts_modified_staged_and_untracked_files(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("dest", files={"tracked.txt": "base\n", "staged.txt": "base\n"})

    (repo / "tracked.txt").write_text("modified\n", encoding="utf-8")
    (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "staged.txt"],
        check=True,
        capture_output=True,
    )

    dconfig = _dest_dconfig(repo)
    state = read_destination_state(dconfig, git_runner)

    assert state.head == read_destination_head(dconfig, git_runner)
    assert state.modified_count == 1
    assert state.staged_count == 1
    assert state.untracked_count == 1
    assert state.is_dirty is True


def test_wt_deleted_paths_populated(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("dest", files={"file.txt": "content\n"})
    (repo / "file.txt").unlink()  # produces " D" status

    state = read_destination_state(_dest_dconfig(repo), git_runner)

    assert "file.txt" in state.wt_deleted_paths
    assert "file.txt" in state.dirty_paths


def test_staged_deletion_excluded_from_wt_deleted(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("dest", files={"file.txt": "content\n"})
    subprocess.run(
        ["git", "-C", str(repo), "rm", "-q", "file.txt"],
        check=True,
        capture_output=True,
    )  # produces "D " status

    state = read_destination_state(_dest_dconfig(repo), git_runner)

    assert "file.txt" not in state.wt_deleted_paths
    assert "file.txt" in state.dirty_paths

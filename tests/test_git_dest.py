from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from wdsync.git_dest import read_destination_head, read_destination_state
from wdsync.runner import CommandRunner


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

    state = read_destination_state(repo, git_runner)

    assert state.head == read_destination_head(repo, git_runner)
    assert state.modified_count == 1
    assert state.staged_count == 1
    assert state.untracked_count == 1
    assert state.is_dirty is True

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from wdsync.core.models import RestoreResult, SyncPlan
from wdsync.core.runner import CommandRunner
from wdsync.sync.engine import execute_sync, restore_files

# conftest provides: git_runner, repo_factory


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_execute_sync_uses_content_focused_rsync_flags(tmp_path: Path) -> None:
    log_path = tmp_path / "rsync-args.txt"
    rsync_stub = _write_executable(
        tmp_path / "rsync",
        (f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > {log_path}\nexit 0\n"),
    )
    runner = CommandRunner({"rsync": rsync_stub})
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    (source_root / "file.txt").write_text("content\n", encoding="utf-8")

    plan = SyncPlan(
        source_root=source_root,
        dest_root=dest_root,
        preview_rows=(),
        copy_paths=("file.txt",),
        delete_paths=(),
        skipped_paths=(),
        warnings=(),
    )

    execute_sync(plan, runner)

    args = log_path.read_text(encoding="utf-8").splitlines()
    assert "-rlt" in args
    assert "-a" not in args
    assert "--from0" in args
    assert any(arg.startswith("--files-from=") for arg in args)


def test_restore_files_runs_git_restore(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("dest", files={"file.txt": "content\n"})
    (repo / "file.txt").unlink()  # produces " D" status

    result = restore_files(
        ("file.txt",), git_runner, dest_git_cmd=("git",), dest_root_native=str(repo)
    )

    assert result == RestoreResult(restored_count=1, warnings=())
    assert (repo / "file.txt").read_text(encoding="utf-8") == "content\n"


def test_restore_files_warns_on_failure(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("dest", files={"file.txt": "content\n"})

    result = restore_files(
        ("nonexistent.txt",), git_runner, dest_git_cmd=("git",), dest_root_native=str(repo)
    )

    assert result.restored_count == 0
    assert len(result.warnings) == 1
    assert "nonexistent.txt" in result.warnings[0]


def test_restore_files_noop_when_empty(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("dest", files={"file.txt": "content\n"})

    result = restore_files(
        (),
        git_runner,
        dest_git_cmd=("git",),
        dest_root_native=str(repo),
    )

    assert result == RestoreResult(restored_count=0, warnings=())

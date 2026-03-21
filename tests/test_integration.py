from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from wdsync.doctor import build_doctor_report
from wdsync.git_dest import read_destination_state
from wdsync.git_source import read_source_state
from wdsync.models import ProjectConfig
from wdsync.planner import build_sync_plan
from wdsync.runner import CommandRunner
from wdsync.sync import execute_sync


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", message],
        check=True,
        capture_output=True,
    )


def test_untracked_directory_syncs_nested_files(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    project_config_factory: Callable[[Path, Path], ProjectConfig],
) -> None:
    source_repo = repo_factory("source", files={"tracked.txt": "base\n"})
    dest_repo = repo_factory("dest", clone_from=source_repo)
    (source_repo / "newdir/sub").mkdir(parents=True)
    (source_repo / "newdir/sub/file.txt").write_text("fresh\n", encoding="utf-8")

    config = project_config_factory(source_repo, dest_repo)
    source_state = read_source_state(config, git_runner)
    plan = build_sync_plan(config, source_state)
    result = execute_sync(plan, git_runner)

    assert "newdir/sub/file.txt" in result.plan.copy_paths
    assert (dest_repo / "newdir/sub/file.txt").read_text(encoding="utf-8") == "fresh\n"


def test_rename_and_delete_are_previewed_but_only_rename_is_synced(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    project_config_factory: Callable[[Path, Path], ProjectConfig],
) -> None:
    source_repo = repo_factory(
        "source",
        files={"alpha.txt": "alpha\n", "remove.txt": "remove\n"},
    )
    dest_repo = repo_factory("dest", clone_from=source_repo)

    subprocess.run(
        ["git", "-C", str(source_repo), "mv", "alpha.txt", "beta.txt"],
        check=True,
        capture_output=True,
    )
    (source_repo / "remove.txt").unlink()

    config = project_config_factory(source_repo, dest_repo)
    source_state = read_source_state(config, git_runner)
    plan = build_sync_plan(config, source_state)
    result = execute_sync(plan, git_runner)

    labels = {row.path: row.label for row in plan.preview_rows}
    assert labels["beta.txt"] == "renamed"
    assert labels["remove.txt"] == "deleted"
    assert "remove.txt" not in plan.copy_paths
    assert result.skipped_count == 1
    assert (dest_repo / "beta.txt").exists()
    assert (dest_repo / "remove.txt").exists()


def test_doctor_warns_on_head_mismatch_and_dirty_destination(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    project_config_factory: Callable[[Path, Path], ProjectConfig],
) -> None:
    source_repo = repo_factory("source", files={"tracked.txt": "base\n"})
    dest_repo = repo_factory("dest", clone_from=source_repo)

    (source_repo / "tracked.txt").write_text("source change\n", encoding="utf-8")
    _commit_all(source_repo, "source change")
    (dest_repo / "local.txt").write_text("dirty\n", encoding="utf-8")

    config = project_config_factory(source_repo, dest_repo)
    source_state = read_source_state(config, git_runner)
    destination_state = read_destination_state(dest_repo, git_runner)
    report = build_doctor_report(config, source_state, destination_state, git_runner)

    warning_codes = {warning.code for warning in report.warnings}
    assert "head-mismatch" in warning_codes
    assert "destination-dirty" in warning_codes

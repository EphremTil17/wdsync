from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from wdsync.core.models import ProjectConfig, StatusKind, SyncDirection
from wdsync.core.runner import CommandRunner
from wdsync.git.dest import read_destination_state
from wdsync.git.source import read_source_state
from wdsync.sync.direction import build_direction_config
from wdsync.sync.doctor import build_doctor_report
from wdsync.sync.engine import execute_sync
from wdsync.sync.manifest import read_manifest, write_manifest
from wdsync.sync.planner import build_sync_plan


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
    dconfig = build_direction_config(config, SyncDirection.FETCH)
    source_state = read_source_state(dconfig, git_runner)
    plan = build_sync_plan(dconfig, source_state)
    result = execute_sync(plan, git_runner)

    assert "newdir/sub/file.txt" in result.plan.copy_paths
    assert (dest_repo / "newdir/sub/file.txt").read_text(encoding="utf-8") == "fresh\n"


def test_file_with_spaces_syncs_successfully(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    project_config_factory: Callable[[Path, Path], ProjectConfig],
) -> None:
    source_repo = repo_factory("source", files={"tracked.txt": "base\n"})
    dest_repo = repo_factory("dest", clone_from=source_repo)
    path_with_spaces = source_repo / "assets/anyone pause.wav"
    path_with_spaces.parent.mkdir(parents=True)
    path_with_spaces.write_text("audio placeholder\n", encoding="utf-8")

    config = project_config_factory(source_repo, dest_repo)
    dconfig = build_direction_config(config, SyncDirection.FETCH)
    source_state = read_source_state(dconfig, git_runner)
    plan = build_sync_plan(dconfig, source_state)
    result = execute_sync(plan, git_runner)

    assert "assets/anyone pause.wav" in result.plan.copy_paths
    assert (dest_repo / "assets/anyone pause.wav").read_text(encoding="utf-8") == (
        "audio placeholder\n"
    )


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
    dconfig = build_direction_config(config, SyncDirection.FETCH)
    source_state = read_source_state(dconfig, git_runner)
    plan = build_sync_plan(dconfig, source_state)
    result = execute_sync(plan, git_runner)

    labels = {row.path: row.label for row in plan.preview_rows}
    assert labels["beta.txt"] == "renamed"
    assert labels["remove.txt"] == "deleted"
    assert "remove.txt" not in plan.copy_paths
    assert "remove.txt" in plan.delete_paths
    assert result.deleted_count == 1
    assert (dest_repo / "beta.txt").exists()
    assert not (dest_repo / "remove.txt").exists()


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
    dconfig = build_direction_config(config, SyncDirection.FETCH)
    source_state = read_source_state(dconfig, git_runner)
    destination_state = read_destination_state(dconfig, git_runner)
    report = build_doctor_report(dconfig, source_state, destination_state, git_runner)

    warning_codes = {warning.code for warning in report.warnings}
    assert "head-mismatch" in warning_codes
    assert "destination-dirty" in warning_codes


def test_reconciliation_restores_previously_deleted_file(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    project_config_factory: Callable[[Path, Path], ProjectConfig],
) -> None:
    source_repo = repo_factory(
        "source",
        files={"keep.txt": "keep\n", "remove.txt": "remove\n"},
    )
    dest_repo = repo_factory("dest", clone_from=source_repo)

    # Step 1: Delete remove.txt in source and sync — should delete from dest
    (source_repo / "remove.txt").unlink()

    config = project_config_factory(source_repo, dest_repo)
    dconfig = build_direction_config(config, SyncDirection.FETCH)
    source_state = read_source_state(dconfig, git_runner)
    plan = build_sync_plan(dconfig, source_state)
    execute_sync(plan, git_runner)

    assert not (dest_repo / "remove.txt").exists()

    # Step 2: Restore remove.txt in source (git restore)
    subprocess.run(
        ["git", "-C", str(source_repo), "restore", "--", "remove.txt"],
        check=True,
        capture_output=True,
    )
    assert (source_repo / "remove.txt").exists()

    # Step 3: Sync again — should detect dest has " D" for remove.txt
    # and restore it since source no longer has it deleted
    source_state = read_source_state(dconfig, git_runner)
    destination_state = read_destination_state(dconfig, git_runner)
    plan = build_sync_plan(dconfig, source_state)

    source_deleted_paths = frozenset(
        entry.path for entry in source_state.entries if entry.kind is StatusKind.DELETED
    )
    restore_candidates = destination_state.wt_deleted_paths - source_deleted_paths
    if restore_candidates:
        plan = replace(plan, restore_paths=tuple(sorted(restore_candidates)))

    result = execute_sync(plan, git_runner)

    assert (dest_repo / "remove.txt").exists()
    assert (dest_repo / "remove.txt").read_text(encoding="utf-8") == "remove\n"
    assert result.restored_count == 1


def test_manifest_orphan_cleanup_deletes_untracked_file(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    project_config_factory: Callable[[Path, Path], ProjectConfig],
) -> None:
    source_repo = repo_factory("source", files={"tracked.txt": "base\n"})
    dest_repo = repo_factory("dest", clone_from=source_repo)

    # Step 1: Create an untracked file in source and sync it
    (source_repo / "scratch.txt").write_text("temp\n", encoding="utf-8")

    config = project_config_factory(source_repo, dest_repo)
    dconfig = build_direction_config(config, SyncDirection.FETCH)
    source_state = read_source_state(dconfig, git_runner)
    plan = build_sync_plan(dconfig, source_state)
    execute_sync(plan, git_runner)

    assert (dest_repo / "scratch.txt").exists()

    # Write manifest recording the untracked file we just synced
    current_untracked = frozenset(
        entry.path for entry in source_state.entries if entry.kind is StatusKind.NEW
    )
    write_manifest(dconfig.dest_root, current_untracked)

    # Step 2: Delete the untracked file from source
    (source_repo / "scratch.txt").unlink()

    # Step 3: Sync again — manifest detects orphan, deletes from dest
    source_state = read_source_state(dconfig, git_runner)
    plan = build_sync_plan(dconfig, source_state)

    source_dirty_paths = frozenset(entry.path for entry in source_state.entries)
    prev_untracked = read_manifest(dconfig.dest_root)
    orphaned = prev_untracked - source_dirty_paths
    if orphaned:
        plan = replace(plan, delete_paths=plan.delete_paths + tuple(sorted(orphaned)))

    result = execute_sync(plan, git_runner)

    assert not (dest_repo / "scratch.txt").exists()
    assert result.deleted_count == 1


def test_send_syncs_wsl_dirty_tree_to_remote(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    project_config_factory: Callable[[Path, Path], ProjectConfig],
) -> None:
    source_repo = repo_factory("source", files={"tracked.txt": "base\n"})
    dest_repo = repo_factory("dest", clone_from=source_repo)

    # Modify a file in the WSL repo (which becomes the source in send mode)
    (dest_repo / "tracked.txt").write_text("modified in WSL\n", encoding="utf-8")

    config = project_config_factory(source_repo, dest_repo)
    dconfig = build_direction_config(config, SyncDirection.SEND)
    source_state = read_source_state(dconfig, git_runner)
    plan = build_sync_plan(dconfig, source_state)
    result = execute_sync(plan, git_runner)

    assert result.copied_count == 1
    assert (source_repo / "tracked.txt").read_text(encoding="utf-8") == "modified in WSL\n"


def test_send_deletes_propagate_to_remote(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    project_config_factory: Callable[[Path, Path], ProjectConfig],
) -> None:
    source_repo = repo_factory("source", files={"tracked.txt": "base\n", "remove.txt": "remove\n"})
    dest_repo = repo_factory("dest", clone_from=source_repo)

    # Delete a file in the WSL repo (source in send mode)
    (dest_repo / "remove.txt").unlink()

    config = project_config_factory(source_repo, dest_repo)
    dconfig = build_direction_config(config, SyncDirection.SEND)
    source_state = read_source_state(dconfig, git_runner)
    plan = build_sync_plan(dconfig, source_state)
    result = execute_sync(plan, git_runner)

    assert result.deleted_count == 1
    assert not (source_repo / "remove.txt").exists()

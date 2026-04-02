from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile

from wdsync.core.exceptions import CommandExecutionError
from wdsync.core.models import RestoreResult, SyncPlan, SyncResult
from wdsync.core.runner import CommandRunner
from wdsync.sync.deleter import delete_files


def _write_files_from(paths: tuple[str, ...]) -> Path:
    with NamedTemporaryFile("wb", delete=False) as handle:
        for path in paths:
            handle.write(path.encode("utf-8", errors="surrogateescape"))
            handle.write(b"\0")
        return Path(handle.name)


def restore_files(
    restore_paths: tuple[str, ...],
    runner: CommandRunner,
    *,
    dest_git_cmd: tuple[str, ...] = ("git",),
    dest_root_native: str = "",
) -> RestoreResult:
    if not restore_paths:
        return RestoreResult(restored_count=0, warnings=())

    warnings: list[str] = []
    restored = 0

    try:
        runner.run([*dest_git_cmd, "-C", dest_root_native, "restore", "--", *restore_paths])
        restored = len(restore_paths)
    except CommandExecutionError:
        for path in restore_paths:
            try:
                runner.run([*dest_git_cmd, "-C", dest_root_native, "restore", "--", path])
                restored += 1
            except CommandExecutionError:
                warnings.append(f"warning: could not restore {path!r} in destination")

    return RestoreResult(restored_count=restored, warnings=tuple(warnings))


def copy_files(
    plan: SyncPlan,
    runner: CommandRunner,
    *,
    rsync_cmd: tuple[str, ...] = ("rsync",),
    rsync_source_root: str | None = None,
    rsync_dest_root: str | None = None,
) -> bool:
    if not plan.copy_paths:
        return False

    files_from_path = _write_files_from(plan.copy_paths)
    try:
        runner.run(
            [
                *rsync_cmd,
                "-rlt",
                "--from0",
                f"--files-from={files_from_path}",
                f"{(rsync_source_root or str(plan.source_root))}/",
                f"{(rsync_dest_root or str(plan.dest_root))}/",
            ]
        )
    finally:
        files_from_path.unlink(missing_ok=True)
    return True


def execute_sync(
    plan: SyncPlan,
    runner: CommandRunner,
    *,
    dest_dirty_paths: frozenset[str] = frozenset(),
    confirm_sudo: Callable[[str], bool] = lambda _: False,
    prune_empty_dirs: bool = True,
    dest_git_cmd: tuple[str, ...] = ("git",),
    dest_root_native: str = "",
    rsync_cmd: tuple[str, ...] = ("rsync",),
    rsync_source_root: str | None = None,
    rsync_dest_root: str | None = None,
) -> SyncResult:
    restore_result = restore_files(
        plan.restore_paths,
        runner,
        dest_git_cmd=dest_git_cmd,
        dest_root_native=dest_root_native or str(plan.dest_root),
    )

    outcomes = delete_files(
        plan,
        dest_dirty_paths,
        confirm_sudo=confirm_sudo,
        prune_empty_dirs=prune_empty_dirs,
    )
    deleted_count = sum(1 for o in outcomes if o.deleted)

    extra_warnings: list[str] = list(restore_result.warnings)
    for outcome in outcomes:
        if outcome.skipped and outcome.skip_reason == "dest-modified":
            extra_warnings.append(
                f"warning: {outcome.path!r} has local changes in dest — skipping deletion"
            )
        elif (
            outcome.skipped and outcome.skip_reason and outcome.skip_reason.startswith("os-error:")
        ):
            extra_warnings.append(
                f"warning: could not delete {outcome.path!r} ({outcome.skip_reason})"
            )

    if extra_warnings:
        plan = replace(plan, warnings=plan.warnings + tuple(extra_warnings))

    if not plan.copy_paths:
        return SyncResult(
            plan=plan,
            copied_count=0,
            deleted_count=deleted_count,
            skipped_count=len(plan.skipped_paths),
            performed_copy=False,
            restored_count=restore_result.restored_count,
        )

    performed_copy = copy_files(
        plan,
        runner,
        rsync_cmd=rsync_cmd,
        rsync_source_root=rsync_source_root,
        rsync_dest_root=rsync_dest_root,
    )

    return SyncResult(
        plan=plan,
        copied_count=len(plan.copy_paths),
        deleted_count=deleted_count,
        skipped_count=len(plan.skipped_paths),
        performed_copy=performed_copy,
        restored_count=restore_result.restored_count,
    )

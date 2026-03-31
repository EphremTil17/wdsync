from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile

from wdsync.deleter import delete_files
from wdsync.exceptions import CommandExecutionError
from wdsync.models import SyncPlan, SyncResult
from wdsync.runner import CommandRunner


def _write_files_from(paths: tuple[str, ...]) -> Path:
    with NamedTemporaryFile("wb", delete=False) as handle:
        for path in paths:
            handle.write(path.encode("utf-8", errors="surrogateescape"))
            handle.write(b"\0")
        return Path(handle.name)


def restore_files(
    dest_root: Path,
    restore_paths: tuple[str, ...],
    runner: CommandRunner,
) -> tuple[int, list[str]]:
    if not restore_paths:
        return 0, []

    warnings: list[str] = []
    restored = 0

    try:
        runner.run(["git", "-C", str(dest_root), "restore", "--", *restore_paths])
        restored = len(restore_paths)
    except CommandExecutionError:
        for path in restore_paths:
            try:
                runner.run(["git", "-C", str(dest_root), "restore", "--", path])
                restored += 1
            except CommandExecutionError:
                warnings.append(f"warning: could not restore {path!r} in destination")

    return restored, warnings


def execute_sync(
    plan: SyncPlan,
    runner: CommandRunner,
    *,
    dest_dirty_paths: frozenset[str] = frozenset(),
    confirm_sudo: Callable[[str], bool] = lambda _: False,
    prune_empty_dirs: bool = True,
) -> SyncResult:
    restored_count, restore_warnings = restore_files(plan.dest_root, plan.restore_paths, runner)

    outcomes = delete_files(
        plan,
        dest_dirty_paths,
        confirm_sudo=confirm_sudo,
        prune_empty_dirs=prune_empty_dirs,
    )
    deleted_count = sum(1 for o in outcomes if o.deleted)

    extra_warnings: list[str] = list(restore_warnings)
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
            restored_count=restored_count,
        )

    files_from_path = _write_files_from(plan.copy_paths)
    try:
        runner.run(
            [
                "rsync",
                "-rlt",
                "--from0",
                f"--files-from={files_from_path}",
                f"{plan.source_root}/",
                f"{plan.dest_root}/",
            ]
        )
    finally:
        files_from_path.unlink(missing_ok=True)

    return SyncResult(
        plan=plan,
        copied_count=len(plan.copy_paths),
        deleted_count=deleted_count,
        skipped_count=len(plan.skipped_paths),
        performed_copy=True,
        restored_count=restored_count,
    )

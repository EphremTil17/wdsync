from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from wdsync.models import SyncPlan, SyncResult
from wdsync.runner import CommandRunner


def _write_files_from(paths: tuple[str, ...]) -> Path:
    with NamedTemporaryFile("wb", delete=False) as handle:
        for path in paths:
            handle.write(path.encode("utf-8", errors="surrogateescape"))
            handle.write(b"\0")
        return Path(handle.name)


def execute_sync(plan: SyncPlan, runner: CommandRunner) -> SyncResult:
    if not plan.copy_paths:
        return SyncResult(
            plan=plan,
            copied_count=0,
            skipped_count=len(plan.skipped_paths),
            performed_copy=False,
        )

    files_from_path = _write_files_from(plan.copy_paths)
    try:
        runner.run(
            [
                "rsync",
                "-a",
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
        skipped_count=len(plan.skipped_paths),
        performed_copy=True,
    )

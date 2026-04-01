from __future__ import annotations

from wdsync.core.models import DestinationState, DirectionConfig
from wdsync.core.runner import CommandRunner
from wdsync.git.status_parser import parse_porcelain_v1_z


def read_destination_head(dconfig: DirectionConfig, runner: CommandRunner) -> str | None:
    result = runner.run(
        [dconfig.dest_git, "-C", dconfig.dest_root_native, "rev-parse", "--verify", "HEAD"],
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout_text().strip()


def read_destination_state(dconfig: DirectionConfig, runner: CommandRunner) -> DestinationState:
    result = runner.run(
        [
            dconfig.dest_git,
            "-C",
            dconfig.dest_root_native,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ]
    )
    entries = parse_porcelain_v1_z(result.stdout)

    modified_count = 0
    staged_count = 0
    untracked_count = 0
    dirty_paths: set[str] = set()
    wt_deleted_paths: set[str] = set()
    for entry in entries:
        if entry.raw_xy == "??":
            untracked_count += 1
            continue
        if entry.raw_xy[0] not in {" ", "?"}:
            staged_count += 1
            dirty_paths.add(entry.path)
        if entry.raw_xy[1] not in {" ", "?"}:
            modified_count += 1
            dirty_paths.add(entry.path)
        if entry.raw_xy == " D":
            wt_deleted_paths.add(entry.path)

    return DestinationState(
        head=read_destination_head(dconfig, runner),
        modified_count=modified_count,
        staged_count=staged_count,
        untracked_count=untracked_count,
        dirty_paths=frozenset(dirty_paths),
        wt_deleted_paths=frozenset(wt_deleted_paths),
        entries=entries,
    )

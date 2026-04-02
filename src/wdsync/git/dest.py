from __future__ import annotations

from collections.abc import Sequence

from wdsync.core.models import DestinationState, DirectionConfig, StatusRecord
from wdsync.core.runner import CommandRunner
from wdsync.git.status_parser import parse_porcelain_v1_z


def read_head(command: Sequence[str], runner: CommandRunner) -> str | None:
    result = runner.run([*command, "rev-parse", "--verify", "HEAD"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout_text().strip()


def destination_state_from_entries(
    entries: tuple[StatusRecord, ...],
    *,
    head: str | None,
) -> DestinationState:
    modified_count = 0
    staged_count = 0
    untracked_count = 0
    dirty_paths: set[str] = set()
    wt_deleted_paths: set[str] = set()
    for entry in entries:
        raw_xy = entry.raw_xy
        path = entry.path
        if raw_xy == "??":
            untracked_count += 1
            continue
        if raw_xy[0] not in {" ", "?"}:
            staged_count += 1
            dirty_paths.add(path)
        if raw_xy[1] not in {" ", "?"}:
            modified_count += 1
            dirty_paths.add(path)
        if raw_xy == " D":
            wt_deleted_paths.add(path)

    return DestinationState(
        head=head,
        modified_count=modified_count,
        staged_count=staged_count,
        untracked_count=untracked_count,
        dirty_paths=frozenset(dirty_paths),
        wt_deleted_paths=frozenset(wt_deleted_paths),
        entries=entries,
    )


def read_destination_head(dconfig: DirectionConfig, runner: CommandRunner) -> str | None:
    return read_head(dconfig.dest_git_command(), runner)


def read_repo_destination_state(
    command: Sequence[str],
    runner: CommandRunner,
) -> DestinationState:
    result = runner.run([*command, "status", "--porcelain=v1", "-z", "--untracked-files=all"])
    entries = parse_porcelain_v1_z(result.stdout)
    return destination_state_from_entries(entries, head=read_head(command, runner))


def read_destination_state(dconfig: DirectionConfig, runner: CommandRunner) -> DestinationState:
    return read_repo_destination_state(dconfig.dest_git_command(), runner)

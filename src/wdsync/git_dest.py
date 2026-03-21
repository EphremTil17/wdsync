from __future__ import annotations

from pathlib import Path

from wdsync.models import DestinationState
from wdsync.runner import CommandRunner
from wdsync.status_parser import parse_porcelain_v1_z


def read_destination_head(dest_root: Path, runner: CommandRunner) -> str | None:
    result = runner.run(["git", "-C", str(dest_root), "rev-parse", "--verify", "HEAD"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout_text().strip()


def read_destination_state(dest_root: Path, runner: CommandRunner) -> DestinationState:
    result = runner.run(
        ["git", "-C", str(dest_root), "status", "--porcelain=v1", "-z", "--untracked-files=all"]
    )
    entries = parse_porcelain_v1_z(result.stdout)

    modified_count = 0
    staged_count = 0
    untracked_count = 0
    for entry in entries:
        if entry.raw_xy == "??":
            untracked_count += 1
            continue
        if entry.raw_xy[0] not in {" ", "?"}:
            staged_count += 1
        if entry.raw_xy[1] not in {" ", "?"}:
            modified_count += 1

    return DestinationState(
        head=read_destination_head(dest_root, runner),
        modified_count=modified_count,
        staged_count=staged_count,
        untracked_count=untracked_count,
    )

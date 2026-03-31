from __future__ import annotations

from wdsync.models import DirectionConfig, SourceState
from wdsync.runner import CommandRunner
from wdsync.status_parser import parse_porcelain_v1_z


def read_source_head(dconfig: DirectionConfig, runner: CommandRunner) -> str | None:
    result = runner.run(
        [dconfig.source_git, "-C", dconfig.source_root_native, "rev-parse", "--verify", "HEAD"],
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout_text().strip()


def read_source_state(dconfig: DirectionConfig, runner: CommandRunner) -> SourceState:
    status_result = runner.run(
        [
            dconfig.source_git,
            "-C",
            dconfig.source_root_native,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ]
    )
    return SourceState(
        head=read_source_head(dconfig, runner),
        entries=parse_porcelain_v1_z(status_result.stdout),
    )

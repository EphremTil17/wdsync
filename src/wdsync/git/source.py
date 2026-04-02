from __future__ import annotations

from collections.abc import Sequence

from wdsync.core.models import DirectionConfig, SourceState
from wdsync.core.runner import CommandRunner
from wdsync.git.status_parser import parse_porcelain_v1_z


def read_head(command: Sequence[str], runner: CommandRunner) -> str | None:
    result = runner.run([*command, "rev-parse", "--verify", "HEAD"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout_text().strip()


def read_repo_source_state(command: Sequence[str], runner: CommandRunner) -> SourceState:
    status_result = runner.run(
        [*command, "status", "--porcelain=v1", "-z", "--untracked-files=all"]
    )
    return SourceState(
        head=read_head(command, runner),
        entries=parse_porcelain_v1_z(status_result.stdout),
    )


def read_source_head(dconfig: DirectionConfig, runner: CommandRunner) -> str | None:
    return read_head(dconfig.source_git_command(), runner)


def read_source_state(dconfig: DirectionConfig, runner: CommandRunner) -> SourceState:
    return read_repo_source_state(dconfig.source_git_command(), runner)

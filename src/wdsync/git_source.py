from __future__ import annotations

from wdsync.models import ProjectConfig, SourceState
from wdsync.runner import CommandRunner
from wdsync.status_parser import parse_porcelain_v1_z


def read_source_head(config: ProjectConfig, runner: CommandRunner) -> str | None:
    result = runner.run(
        ["git.exe", "-C", config.source_root_windows, "rev-parse", "--verify", "HEAD"],
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout_text().strip()


def read_source_state(config: ProjectConfig, runner: CommandRunner) -> SourceState:
    status_result = runner.run(
        [
            "git.exe",
            "-C",
            config.source_root_windows,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ]
    )
    return SourceState(
        head=read_source_head(config, runner),
        entries=parse_porcelain_v1_z(status_result.stdout),
    )

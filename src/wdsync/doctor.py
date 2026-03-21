from __future__ import annotations

from collections.abc import Sequence

from wdsync.models import (
    DestinationState,
    DoctorReport,
    DoctorWarning,
    HeadRelation,
    ProjectConfig,
    RiskLevel,
    Severity,
    SourceState,
)
from wdsync.runner import CommandRunner


def _repo_knows_commit(command: Sequence[str], commit: str, runner: CommandRunner) -> bool:
    result = runner.run([*command, "cat-file", "-e", f"{commit}^{{commit}}"], check=False)
    return result.returncode == 0


def _is_ancestor(command: Sequence[str], older: str, newer: str, runner: CommandRunner) -> bool:
    result = runner.run([*command, "merge-base", "--is-ancestor", older, newer], check=False)
    return result.returncode == 0


def determine_head_relation(
    config: ProjectConfig,
    source_head: str | None,
    destination_head: str | None,
    runner: CommandRunner,
) -> HeadRelation:
    if source_head is None or destination_head is None:
        return HeadRelation.UNKNOWN
    if source_head == destination_head:
        return HeadRelation.SAME

    candidate_commands: tuple[tuple[str, ...], ...] = (
        ("git", "-C", str(config.dest_root)),
        ("git.exe", "-C", config.source_root_windows),
    )
    for command in candidate_commands:
        if not (
            _repo_knows_commit(command, source_head, runner)
            and _repo_knows_commit(command, destination_head, runner)
        ):
            continue
        if _is_ancestor(command, source_head, destination_head, runner):
            return HeadRelation.DESTINATION_AHEAD
        if _is_ancestor(command, destination_head, source_head, runner):
            return HeadRelation.SOURCE_AHEAD
        merge_base = runner.run(
            [*command, "merge-base", source_head, destination_head],
            check=False,
        )
        return HeadRelation.DIVERGED if merge_base.returncode == 0 else HeadRelation.DIFFERENT

    return HeadRelation.DIFFERENT


def build_doctor_report(
    config: ProjectConfig,
    source_state: SourceState,
    destination_state: DestinationState,
    runner: CommandRunner,
) -> DoctorReport:
    head_relation = determine_head_relation(
        config,
        source_state.head,
        destination_state.head,
        runner,
    )
    warnings: list[DoctorWarning] = []

    if source_state.head != destination_state.head:
        warnings.append(
            DoctorWarning(
                code="head-mismatch",
                message=(
                    "source and destination HEAD differ"
                    if head_relation is HeadRelation.DIFFERENT
                    else f"source and destination HEAD relation is {head_relation.value}"
                ),
                severity=Severity.WARNING,
            )
        )

    if destination_state.is_dirty:
        warnings.append(
            DoctorWarning(
                code="destination-dirty",
                message="destination repo is not clean",
                severity=Severity.WARNING,
            )
        )

    return DoctorReport(
        source_head=source_state.head,
        destination_head=destination_state.head,
        source_dirty_count=len(source_state.entries),
        head_relation=head_relation,
        destination_state=destination_state,
        warnings=tuple(warnings),
        risk_level=RiskLevel.MEDIUM if warnings else RiskLevel.LOW,
    )

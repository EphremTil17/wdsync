from __future__ import annotations

from collections.abc import Callable, Sequence

from wdsync.core.models import (
    DestinationState,
    DirectionConfig,
    DoctorReport,
    DoctorWarning,
    HeadRelation,
    RiskLevel,
    Severity,
    SourceState,
)
from wdsync.core.runner import CommandRunner


def _repo_knows_commit(command: Sequence[str], commit: str, runner: CommandRunner) -> bool:
    result = runner.run([*command, "cat-file", "-e", f"{commit}^{{commit}}"], check=False)
    return result.returncode == 0


def _is_ancestor(command: Sequence[str], older: str, newer: str, runner: CommandRunner) -> bool:
    result = runner.run([*command, "merge-base", "--is-ancestor", older, newer], check=False)
    return result.returncode == 0


def determine_head_relation(
    dconfig: DirectionConfig,
    source_head: str | None,
    destination_head: str | None,
    runner: CommandRunner,
    *,
    peer_compare_heads: Callable[[str, str], HeadRelation] | None = None,
) -> HeadRelation:
    if source_head is None or destination_head is None:
        return HeadRelation.UNKNOWN
    if source_head == destination_head:
        return HeadRelation.SAME

    if dconfig.source_is_local:
        local_command = tuple(dconfig.source_git_command())
    else:
        local_command = tuple(dconfig.dest_git_command())
    relation = determine_head_relation_from_command(
        local_command,
        source_head,
        destination_head,
        runner,
    )
    if relation is not None:
        return relation
    if peer_compare_heads is not None:
        return peer_compare_heads(source_head, destination_head)

    return HeadRelation.DIFFERENT


def determine_head_relation_from_command(
    command: Sequence[str],
    source_head: str,
    destination_head: str,
    runner: CommandRunner,
) -> HeadRelation | None:
    if not (
        _repo_knows_commit(command, source_head, runner)
        and _repo_knows_commit(command, destination_head, runner)
    ):
        return None
    if _is_ancestor(command, source_head, destination_head, runner):
        return HeadRelation.DESTINATION_AHEAD
    if _is_ancestor(command, destination_head, source_head, runner):
        return HeadRelation.SOURCE_AHEAD
    merge_base = runner.run(
        [*command, "merge-base", source_head, destination_head],
        check=False,
    )
    return HeadRelation.DIVERGED if merge_base.returncode == 0 else HeadRelation.DIFFERENT


def build_doctor_report(
    dconfig: DirectionConfig,
    source_state: SourceState,
    destination_state: DestinationState,
    runner: CommandRunner,
    *,
    peer_compare_heads: Callable[[str, str], HeadRelation] | None = None,
) -> DoctorReport:
    head_relation = determine_head_relation(
        dconfig,
        source_state.head,
        destination_state.head,
        runner,
        peer_compare_heads=peer_compare_heads,
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

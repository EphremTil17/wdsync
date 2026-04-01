from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from wdsync.core.models import (
    DestinationState,
    DirectionConfig,
    DoctorReport,
    HeadRelation,
    RiskLevel,
    SourceState,
    SyncDirection,
)
from wdsync.core.runner import CommandResult, CommandRunner
from wdsync.sync import doctor


class _MergeBaseRunner:
    def __init__(self, returncode: int) -> None:
        self._returncode = returncode

    def run(
        self,
        args: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        del args, cwd, check, env
        return CommandResult(args=("git",), returncode=self._returncode, stdout=b"", stderr=b"")


def _dconfig() -> DirectionConfig:
    return DirectionConfig(
        direction=SyncDirection.FETCH,
        source_root=Path("/tmp/source"),
        source_root_native="/tmp/source",
        source_git="git.exe",
        dest_root=Path("/tmp/dest"),
        dest_root_native="/tmp/dest",
        dest_git="git",
    )


def test_determine_head_relation_handles_unknown_and_same_commit() -> None:
    dconfig = _dconfig()
    fake_runner = cast(CommandRunner, object())

    assert (
        doctor.determine_head_relation(dconfig, None, "abc123", fake_runner) is HeadRelation.UNKNOWN
    )
    assert (
        doctor.determine_head_relation(dconfig, "abc123", "abc123", fake_runner)
        is HeadRelation.SAME
    )


def test_determine_head_relation_detects_destination_ahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def repo_knows_commit(
        command: Sequence[str],
        commit: str,
        runner: CommandRunner,
    ) -> bool:
        del command, commit, runner
        return True

    def is_ancestor(
        command: Sequence[str],
        older: str,
        newer: str,
        runner: CommandRunner,
    ) -> bool:
        del command, runner
        return (older, newer) == ("source", "dest")

    monkeypatch.setattr("wdsync.sync.doctor._repo_knows_commit", repo_knows_commit)
    monkeypatch.setattr("wdsync.sync.doctor._is_ancestor", is_ancestor)

    relation = doctor.determine_head_relation(
        _dconfig(),
        "source",
        "dest",
        cast(CommandRunner, object()),
    )

    assert relation is HeadRelation.DESTINATION_AHEAD


def test_determine_head_relation_detects_source_ahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def repo_knows_commit(
        command: Sequence[str],
        commit: str,
        runner: CommandRunner,
    ) -> bool:
        del command, commit, runner
        return True

    def is_ancestor(
        command: Sequence[str],
        older: str,
        newer: str,
        runner: CommandRunner,
    ) -> bool:
        del command, runner
        return (older, newer) == ("dest", "source")

    monkeypatch.setattr("wdsync.sync.doctor._repo_knows_commit", repo_knows_commit)
    monkeypatch.setattr("wdsync.sync.doctor._is_ancestor", is_ancestor)

    relation = doctor.determine_head_relation(
        _dconfig(),
        "source",
        "dest",
        cast(CommandRunner, object()),
    )

    assert relation is HeadRelation.SOURCE_AHEAD


def test_determine_head_relation_detects_diverged_and_different(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def repo_knows_commit(
        command: Sequence[str],
        commit: str,
        runner: CommandRunner,
    ) -> bool:
        del command, commit, runner
        return True

    def is_ancestor(
        command: Sequence[str],
        older: str,
        newer: str,
        runner: CommandRunner,
    ) -> bool:
        del command, older, newer, runner
        return False

    monkeypatch.setattr("wdsync.sync.doctor._repo_knows_commit", repo_knows_commit)
    monkeypatch.setattr("wdsync.sync.doctor._is_ancestor", is_ancestor)

    diverged = doctor.determine_head_relation(
        _dconfig(),
        "source",
        "dest",
        cast(CommandRunner, _MergeBaseRunner(returncode=0)),
    )
    different = doctor.determine_head_relation(
        _dconfig(),
        "source",
        "dest",
        cast(CommandRunner, _MergeBaseRunner(returncode=1)),
    )

    assert diverged is HeadRelation.DIVERGED
    assert different is HeadRelation.DIFFERENT


def test_determine_head_relation_falls_back_to_different_when_commits_are_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def repo_knows_commit(
        command: Sequence[str],
        commit: str,
        runner: CommandRunner,
    ) -> bool:
        del command, commit, runner
        return False

    monkeypatch.setattr("wdsync.sync.doctor._repo_knows_commit", repo_knows_commit)

    relation = doctor.determine_head_relation(
        _dconfig(),
        "source",
        "dest",
        cast(CommandRunner, object()),
    )

    assert relation is HeadRelation.DIFFERENT


def test_build_doctor_report_marks_clean_repos_as_low_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def determine_head_relation(
        dconfig: DirectionConfig,
        source_head: str | None,
        destination_head: str | None,
        runner: CommandRunner,
    ) -> HeadRelation:
        del dconfig, source_head, destination_head, runner
        return HeadRelation.SAME

    monkeypatch.setattr(doctor, "determine_head_relation", determine_head_relation)

    report = doctor.build_doctor_report(
        _dconfig(),
        SourceState(head="abc123", entries=()),
        DestinationState(
            head="abc123",
            modified_count=0,
            staged_count=0,
            untracked_count=0,
            dirty_paths=frozenset(),
        ),
        cast(CommandRunner, object()),
    )

    assert isinstance(report, DoctorReport)
    assert report.warnings == ()
    assert report.risk_level is RiskLevel.LOW


def test_build_doctor_report_uses_different_message_for_unrelated_heads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def determine_head_relation(
        dconfig: DirectionConfig,
        source_head: str | None,
        destination_head: str | None,
        runner: CommandRunner,
    ) -> HeadRelation:
        del dconfig, source_head, destination_head, runner
        return HeadRelation.DIFFERENT

    monkeypatch.setattr(doctor, "determine_head_relation", determine_head_relation)

    report = doctor.build_doctor_report(
        _dconfig(),
        SourceState(head="source", entries=()),
        DestinationState(
            head="dest",
            modified_count=0,
            staged_count=0,
            untracked_count=0,
            dirty_paths=frozenset(),
        ),
        cast(CommandRunner, object()),
    )

    assert report.warnings[0].code == "head-mismatch"
    assert report.warnings[0].message == "source and destination HEAD differ"

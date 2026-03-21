from __future__ import annotations

import json
from pathlib import Path

from wdsync.formatters import (
    doctor_to_json,
    format_doctor,
    format_preview,
    format_sync_result,
    preview_to_json,
    render_json,
    sync_to_json,
)
from wdsync.models import (
    DestinationState,
    DoctorReport,
    DoctorWarning,
    HeadRelation,
    PreviewRow,
    RiskLevel,
    Severity,
    SyncPlan,
    SyncResult,
)


def _plan() -> SyncPlan:
    return SyncPlan(
        source_root=Path("/tmp/source"),
        dest_root=Path("/tmp/dest"),
        preview_rows=(
            PreviewRow(path="tracked.txt", raw_xy=" M", label="unstaged", syncable=True),
            PreviewRow(path="gone.txt", raw_xy=" D", label="deleted", syncable=False),
        ),
        copy_paths=("tracked.txt",),
        skipped_paths=("gone.txt",),
        warnings=("1 deleted file(s) will be skipped because v1 does not propagate deletions.",),
    )


def _report(*, with_warnings: bool) -> DoctorReport:
    warnings = (
        DoctorWarning(
            code="head-mismatch",
            message="source and destination HEAD relation is diverged",
            severity=Severity.WARNING,
        ),
    )
    return DoctorReport(
        source_head="source-head",
        destination_head="dest-head",
        source_dirty_count=2,
        head_relation=HeadRelation.DIVERGED,
        destination_state=DestinationState(
            head="dest-head",
            modified_count=1,
            staged_count=2,
            untracked_count=3,
        ),
        warnings=warnings if with_warnings else (),
        risk_level=RiskLevel.MEDIUM if with_warnings else RiskLevel.LOW,
    )


def test_preview_and_sync_json_include_expected_fields() -> None:
    plan = _plan()
    preview_payload = preview_to_json(plan)
    sync_payload = sync_to_json(
        SyncResult(plan=plan, copied_count=1, skipped_count=1, performed_copy=True)
    )

    assert preview_payload["schema_version"] == 1
    assert preview_payload["rows"][0]["label"] == "unstaged"
    assert preview_payload["warnings"] == list(plan.warnings)
    assert sync_payload["copied_count"] == 1
    assert sync_payload["performed_copy"] is True


def test_doctor_json_and_render_json_are_stable() -> None:
    payload = doctor_to_json(_report(with_warnings=True))
    rendered = render_json(payload)
    decoded = json.loads(rendered)

    assert decoded["schema_version"] == 1
    assert decoded["warnings"][0]["severity"] == "warning"
    assert decoded["destination"]["is_dirty"] is True


def test_format_preview_covers_empty_and_warning_cases() -> None:
    empty = SyncPlan(
        source_root=Path("/tmp/source"),
        dest_root=Path("/tmp/dest"),
        preview_rows=(),
        copy_paths=(),
        skipped_paths=(),
        warnings=(),
    )

    assert format_preview(empty) == "wdsync: nothing to sync"

    rendered = format_preview(_plan())
    assert "[unstaged" in rendered
    assert "[deleted" in rendered
    assert "warning:" in rendered
    assert "Dry run." in rendered


def test_format_sync_result_covers_copy_and_nothing_to_copy_cases() -> None:
    plan = _plan()
    rendered = format_sync_result(
        SyncResult(plan=plan, copied_count=1, skipped_count=1, performed_copy=True)
    )
    skipped_only = format_sync_result(
        SyncResult(
            plan=SyncPlan(
                source_root=plan.source_root,
                dest_root=plan.dest_root,
                preview_rows=plan.preview_rows,
                copy_paths=(),
                skipped_paths=plan.skipped_paths,
                warnings=plan.warnings,
            ),
            copied_count=0,
            skipped_count=1,
            performed_copy=False,
        )
    )

    assert "Done. Synced 1 file(s)." in rendered
    assert "Skipped 1 deleted file(s)." in rendered
    assert "Nothing to copy into /tmp/dest." in skipped_only


def test_format_doctor_covers_warning_and_clean_output() -> None:
    with_warnings = format_doctor(_report(with_warnings=True))
    without_warnings = format_doctor(_report(with_warnings=False))

    assert "Warnings:" in with_warnings
    assert "source and destination HEAD relation is diverged" in with_warnings
    assert "Warnings:                none" in without_warnings

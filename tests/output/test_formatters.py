from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wdsync.core.models import (
    ConflictRecord,
    DestinationState,
    PreviewRow,
    SourceState,
    StatusKind,
    StatusRecord,
    SyncDirection,
    SyncPlan,
    SyncResult,
)
from wdsync.output.formatters import (
    format_status,
    format_sync_result,
    render_json,
    status_to_json,
    sync_to_json,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(value: str) -> str:
    return _ANSI_RE.sub("", value)


def _plan() -> SyncPlan:
    return SyncPlan(
        source_root=Path("/tmp/source"),
        dest_root=Path("/tmp/dest"),
        preview_rows=(
            PreviewRow(path="tracked.txt", raw_xy=" M", label="unstaged", syncable=True),
            PreviewRow(path="gone.txt", raw_xy=" D", label="deleted", syncable=False),
        ),
        copy_paths=("tracked.txt",),
        delete_paths=("gone.txt",),
        skipped_paths=(),
        warnings=(),
    )


def test_sync_json_includes_expected_fields() -> None:
    plan = _plan()
    payload = sync_to_json(
        SyncResult(plan=plan, copied_count=1, deleted_count=1, skipped_count=0, performed_copy=True)
    )

    assert payload["schema_version"] == 2
    assert payload["copied_count"] == 1
    assert payload["performed_copy"] is True
    assert payload["direction"] == "fetch"


def test_render_json_is_stable() -> None:
    rendered = render_json({"key": "value"})
    decoded = json.loads(rendered)

    assert decoded["key"] == "value"


def test_format_sync_result_covers_copy_and_nothing_to_copy_cases() -> None:
    plan = _plan()
    rendered = format_sync_result(
        SyncResult(plan=plan, copied_count=1, deleted_count=1, skipped_count=0, performed_copy=True)
    )
    skipped_only = format_sync_result(
        SyncResult(
            plan=SyncPlan(
                source_root=plan.source_root,
                dest_root=plan.dest_root,
                preview_rows=plan.preview_rows,
                copy_paths=(),
                delete_paths=(),
                skipped_paths=(),
                warnings=plan.warnings,
            ),
            copied_count=0,
            deleted_count=0,
            skipped_count=0,
            performed_copy=False,
        )
    )

    assert "Done. Synced 1 file(s)." in rendered
    assert "Deleted 1 file(s)." in rendered
    assert "Nothing to copy into /tmp/dest." in skipped_only


def test_format_sync_result_shows_restored_count() -> None:
    plan = _plan()
    rendered = format_sync_result(
        SyncResult(
            plan=plan,
            copied_count=1,
            deleted_count=0,
            skipped_count=0,
            performed_copy=True,
            restored_count=2,
        )
    )

    assert "Restored 2 file(s)." in rendered


def test_sync_json_includes_restored_count() -> None:
    plan = _plan()
    payload = sync_to_json(
        SyncResult(
            plan=plan,
            copied_count=1,
            deleted_count=0,
            skipped_count=0,
            performed_copy=True,
            restored_count=3,
        )
    )

    assert payload["restored_count"] == 3


def test_format_status_shows_unified_view() -> None:
    source = SourceState(
        head="abc",
        entries=(
            StatusRecord(raw_xy=" M", path="file.py", orig_path=None, kind=StatusKind.UNSTAGED),
        ),
    )
    dest = DestinationState(
        head="abc",
        modified_count=0,
        staged_count=0,
        untracked_count=0,
    )

    rendered = format_status(
        direction=SyncDirection.FETCH,
        source_state=source,
        destination_state=dest,
        conflicts=(),
        head_relation="same",
        risk_level="low",
        orphaned_count=0,
    )

    assert "fetch" in rendered
    assert "file.py" in rendered
    assert "Current repo: clean" in rendered
    assert "Peer repo: 1 dirty file(s)" in rendered
    assert "Synced: none" in rendered
    assert "Conflicts: none" in rendered
    assert "HEAD relation:       same" in rendered


def test_format_status_colorizes_sections_for_interactive_terminals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SourceState(
        head="abc",
        entries=(
            StatusRecord(raw_xy=" M", path="file.py", orig_path=None, kind=StatusKind.UNSTAGED),
        ),
    )
    dest = DestinationState(
        head="abc",
        modified_count=0,
        staged_count=0,
        untracked_count=0,
    )
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")

    rendered = format_status(
        direction=SyncDirection.FETCH,
        source_state=source,
        destination_state=dest,
        conflicts=(),
        head_relation="same",
        risk_level="low",
        orphaned_count=0,
    )

    assert "\x1b[" in rendered
    assert _strip_ansi(rendered).count("Current repo: clean") == 1
    assert _strip_ansi(rendered).count("Peer repo: 1 dirty file(s)") == 1
    assert _strip_ansi(rendered).count("Synced: none") == 1
    assert _strip_ansi(rendered).count("Conflicts: none") == 1


def test_format_status_colorizes_git_status_cells_by_meaning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SourceState(
        head="abc",
        entries=(
            StatusRecord(raw_xy="M ", path="staged-mod.py", orig_path=None, kind=StatusKind.STAGED),
            StatusRecord(
                raw_xy=" M",
                path="unstaged-mod.py",
                orig_path=None,
                kind=StatusKind.UNSTAGED,
            ),
            StatusRecord(raw_xy="A ", path="added.py", orig_path=None, kind=StatusKind.ADDED),
            StatusRecord(raw_xy=" D", path="deleted.py", orig_path=None, kind=StatusKind.DELETED),
            StatusRecord(raw_xy="??", path="new.py", orig_path=None, kind=StatusKind.NEW),
        ),
    )
    dest = DestinationState(head="abc", modified_count=0, staged_count=0, untracked_count=0)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")

    rendered = format_status(
        direction=SyncDirection.SEND,
        source_state=source,
        destination_state=dest,
        conflicts=(),
        head_relation="same",
        risk_level="low",
        orphaned_count=0,
    )

    assert "\x1b[38;5;214mM\x1b[0m " in rendered
    assert " \x1b[33mM\x1b[0m" in rendered
    assert "\x1b[32mA\x1b[0m " in rendered
    assert " \x1b[31mD\x1b[0m" in rendered
    assert "\x1b[35m?\x1b[0m\x1b[35m?\x1b[0m" in rendered


def test_format_status_moves_identical_overlaps_into_synced_section() -> None:
    source = SourceState(
        head="abc",
        entries=(
            StatusRecord(raw_xy=" M", path="shared.py", orig_path=None, kind=StatusKind.UNSTAGED),
            StatusRecord(raw_xy="??", path="source-only.py", orig_path=None, kind=StatusKind.NEW),
        ),
    )
    dest = DestinationState(
        head="abc",
        modified_count=1,
        staged_count=0,
        untracked_count=1,
        entries=(
            StatusRecord(raw_xy="M ", path="shared.py", orig_path=None, kind=StatusKind.STAGED),
            StatusRecord(raw_xy="??", path="dest-only.py", orig_path=None, kind=StatusKind.NEW),
        ),
    )

    rendered = format_status(
        direction=SyncDirection.FETCH,
        source_state=source,
        destination_state=dest,
        conflicts=(),
        head_relation="same",
        risk_level="low",
        orphaned_count=0,
    )

    assert "Current repo: 1 dirty file(s)" in rendered
    assert "Peer repo: 1 dirty file(s)" in rendered
    assert "Synced: 1 file(s) already matched on both sides" in rendered
    assert "Relative path" in rendered
    assert "Current : Peer" in rendered
    assert "source-only.py" in rendered
    assert "dest-only.py" in rendered
    assert "shared.py" in rendered
    assert "[M ]:[ M]" in rendered


def test_format_status_lists_current_repo_before_peer_repo() -> None:
    source = SourceState(
        head="abc",
        entries=(
            StatusRecord(raw_xy="??", path="peer-only.py", orig_path=None, kind=StatusKind.NEW),
        ),
    )
    dest = DestinationState(
        head="abc",
        modified_count=1,
        staged_count=0,
        untracked_count=0,
        entries=(
            StatusRecord(
                raw_xy=" M",
                path="current-only.py",
                orig_path=None,
                kind=StatusKind.UNSTAGED,
            ),
        ),
    )

    rendered = format_status(
        direction=SyncDirection.FETCH,
        source_state=source,
        destination_state=dest,
        conflicts=(),
        head_relation="same",
        risk_level="low",
        orphaned_count=0,
    )

    assert rendered.index("Current repo: 1 dirty file(s)") < rendered.index(
        "Peer repo: 1 dirty file(s)"
    )


def test_status_to_json_matches_declared_schema() -> None:
    source = SourceState(
        head="abc",
        entries=(
            StatusRecord(raw_xy=" M", path="file.py", orig_path=None, kind=StatusKind.UNSTAGED),
        ),
    )
    dest = DestinationState(
        head="def",
        modified_count=1,
        staged_count=0,
        untracked_count=0,
        entries=(
            StatusRecord(raw_xy="M ", path="file.py", orig_path=None, kind=StatusKind.STAGED),
        ),
    )
    conflicts = (ConflictRecord(path="file.py", source_xy=" M", dest_xy="M "),)

    payload = status_to_json(
        direction=SyncDirection.FETCH,
        source_state=source,
        destination_state=dest,
        conflicts=conflicts,
        head_relation="diverged",
        risk_level="medium",
        orphaned_count=2,
    )

    assert payload["schema_version"] == 2
    assert payload["source_dirty_count"] == 1
    assert payload["destination_dirty_count"] == 1
    assert payload["conflict_count"] == 1
    assert payload["source_entries"][0]["path"] == "file.py"
    assert payload["destination_entries"][0]["label"] == "staged"
    assert payload["conflicts"][0]["dest_xy"] == "M "

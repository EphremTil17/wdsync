from __future__ import annotations

from wdsync.core.models import DestinationState, SourceState, StatusKind, StatusRecord
from wdsync.sync.conflict import detect_conflicts


def _source_state(*entries: tuple[str, str]) -> SourceState:
    return SourceState(
        head="abc123",
        entries=tuple(
            StatusRecord(raw_xy=xy, path=p, orig_path=None, kind=StatusKind.UNSTAGED)
            for p, xy in entries
        ),
    )


def _dest_state(*entries: tuple[str, str]) -> DestinationState:
    records = tuple(
        StatusRecord(raw_xy=xy, path=p, orig_path=None, kind=StatusKind.UNSTAGED)
        for p, xy in entries
    )
    return DestinationState(
        head="abc123",
        modified_count=len(records),
        staged_count=0,
        untracked_count=0,
        dirty_paths=frozenset(r.path for r in records),
        entries=records,
    )


def test_no_conflicts_when_disjoint() -> None:
    source = _source_state(("a.txt", " M"))
    dest = _dest_state(("b.txt", " M"))

    conflicts = detect_conflicts(source, dest)

    assert conflicts == ()


def test_detects_overlapping_dirty_files() -> None:
    source = _source_state(("shared.txt", " M"), ("only_source.txt", "??"))
    dest = _dest_state(("shared.txt", " M"), ("only_dest.txt", " M"))

    conflicts = detect_conflicts(source, dest)

    assert len(conflicts) == 1
    assert conflicts[0].path == "shared.txt"
    assert conflicts[0].source_xy == " M"
    assert conflicts[0].dest_xy == " M"


def test_no_conflicts_when_both_clean() -> None:
    source = SourceState(head="abc123", entries=())
    dest = DestinationState(head="abc123", modified_count=0, staged_count=0, untracked_count=0)

    conflicts = detect_conflicts(source, dest)

    assert conflicts == ()


def test_multiple_conflicts_sorted() -> None:
    source = _source_state(("z.txt", " M"), ("a.txt", " M"))
    dest = _dest_state(("a.txt", "M "), ("z.txt", " M"))

    conflicts = detect_conflicts(source, dest)

    assert len(conflicts) == 2
    assert conflicts[0].path == "a.txt"
    assert conflicts[1].path == "z.txt"

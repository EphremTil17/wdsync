from __future__ import annotations

from wdsync.models import StatusKind
from wdsync.status_parser import classify_status


def test_supported_status_labels_map_correctly() -> None:
    assert classify_status("??") is StatusKind.NEW
    assert classify_status(" M") is StatusKind.UNSTAGED
    assert classify_status("M ") is StatusKind.STAGED
    assert classify_status("MM") is StatusKind.BOTH
    assert classify_status("A ") is StatusKind.ADDED
    assert classify_status("AM") is StatusKind.ADDED_MODIFIED
    assert classify_status("R ") is StatusKind.RENAMED
    assert classify_status("RM") is StatusKind.RENAMED
    assert classify_status("C ") is StatusKind.COPIED
    assert classify_status("CM") is StatusKind.COPIED
    assert classify_status(" D") is StatusKind.DELETED
    assert classify_status("D ") is StatusKind.DELETED
    assert classify_status("DD") is StatusKind.DELETED

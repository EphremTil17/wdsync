from __future__ import annotations

import pytest

from wdsync.exceptions import StatusParseError
from wdsync.models import StatusKind
from wdsync.status_parser import parse_porcelain_v1_z


def test_parse_basic_status_records() -> None:
    payload = (
        b" M tracked.txt\0M  staged.txt\0MM both.txt\0?? new.txt\0A  added.txt\0AM added_mod.txt\0"
    )
    entries = parse_porcelain_v1_z(payload)

    assert [entry.raw_xy for entry in entries] == [" M", "M ", "MM", "??", "A ", "AM"]
    assert [entry.kind for entry in entries] == [
        StatusKind.UNSTAGED,
        StatusKind.STAGED,
        StatusKind.BOTH,
        StatusKind.NEW,
        StatusKind.ADDED,
        StatusKind.ADDED_MODIFIED,
    ]


def test_parse_rename_and_copy_records_under_z_mode() -> None:
    payload = b"R  new_name.txt\0old_name.txt\0C  copy.txt\0source.txt\0"
    entries = parse_porcelain_v1_z(payload)

    assert len(entries) == 2
    assert entries[0].raw_xy == "R "
    assert entries[0].path == "new_name.txt"
    assert entries[0].orig_path == "old_name.txt"
    assert entries[0].kind is StatusKind.RENAMED
    assert entries[1].raw_xy == "C "
    assert entries[1].path == "copy.txt"
    assert entries[1].orig_path == "source.txt"
    assert entries[1].kind is StatusKind.COPIED


def test_parse_deleted_records() -> None:
    payload = b" D gone.txt\0D  staged_gone.txt\0DD both_gone.txt\0"
    entries = parse_porcelain_v1_z(payload)

    assert [entry.kind for entry in entries] == [
        StatusKind.DELETED,
        StatusKind.DELETED,
        StatusKind.DELETED,
    ]


def test_parse_porcelain_rejects_malformed_entries() -> None:
    with pytest.raises(StatusParseError):
        parse_porcelain_v1_z(b"not-valid\0")


def test_parse_porcelain_rejects_rename_without_source_path() -> None:
    with pytest.raises(StatusParseError):
        parse_porcelain_v1_z(b"R  renamed.txt\0")

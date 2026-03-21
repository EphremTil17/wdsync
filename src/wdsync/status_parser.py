from __future__ import annotations

from wdsync.exceptions import StatusParseError
from wdsync.models import StatusKind, StatusRecord


def _decode_token(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape")


def classify_status(raw_xy: str) -> StatusKind:
    if raw_xy == "??":
        return StatusKind.NEW
    if raw_xy == " M":
        return StatusKind.UNSTAGED
    if raw_xy == "M ":
        return StatusKind.STAGED
    if raw_xy == "MM":
        return StatusKind.BOTH
    if raw_xy == "A ":
        return StatusKind.ADDED
    if raw_xy == "AM":
        return StatusKind.ADDED_MODIFIED
    if raw_xy in {"R ", "RM"}:
        return StatusKind.RENAMED
    if raw_xy in {"C ", "CM"}:
        return StatusKind.COPIED
    if raw_xy in {" D", "D ", "DD"}:
        return StatusKind.DELETED
    return StatusKind.CHANGED


def is_syncable_status(raw_xy: str) -> bool:
    return classify_status(raw_xy) is not StatusKind.DELETED


def parse_porcelain_v1_z(payload: bytes) -> tuple[StatusRecord, ...]:
    if not payload:
        return ()

    tokens = payload.split(b"\0")
    entries: list[StatusRecord] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if not token:
            index += 1
            continue

        text = _decode_token(token)
        if len(text) < 4 or text[2] != " ":
            raise StatusParseError(f"wdsync: malformed porcelain entry: {text!r}")

        raw_xy = text[:2]
        path = text[3:]
        orig_path: str | None = None

        if raw_xy[0] in {"R", "C"}:
            try:
                next_token = tokens[index + 1]
            except IndexError as exc:
                raise StatusParseError(
                    "wdsync: rename/copy status entry is missing its source path."
                ) from exc
            if not next_token:
                raise StatusParseError(
                    "wdsync: rename/copy status entry is missing its source path."
                )
            orig_path = _decode_token(next_token)
            index += 1

        entries.append(
            StatusRecord(
                raw_xy=raw_xy,
                path=path,
                orig_path=orig_path,
                kind=classify_status(raw_xy),
            )
        )
        index += 1

    return tuple(entries)

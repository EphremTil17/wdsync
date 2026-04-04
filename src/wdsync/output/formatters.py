from __future__ import annotations

import json
import os
import sys
from typing import NamedTuple

from wdsync.core.models import (
    ConflictRecord,
    DestinationState,
    PreviewRowJSON,
    SourceState,
    StatusJSON,
    StatusRecord,
    SyncDirection,
    SyncJSON,
    SyncPlan,
    SyncResult,
)
from wdsync.git.status_parser import is_syncable_status

_SCHEMA_VERSION = 2
_ANSI_RESET = "\x1b[0m"
_ANSI_CYAN = "\x1b[36m"
_ANSI_GREEN = "\x1b[32m"
_ANSI_YELLOW = "\x1b[33m"
_ANSI_RED = "\x1b[31m"
_ANSI_MAGENTA = "\x1b[35m"
_ANSI_ORANGE = "\x1b[38;5;214m"
_ANSI_DIM = "\x1b[2m"


class _MatchedStatus(NamedTuple):
    path: str
    source_xy: str
    dest_xy: str


def _preview_rows_to_json(plan: SyncPlan) -> list[PreviewRowJSON]:
    return [
        {
            "path": row.path,
            "raw_status": row.raw_xy,
            "label": row.label,
            "syncable": row.syncable,
        }
        for row in plan.preview_rows
    ]


def sync_to_json(result: SyncResult) -> SyncJSON:
    return {
        "schema_version": _SCHEMA_VERSION,
        "direction": result.plan.direction.value,
        "source_root": str(result.plan.source_root),
        "dest_root": str(result.plan.dest_root),
        "total": len(result.plan.preview_rows),
        "copied_count": result.copied_count,
        "deleted_count": result.deleted_count,
        "restored_count": result.restored_count,
        "skipped_count": result.skipped_count,
        "performed_copy": result.performed_copy,
        "warnings": list(result.plan.warnings),
        "rows": _preview_rows_to_json(result.plan),
    }


def _status_entries_to_json(state: SourceState | DestinationState) -> list[PreviewRowJSON]:
    return [
        {
            "path": entry.path,
            "raw_status": entry.raw_xy,
            "label": entry.kind.value,
            "syncable": is_syncable_status(entry.raw_xy),
        }
        for entry in state.entries
    ]


def status_to_json(
    *,
    direction: SyncDirection,
    source_state: SourceState,
    destination_state: DestinationState,
    conflicts: tuple[ConflictRecord, ...],
    head_relation: str,
    risk_level: str,
    orphaned_count: int,
) -> StatusJSON:
    return {
        "schema_version": _SCHEMA_VERSION,
        "direction": direction.value,
        "source_dirty_count": len(source_state.entries),
        "destination_dirty_count": len(destination_state.entries),
        "conflict_count": len(conflicts),
        "head_relation": head_relation,
        "risk_level": risk_level,
        "orphaned_count": orphaned_count,
        "source_entries": _status_entries_to_json(source_state),
        "destination_entries": _status_entries_to_json(destination_state),
        "conflicts": [
            {
                "path": conflict.path,
                "source_xy": conflict.source_xy,
                "dest_xy": conflict.dest_xy,
            }
            for conflict in conflicts
        ],
    }


def render_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _colors_enabled() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    return sys.stderr.isatty()


def _colorize(text: str, ansi: str) -> str:
    if not _colors_enabled():
        return text
    return f"{ansi}{text}{_ANSI_RESET}"


def _dim(text: str) -> str:
    return _colorize(text, _ANSI_DIM)


def _sync_hint(direction: SyncDirection) -> str:
    if direction is SyncDirection.SEND:
        return "Run 'wdsync send' to sync"
    return "Run 'wdsync fetch' to sync"


def _current_peer_entries(
    direction: SyncDirection,
    *,
    source_only: tuple[StatusRecord, ...],
    destination_only: tuple[StatusRecord, ...],
) -> tuple[tuple[StatusRecord, ...], tuple[StatusRecord, ...]]:
    if direction is SyncDirection.FETCH:
        return destination_only, source_only
    return source_only, destination_only


def _current_peer_statuses(
    direction: SyncDirection,
    *,
    source_xy: str,
    dest_xy: str,
) -> tuple[str, str]:
    if direction is SyncDirection.FETCH:
        return dest_xy, source_xy
    return source_xy, dest_xy


def _status_char_ansi(char: str, *, slot: int) -> str | None:
    if char == "M":
        return _ANSI_ORANGE if slot == 0 else _ANSI_YELLOW
    if char == "A":
        return _ANSI_GREEN
    if char == "D":
        return _ANSI_RED
    if char == "?":
        return _ANSI_MAGENTA
    if char == "R":
        return _ANSI_CYAN
    if char == "C":
        return _ANSI_CYAN
    return None


def _format_raw_xy(raw_xy: str) -> str:
    formatted: list[str] = []
    for slot, char in enumerate(raw_xy):
        ansi = _status_char_ansi(char, slot=slot)
        formatted.append(_colorize(char, ansi) if ansi is not None else char)
    return "".join(formatted)


def _comparison_table_lines(
    rows: tuple[tuple[str, str, str], ...],
    *,
    direction: SyncDirection,
) -> list[str]:
    path_header = "Relative path"
    status_header = "Current : Peer"
    status_width = len("[MM]:[MM]")
    path_width = max(len(path_header), *(len(path) for path, _, _ in rows))
    lines = [f"    {path_header:<{path_width}}  {status_header:>{status_width}}"]
    for path, source_xy, dest_xy in rows:
        current_xy, peer_xy = _current_peer_statuses(
            direction,
            source_xy=source_xy,
            dest_xy=dest_xy,
        )
        lines.append(
            f"    {path:<{path_width}}  [{_format_raw_xy(current_xy)}]:[{_format_raw_xy(peer_xy)}]"
        )
    return lines


def _partition_status_entries(
    source_state: SourceState,
    destination_state: DestinationState,
    conflicts: tuple[ConflictRecord, ...],
) -> tuple[tuple[StatusRecord, ...], tuple[StatusRecord, ...], tuple[_MatchedStatus, ...]]:
    source_map = {entry.path: entry for entry in source_state.entries}
    dest_map = {entry.path: entry for entry in destination_state.entries}
    overlap_paths = source_map.keys() & dest_map.keys()
    conflict_paths = {conflict.path for conflict in conflicts}
    synced_paths = sorted(overlap_paths - conflict_paths)
    synced = tuple(
        _MatchedStatus(
            path=path,
            source_xy=source_map[path].raw_xy,
            dest_xy=dest_map[path].raw_xy,
        )
        for path in synced_paths
    )
    source_only = tuple(entry for entry in source_state.entries if entry.path not in overlap_paths)
    destination_only = tuple(
        entry for entry in destination_state.entries if entry.path not in overlap_paths
    )
    return source_only, destination_only, synced


def format_sync_result(result: SyncResult) -> str:
    has_actions = bool(result.plan.preview_rows or result.restored_count or result.deleted_count)
    if not has_actions:
        return "wdsync: nothing to sync"

    lines: list[str] = []
    if result.plan.preview_rows:
        lines.append(f"wdsync: {len(result.plan.preview_rows)} file(s):")
        lines.append("")
        for row in result.plan.preview_rows:
            lines.append(f"  [{row.label:<9}] [{row.raw_xy}]  {row.path}")

    if result.plan.warnings:
        lines.append("")
        for warning in result.plan.warnings:
            lines.append(f"  warning: {warning}")

    lines.append("")
    if result.performed_copy:
        lines.append(f"Syncing {result.plan.source_root} -> {result.plan.dest_root} ...")
        lines.append(f"Done. Synced {result.copied_count} file(s).")
    if result.restored_count:
        lines.append(f"Restored {result.restored_count} file(s).")
    if result.deleted_count:
        lines.append(f"Deleted {result.deleted_count} file(s).")
    if result.skipped_count:
        lines.append(f"Skipped {result.skipped_count} file(s).")
    if not result.performed_copy and not result.restored_count and not result.deleted_count:
        lines.append(f"Nothing to copy into {result.plan.dest_root}.")
    return "\n".join(lines)


def format_status(
    direction: SyncDirection,
    source_state: SourceState,
    destination_state: DestinationState,
    conflicts: tuple[ConflictRecord, ...],
    head_relation: str,
    risk_level: str,
    orphaned_count: int,
) -> str:
    dir_label = (
        "fetch (Windows → WSL)" if direction is SyncDirection.FETCH else "send (WSL → Windows)"
    )
    lines = [f"wdsync status: {dir_label}", ""]
    source_only, destination_only, synced = _partition_status_entries(
        source_state,
        destination_state,
        conflicts,
    )
    current_only, peer_only = _current_peer_entries(
        direction,
        source_only=source_only,
        destination_only=destination_only,
    )

    if current_only:
        lines.append(_colorize(f"  Current repo: {len(current_only)} dirty file(s)", _ANSI_CYAN))
        for entry in current_only:
            lines.append(
                f"    [{entry.kind.value:<9}] [{_format_raw_xy(entry.raw_xy)}]  {entry.path}"
            )
    else:
        lines.append(_colorize("  Current repo: clean", _ANSI_CYAN))

    lines.append("")
    if peer_only:
        lines.append(
            _colorize(
                f"  Peer repo: {len(peer_only)} dirty file(s)",
                _ANSI_GREEN,
            )
        )
        for entry in peer_only:
            lines.append(
                f"    [{entry.kind.value:<9}] [{_format_raw_xy(entry.raw_xy)}]  {entry.path}"
            )
    else:
        lines.append(_colorize("  Peer repo: clean", _ANSI_GREEN))

    lines.append("")
    if synced:
        lines.append(
            _colorize(
                f"  Synced: {len(synced)} file(s) already matched on both sides",
                _ANSI_MAGENTA,
            )
        )
        lines.extend(
            _comparison_table_lines(
                tuple((entry.path, entry.source_xy, entry.dest_xy) for entry in synced),
                direction=direction,
            )
        )
    else:
        lines.append(_colorize("  Synced: none", _ANSI_MAGENTA))

    lines.append("")
    if conflicts:
        lines.append(
            _colorize(
                f"  Conflicts: {len(conflicts)} file(s) modified on both sides",
                _ANSI_YELLOW,
            )
        )
        lines.extend(
            _comparison_table_lines(
                tuple(
                    (conflict.path, conflict.source_xy, conflict.dest_xy) for conflict in conflicts
                ),
                direction=direction,
            )
        )
    else:
        lines.append(_colorize("  Conflicts: none", _ANSI_YELLOW))

    lines.extend(
        [
            "",
            _dim(f"  HEAD relation:       {head_relation}"),
            _dim(f"  Risk level:          {risk_level}"),
            _dim(f"  Orphaned mirrored:   {orphaned_count}"),
            "",
        ]
    )

    if conflicts:
        lines.append(_colorize("  Conflicts will be skipped unless --force is used.", _ANSI_YELLOW))
    hint = _sync_hint(direction)
    lines.append(f"  {hint}")
    return "\n".join(lines)

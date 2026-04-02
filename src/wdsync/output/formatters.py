from __future__ import annotations

import json
import os
import sys

from wdsync.core.models import (
    ConflictRecord,
    DestinationState,
    PreviewRowJSON,
    SourceState,
    StatusJSON,
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
_ANSI_DIM = "\x1b[2m"


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

    if source_state.entries:
        lines.append(_colorize(f"  Source: {len(source_state.entries)} dirty file(s)", _ANSI_CYAN))
        for entry in source_state.entries:
            lines.append(f"    [{entry.kind.value:<9}] [{entry.raw_xy}]  {entry.path}")
    else:
        lines.append(_colorize("  Source: clean", _ANSI_CYAN))

    lines.append("")
    dest_entry_count = len(destination_state.entries)
    if dest_entry_count:
        lines.append(_colorize(f"  Destination: {dest_entry_count} dirty file(s)", _ANSI_GREEN))
        for entry in destination_state.entries:
            lines.append(f"    [{entry.kind.value:<9}] [{entry.raw_xy}]  {entry.path}")
    else:
        lines.append(_colorize("  Destination: clean", _ANSI_GREEN))

    lines.append("")
    if conflicts:
        lines.append(
            _colorize(
                f"  Conflicts: {len(conflicts)} file(s) modified on both sides",
                _ANSI_YELLOW,
            )
        )
        for c in conflicts:
            lines.append(f"    {c.path}  (source: {c.source_xy}, dest: {c.dest_xy})")
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

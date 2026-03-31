from __future__ import annotations

import json

from wdsync.models import (
    DestinationStateJSON,
    DoctorJSON,
    DoctorReport,
    DoctorWarningJSON,
    PreviewJSON,
    PreviewRowJSON,
    SyncDirection,
    SyncJSON,
    SyncPlan,
    SyncResult,
)

_SCHEMA_VERSION = 2


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


def preview_to_json(plan: SyncPlan) -> PreviewJSON:
    return {
        "schema_version": _SCHEMA_VERSION,
        "direction": plan.direction.value,
        "source_root": str(plan.source_root),
        "dest_root": str(plan.dest_root),
        "total": len(plan.preview_rows),
        "syncable_count": len(plan.copy_paths),
        "skipped_count": len(plan.skipped_paths),
        "warnings": list(plan.warnings),
        "rows": _preview_rows_to_json(plan),
    }


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


def doctor_to_json(report: DoctorReport) -> DoctorJSON:
    destination: DestinationStateJSON = {
        "head": report.destination_state.head,
        "modified_count": report.destination_state.modified_count,
        "staged_count": report.destination_state.staged_count,
        "untracked_count": report.destination_state.untracked_count,
        "is_dirty": report.destination_state.is_dirty,
    }
    warnings: list[DoctorWarningJSON] = [
        {
            "code": warning.code,
            "message": warning.message,
            "severity": warning.severity.value,
        }
        for warning in report.warnings
    ]
    return {
        "schema_version": _SCHEMA_VERSION,
        "source_head": report.source_head,
        "destination_head": report.destination_head,
        "source_dirty_count": report.source_dirty_count,
        "head_relation": report.head_relation.value,
        "risk_level": report.risk_level.value,
        "destination": destination,
        "warnings": warnings,
    }


def render_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _sync_hint(direction: SyncDirection) -> str:
    if direction is SyncDirection.SEND:
        return "Run 'wdsync send' to sync"
    return "Run 'wdsync fetch' or 'wdsync sync' or 'wdsync -f' to sync"


def format_preview(plan: SyncPlan) -> str:
    if not plan.preview_rows:
        return "wdsync: nothing to sync"

    lines = [f"wdsync: {len(plan.preview_rows)} file(s):", ""]
    for row in plan.preview_rows:
        lines.append(f"  [{row.label:<9}] [{row.raw_xy}]  {row.path}")

    if plan.warnings:
        lines.append("")
        for warning in plan.warnings:
            lines.append(f"  warning: {warning}")

    lines.extend(
        [
            "",
            f"  Dry run. {_sync_hint(plan.direction)} -> {plan.dest_root}",
        ]
    )
    return "\n".join(lines)


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


def format_doctor(report: DoctorReport) -> str:
    source_status = "dirty" if report.source_dirty_count else "clean"
    destination_status = "dirty" if report.destination_state.is_dirty else "clean"
    lines = [
        f"Source status:           {source_status}",
        f"Destination status:      {destination_status}",
        f"Source HEAD:             {report.source_head or 'unavailable'}",
        f"Destination HEAD:        {report.destination_head or 'unavailable'}",
        f"HEAD relation:           {report.head_relation.value}",
        f"Destination modified:    {report.destination_state.modified_count}",
        f"Destination staged:      {report.destination_state.staged_count}",
        f"Destination untracked:   {report.destination_state.untracked_count}",
        f"Risk level:              {report.risk_level.value}",
    ]
    if report.warnings:
        lines.append("Warnings:")
        for warning in report.warnings:
            lines.append(f"  - {warning.message}")
    else:
        lines.append("Warnings:                none")
    return "\n".join(lines)

from __future__ import annotations

from wdsync.core.models import DirectionConfig, PreviewRow, SourceState, StatusKind, SyncPlan
from wdsync.git.status_parser import is_syncable_status


def build_sync_plan(dconfig: DirectionConfig, source_state: SourceState) -> SyncPlan:
    preview_rows: list[PreviewRow] = []
    copy_paths: list[str] = []
    delete_paths: list[str] = []
    skipped_paths: list[str] = []
    warnings: list[str] = []
    seen_paths: set[str] = set()

    for entry in source_state.entries:
        if entry.path in seen_paths:
            continue
        seen_paths.add(entry.path)

        syncable = is_syncable_status(entry.raw_xy)
        preview_rows.append(
            PreviewRow(
                path=entry.path,
                raw_xy=entry.raw_xy,
                label=entry.kind.value,
                syncable=syncable,
            )
        )
        if syncable:
            copy_paths.append(entry.path)
        elif entry.kind is StatusKind.DELETED:
            delete_paths.append(entry.path)
        else:
            skipped_paths.append(entry.path)

    return SyncPlan(
        source_root=dconfig.source_root,
        dest_root=dconfig.dest_root,
        preview_rows=tuple(preview_rows),
        copy_paths=tuple(copy_paths),
        delete_paths=tuple(delete_paths),
        skipped_paths=tuple(skipped_paths),
        warnings=tuple(warnings),
        direction=dconfig.direction,
    )

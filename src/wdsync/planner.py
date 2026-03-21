from __future__ import annotations

from wdsync.models import PreviewRow, ProjectConfig, SourceState, SyncPlan
from wdsync.status_parser import is_syncable_status


def build_sync_plan(config: ProjectConfig, source_state: SourceState) -> SyncPlan:
    preview_rows: list[PreviewRow] = []
    copy_paths: list[str] = []
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
        else:
            skipped_paths.append(entry.path)

    if skipped_paths:
        warnings.append(
            f"{len(skipped_paths)} deleted file(s) will be skipped "
            "because v1 does not propagate deletions."
        )

    return SyncPlan(
        source_root=config.source_root,
        dest_root=config.dest_root,
        preview_rows=tuple(preview_rows),
        copy_paths=tuple(copy_paths),
        skipped_paths=tuple(skipped_paths),
        warnings=tuple(warnings),
    )

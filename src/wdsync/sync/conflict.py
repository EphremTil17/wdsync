from __future__ import annotations

from collections.abc import Mapping

from wdsync.core.models import ConflictRecord, DestinationState, SourceState


def detect_conflicts(
    source_state: SourceState,
    destination_state: DestinationState,
) -> tuple[ConflictRecord, ...]:
    source_map = {entry.path: entry.raw_xy for entry in source_state.entries}
    dest_map = {entry.path: entry.raw_xy for entry in destination_state.entries}
    overlapping = source_map.keys() & dest_map.keys()
    return tuple(
        ConflictRecord(path=p, source_xy=source_map[p], dest_xy=dest_map[p])
        for p in sorted(overlapping)
    )


def filter_equivalent_conflicts(
    conflicts: tuple[ConflictRecord, ...],
    *,
    source_fingerprints: Mapping[str, str | None],
    dest_fingerprints: Mapping[str, str | None],
) -> tuple[ConflictRecord, ...]:
    return tuple(
        conflict
        for conflict in conflicts
        if source_fingerprints.get(conflict.path) != dest_fingerprints.get(conflict.path)
    )

from __future__ import annotations

from pathlib import Path

from wdsync.core.models import DirectionConfig, SyncContext
from wdsync.core.runner import CommandRunner
from wdsync.git.dest import read_destination_state
from wdsync.git.source import read_source_state
from wdsync.sync.conflict import detect_conflicts
from wdsync.sync.doctor import build_doctor_report
from wdsync.sync.manifest import read_manifest


def build_sync_context(
    dconfig: DirectionConfig,
    runner: CommandRunner,
    state_path: Path,
) -> SyncContext:
    source_state = read_source_state(dconfig, runner)
    destination_state = read_destination_state(dconfig, runner)
    conflicts = detect_conflicts(source_state, destination_state)
    doctor_report = build_doctor_report(dconfig, source_state, destination_state, runner)
    manifest_untracked = read_manifest(state_path)
    source_dirty_paths = frozenset(entry.path for entry in source_state.entries)
    orphaned_paths = manifest_untracked - source_dirty_paths

    return SyncContext(
        dconfig=dconfig,
        source_state=source_state,
        destination_state=destination_state,
        conflicts=conflicts,
        doctor_report=doctor_report,
        manifest_untracked=manifest_untracked,
        orphaned_paths=orphaned_paths,
    )

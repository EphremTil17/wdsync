from __future__ import annotations

from pathlib import Path

from wdsync.core.exceptions import PeerConnectionError
from wdsync.core.models import DestinationState, DirectionConfig, SourceState, SyncContext
from wdsync.core.runner import CommandRunner
from wdsync.git.dest import read_destination_state
from wdsync.git.source import read_source_state
from wdsync.rpc.session import PeerSession
from wdsync.sync.conflict import detect_conflicts
from wdsync.sync.doctor import build_doctor_report
from wdsync.sync.manifest import read_manifest


def build_sync_context(
    dconfig: DirectionConfig,
    runner: CommandRunner,
    state_path: Path,
    *,
    peer_session: PeerSession | None = None,
) -> SyncContext:
    source_state = _read_source_state(dconfig, runner, peer_session=peer_session)
    destination_state = _read_destination_state(dconfig, runner, peer_session=peer_session)
    conflicts = detect_conflicts(source_state, destination_state)
    doctor_report = build_doctor_report(
        dconfig,
        source_state,
        destination_state,
        runner,
        peer_compare_heads=peer_session.compare_heads if peer_session is not None else None,
    )
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


def _read_source_state(
    dconfig: DirectionConfig,
    runner: CommandRunner,
    *,
    peer_session: PeerSession | None,
) -> SourceState:
    if dconfig.source_is_local:
        return read_source_state(dconfig, runner)
    if peer_session is None:
        raise PeerConnectionError("wdsync: peer session is required when source is remote")
    state = peer_session.status()
    return SourceState(head=state.head, entries=state.entries)


def _read_destination_state(
    dconfig: DirectionConfig,
    runner: CommandRunner,
    *,
    peer_session: PeerSession | None,
) -> DestinationState:
    if dconfig.destination_is_local:
        return read_destination_state(dconfig, runner)
    if peer_session is None:
        raise PeerConnectionError("wdsync: peer session is required when destination is remote")
    return peer_session.status()

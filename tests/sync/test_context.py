from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from wdsync.core.exceptions import PeerConnectionError
from wdsync.core.models import (
    DestinationState,
    DirectionConfig,
    GitExecution,
    HeadRelation,
    RepoEndpoint,
    SourceState,
    StatusKind,
    StatusRecord,
    SyncDirection,
    TransferExecution,
)
from wdsync.core.runner import CommandRunner
from wdsync.rpc.session import PeerSession
from wdsync.sync.context import build_sync_context
from wdsync.sync.manifest import write_manifest


class _FakePeerSession:
    def __init__(
        self,
        state: DestinationState,
        *,
        compare_result: HeadRelation = HeadRelation.DIFFERENT,
        manifest_paths: frozenset[str] = frozenset(),
    ) -> None:
        self._state = state
        self._compare_result = compare_result
        self._manifest_paths = manifest_paths
        self.compared: list[tuple[str, str]] = []

    def status(self) -> DestinationState:
        return self._state

    def read_manifest(self) -> frozenset[str]:
        return self._manifest_paths

    def compare_heads(self, source_head: str, destination_head: str) -> HeadRelation:
        self.compared.append((source_head, destination_head))
        return self._compare_result


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _fetch_dconfig(local_repo: Path) -> DirectionConfig:
    return DirectionConfig(
        direction=SyncDirection.FETCH,
        source=RepoEndpoint(root=Path("/peer"), native_root="/peer"),
        destination=RepoEndpoint(root=local_repo, native_root=str(local_repo)),
        source_git=GitExecution(command_argv=("git",), repo_native_root="/peer"),
        destination_git=GitExecution(command_argv=("git",), repo_native_root=str(local_repo)),
        transfer=TransferExecution(
            command_argv=("rsync",),
            source_root="/peer",
            dest_root=str(local_repo),
        ),
        source_is_local=False,
        destination_is_local=True,
        peer_command_argv=("python", "-m", "wdsync"),
    )


def _send_dconfig(local_repo: Path) -> DirectionConfig:
    return DirectionConfig(
        direction=SyncDirection.SEND,
        source=RepoEndpoint(root=local_repo, native_root=str(local_repo)),
        destination=RepoEndpoint(root=Path("/peer"), native_root="/peer"),
        source_git=GitExecution(command_argv=("git",), repo_native_root=str(local_repo)),
        destination_git=GitExecution(command_argv=("git",), repo_native_root="/peer"),
        transfer=TransferExecution(
            command_argv=("rsync",),
            source_root=str(local_repo),
            dest_root="/peer",
        ),
        source_is_local=True,
        destination_is_local=False,
        peer_command_argv=("python", "-m", "wdsync"),
    )


def test_build_sync_context_merges_local_and_remote_manifest_orphans(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    tmp_path: Path,
) -> None:
    local_repo = repo_factory("dest", files={"tracked.txt": "base\n"})
    local_head = _head(local_repo)
    state_path = tmp_path / "state"
    write_manifest(state_path, frozenset({"scratch.txt", "local-orphan.txt"}))
    peer_state = DestinationState(
        head="remote-head-not-in-local",
        modified_count=0,
        staged_count=0,
        untracked_count=1,
        dirty_paths=frozenset(),
        wt_deleted_paths=frozenset(),
        entries=(
            StatusRecord(raw_xy="??", path="scratch.txt", orig_path=None, kind=StatusKind.NEW),
        ),
    )
    peer_session = _FakePeerSession(
        peer_state,
        compare_result=HeadRelation.SOURCE_AHEAD,
        manifest_paths=frozenset({"scratch.txt", "remote-orphan.txt"}),
    )

    ctx = build_sync_context(
        _fetch_dconfig(local_repo),
        git_runner,
        state_path,
        peer_session=cast(PeerSession, peer_session),
    )

    assert ctx.source_state == SourceState(head=peer_state.head, entries=peer_state.entries)
    assert ctx.destination_state.head == local_head
    assert ctx.manifest_paths == frozenset({"scratch.txt", "local-orphan.txt", "remote-orphan.txt"})
    assert ctx.orphaned_paths == frozenset({"local-orphan.txt", "remote-orphan.txt"})
    assert ctx.doctor_report.head_relation is HeadRelation.SOURCE_AHEAD
    assert peer_session.compared == [("remote-head-not-in-local", local_head)]


def test_build_sync_context_uses_remote_destination_and_detects_conflicts(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    tmp_path: Path,
) -> None:
    local_repo = repo_factory("source", files={"tracked.txt": "base\n"})
    (local_repo / "tracked.txt").write_text("local change\n", encoding="utf-8")
    peer_state = DestinationState(
        head="peer-head",
        modified_count=1,
        staged_count=0,
        untracked_count=0,
        dirty_paths=frozenset({"tracked.txt"}),
        wt_deleted_paths=frozenset(),
        entries=(
            StatusRecord(raw_xy=" M", path="tracked.txt", orig_path=None, kind=StatusKind.UNSTAGED),
        ),
    )

    ctx = build_sync_context(
        _send_dconfig(local_repo),
        git_runner,
        tmp_path / "state",
        peer_session=cast(PeerSession, _FakePeerSession(peer_state)),
    )

    assert ctx.destination_state == peer_state
    assert [conflict.path for conflict in ctx.conflicts] == ["tracked.txt"]


def test_build_sync_context_requires_peer_session_for_remote_repo(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    tmp_path: Path,
) -> None:
    local_repo = repo_factory("dest", files={"tracked.txt": "base\n"})

    with pytest.raises(PeerConnectionError, match="peer session is required"):
        build_sync_context(_fetch_dconfig(local_repo), git_runner, tmp_path / "state")

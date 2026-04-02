from __future__ import annotations

from pathlib import Path

from wdsync.core.environment import Environment, detect_environment
from wdsync.core.exceptions import PeerConnectionError
from wdsync.core.interop import (
    git_command_for_target,
    local_rsync_root,
    peer_environment,
    rsync_command_for_environment,
)
from wdsync.core.models import (
    DirectionConfig,
    GitExecution,
    RepoEndpoint,
    SyncDirection,
    TransferExecution,
    WdsyncConfig,
)
from wdsync.core.runner import CommandRunner


def build_direction_from_wdsync_config(
    config: WdsyncConfig,
    direction: SyncDirection,
    repo_root: Path,
    runner: CommandRunner,
) -> DirectionConfig:
    """Build DirectionConfig from the new WdsyncConfig."""
    if config.peer is None:
        raise PeerConnectionError("wdsync: not connected to a peer. Run 'wdsync connect' first.")

    local_env = detect_environment()
    remote_env = peer_environment(local_env)
    local_git_cmd = git_command_for_target(local_env, local_env)
    peer_git_cmd = git_command_for_target(local_env, remote_env)
    rsync_cmd = rsync_command_for_environment(local_env)
    local_sync_root = local_rsync_root(local_env, repo_root, runner)
    peer_sync_root = (
        config.peer.root_native if local_env is Environment.WINDOWS else str(config.peer.root)
    )
    source = RepoEndpoint(root=config.peer.root, native_root=config.peer.root_native)
    destination = RepoEndpoint(root=repo_root, native_root=str(repo_root))

    if direction is SyncDirection.FETCH:
        return DirectionConfig(
            direction=direction,
            source=source,
            destination=destination,
            source_git=GitExecution(
                command_argv=peer_git_cmd,
                repo_native_root=config.peer.root_native,
            ),
            destination_git=GitExecution(
                command_argv=local_git_cmd,
                repo_native_root=str(repo_root),
            ),
            transfer=TransferExecution(
                command_argv=rsync_cmd,
                source_root=peer_sync_root,
                dest_root=local_sync_root,
            ),
            source_is_local=False,
            destination_is_local=True,
            peer_command_argv=config.peer.command_argv,
        )
    return DirectionConfig(
        direction=direction,
        source=destination,
        destination=source,
        source_git=GitExecution(
            command_argv=local_git_cmd,
            repo_native_root=str(repo_root),
        ),
        destination_git=GitExecution(
            command_argv=peer_git_cmd,
            repo_native_root=config.peer.root_native,
        ),
        transfer=TransferExecution(
            command_argv=rsync_cmd,
            source_root=local_sync_root,
            dest_root=peer_sync_root,
        ),
        source_is_local=True,
        destination_is_local=False,
        peer_command_argv=config.peer.command_argv,
    )

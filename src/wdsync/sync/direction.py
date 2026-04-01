from __future__ import annotations

from pathlib import Path

from wdsync.core.environment import Environment, detect_environment
from wdsync.core.exceptions import PeerConnectionError
from wdsync.core.models import DirectionConfig, ProjectConfig, SyncDirection, WdsyncConfig


def build_direction_config(
    config: ProjectConfig,
    direction: SyncDirection,
) -> DirectionConfig:
    if direction is SyncDirection.FETCH:
        return DirectionConfig(
            direction=direction,
            source_root=config.source_root,
            source_root_native=config.source_root_windows,
            source_git="git.exe",
            dest_root=config.dest_root,
            dest_root_native=str(config.dest_root),
            dest_git="git",
        )
    return DirectionConfig(
        direction=direction,
        source_root=config.dest_root,
        source_root_native=str(config.dest_root),
        source_git="git",
        dest_root=config.source_root,
        dest_root_native=config.source_root_windows,
        dest_git="git.exe",
    )


def _git_executables(env: Environment) -> tuple[str, str]:
    """Return (local_git, peer_git) based on environment."""
    if env is Environment.WINDOWS:
        return "git.exe", "git"
    return "git", "git.exe"


def build_direction_from_wdsync_config(
    config: WdsyncConfig,
    direction: SyncDirection,
    repo_root: Path,
) -> DirectionConfig:
    """Build DirectionConfig from the new WdsyncConfig."""
    if config.peer is None:
        raise PeerConnectionError("wdsync: not connected to a peer. Run 'wdsync connect' first.")

    env = detect_environment()
    local_git, peer_git = _git_executables(env)

    if direction is SyncDirection.FETCH:
        return DirectionConfig(
            direction=direction,
            source_root=config.peer.root,
            source_root_native=config.peer.root_native,
            source_git=peer_git,
            dest_root=repo_root,
            dest_root_native=str(repo_root),
            dest_git=local_git,
        )
    return DirectionConfig(
        direction=direction,
        source_root=repo_root,
        source_root_native=str(repo_root),
        source_git=local_git,
        dest_root=config.peer.root,
        dest_root_native=config.peer.root_native,
        dest_git=peer_git,
    )

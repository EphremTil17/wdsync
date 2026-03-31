from __future__ import annotations

from wdsync.models import DirectionConfig, ProjectConfig, SyncDirection


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

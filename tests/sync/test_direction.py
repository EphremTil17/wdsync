from __future__ import annotations

from pathlib import Path

from wdsync.core.models import ProjectConfig, SyncDirection
from wdsync.sync.direction import build_direction_config


def _config() -> ProjectConfig:
    return ProjectConfig(
        dest_root=Path("/home/user/repo"),
        config_path=Path("/home/user/repo/.wdsync"),
        source_root=Path("/mnt/c/Users/user/repo"),
        source_root_windows="C:\\Users\\user\\repo",
    )


def test_build_fetch_direction() -> None:
    dconfig = build_direction_config(_config(), SyncDirection.FETCH)

    assert dconfig.direction is SyncDirection.FETCH
    assert dconfig.source_root == Path("/mnt/c/Users/user/repo")
    assert dconfig.source_root_native == "C:\\Users\\user\\repo"
    assert dconfig.source_git == "git.exe"
    assert dconfig.dest_root == Path("/home/user/repo")
    assert dconfig.dest_root_native == "/home/user/repo"
    assert dconfig.dest_git == "git"


def test_build_send_direction() -> None:
    dconfig = build_direction_config(_config(), SyncDirection.SEND)

    assert dconfig.direction is SyncDirection.SEND
    assert dconfig.source_root == Path("/home/user/repo")
    assert dconfig.source_root_native == "/home/user/repo"
    assert dconfig.source_git == "git"
    assert dconfig.dest_root == Path("/mnt/c/Users/user/repo")
    assert dconfig.dest_root_native == "C:\\Users\\user\\repo"
    assert dconfig.dest_git == "git.exe"

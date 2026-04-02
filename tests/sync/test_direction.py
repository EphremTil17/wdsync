from __future__ import annotations

from pathlib import Path

import pytest

from wdsync.core.environment import Environment
from wdsync.core.exceptions import PeerConnectionError
from wdsync.core.models import Identity, PeerConfig, SyncDirection, WdsyncConfig
from wdsync.core.runner import CommandRunner
from wdsync.sync.direction import build_direction_from_wdsync_config


def _wdsync_config() -> WdsyncConfig:
    return WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=PeerConfig(
            command_argv=("wdsync.exe",),
            root=Path("/mnt/c/Users/user/repo"),
            root_native="C:\\Users\\user\\repo",
        ),
    )


def test_build_fetch_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wdsync.sync.direction.detect_environment", lambda: Environment.WSL)
    runner = CommandRunner()
    dconfig = build_direction_from_wdsync_config(
        _wdsync_config(), SyncDirection.FETCH, Path("/home/user/repo"), runner
    )

    assert dconfig.direction is SyncDirection.FETCH
    assert dconfig.source_root == Path("/mnt/c/Users/user/repo")
    assert dconfig.source_root_native == "C:\\Users\\user\\repo"
    assert dconfig.source_git.command_argv == ("git.exe",)
    assert dconfig.dest_root == Path("/home/user/repo")
    assert dconfig.dest_root_native == "/home/user/repo"
    assert dconfig.destination_git.command_argv == ("git",)
    assert dconfig.transfer.command_argv == ("rsync",)
    assert dconfig.transfer.source_root == "/mnt/c/Users/user/repo"
    assert dconfig.transfer.dest_root == "/home/user/repo"


def test_build_send_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wdsync.sync.direction.detect_environment", lambda: Environment.WSL)
    runner = CommandRunner()
    dconfig = build_direction_from_wdsync_config(
        _wdsync_config(), SyncDirection.SEND, Path("/home/user/repo"), runner
    )

    assert dconfig.direction is SyncDirection.SEND
    assert dconfig.source_root == Path("/home/user/repo")
    assert dconfig.source_root_native == "/home/user/repo"
    assert dconfig.source_git.command_argv == ("git",)
    assert dconfig.dest_root == Path("/mnt/c/Users/user/repo")
    assert dconfig.dest_root_native == "C:\\Users\\user\\repo"
    assert dconfig.destination_git.command_argv == ("git.exe",)
    assert dconfig.transfer.command_argv == ("rsync",)
    assert dconfig.transfer.source_root == "/home/user/repo"
    assert dconfig.transfer.dest_root == "/mnt/c/Users/user/repo"


def test_build_windows_fetch_direction(
    monkeypatch: pytest.MonkeyPatch,
    git_runner: CommandRunner,
) -> None:
    monkeypatch.setattr("wdsync.sync.direction.detect_environment", lambda: Environment.WINDOWS)
    config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=PeerConfig(
            command_argv=("wsl.exe", "--exec", "wdsync"),
            root=Path(r"\\wsl.localhost\Ubuntu\home\user\repo"),
            root_native="/home/user/repo",
        ),
    )

    dconfig = build_direction_from_wdsync_config(
        config,
        SyncDirection.FETCH,
        Path(r"C:\Users\user\repo"),
        git_runner,
    )

    assert dconfig.source_git.command_argv == ("wsl.exe", "--exec", "git")
    assert dconfig.destination_git.command_argv == ("git.exe",)
    assert dconfig.transfer.command_argv == ("wsl.exe", "--exec", "rsync")
    assert dconfig.transfer.source_root == "/home/user/repo"
    assert dconfig.transfer.dest_root == "/mnt/c/Users/user/repo"


def test_raises_when_peer_is_none() -> None:
    config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=None,
    )
    with pytest.raises(PeerConnectionError, match="not connected"):
        build_direction_from_wdsync_config(
            config,
            SyncDirection.FETCH,
            Path("/home/user/repo"),
            CommandRunner(),
        )

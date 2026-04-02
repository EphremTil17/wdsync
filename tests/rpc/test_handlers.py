from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from wdsync.core.environment import Environment
from wdsync.core.models import DestinationState, Identity, PeerConfig, WdsyncConfig
from wdsync.core.protocol import HANDSHAKE_CAPABILITIES, PROTOCOL_VERSION, RpcMethod
from wdsync.core.runner import CommandRunner
from wdsync.rpc import handlers
from wdsync.rpc.handlers import handle_rpc_request


def _make_request(
    method: str, *, version: int = PROTOCOL_VERSION, args: dict[str, object] | None = None
) -> dict[str, object]:
    return {"version": version, "method": method, "args": args or {}}


def test_handshake_returns_version_and_capabilities() -> None:
    runner = cast(CommandRunner, object())
    request = _make_request(RpcMethod.HANDSHAKE)

    response = handle_rpc_request(request, runner)

    assert response["ok"] is True
    assert response["data"]["protocol_version"] == PROTOCOL_VERSION
    assert response["data"]["capabilities"] == list(HANDSHAKE_CAPABILITIES)


def test_locate_repo_finds_match(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = cast(CommandRunner, object())
    identity = Identity(remote_url="https://github.com/user/repo", root_commits=("abc",))

    def _fake_locate(*_args: object, **_kwargs: object) -> tuple[Path, str]:
        return (Path("/home/user/repo"), "remote_url")

    def _fake_resolve(*_args: object, **_kwargs: object) -> Identity:
        return identity

    monkeypatch.setattr(handlers, "locate_matching_repo", _fake_locate)
    monkeypatch.setattr(handlers, "resolve_identity", _fake_resolve)

    request = _make_request(
        RpcMethod.LOCATE_REPO,
        args={
            "identity": {"remote_url": "https://github.com/user/repo", "root_commits": ["abc"]},
        },
    )
    response = handle_rpc_request(request, runner)

    assert response["ok"] is True
    assert response["data"]["matched_by"] == "remote_url"
    assert response["data"]["repo_root"] == "/home/user/repo"


def test_locate_repo_returns_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = cast(CommandRunner, object())
    identity = Identity(remote_url="https://github.com/user/repo", root_commits=("abc",))

    def _fake_locate(*_args: object, **_kwargs: object) -> tuple[Path, str]:
        return (Path("/repo"), "root_commits")

    def _fake_resolve(*_args: object, **_kwargs: object) -> Identity:
        return identity

    monkeypatch.setattr(handlers, "locate_matching_repo", _fake_locate)
    monkeypatch.setattr(handlers, "resolve_identity", _fake_resolve)

    request = _make_request(
        RpcMethod.LOCATE_REPO,
        args={"identity": {"remote_url": None, "root_commits": ["abc"]}},
    )
    response = handle_rpc_request(request, runner)

    assert response["ok"] is True
    identity_data = response["data"]["identity"]
    assert isinstance(identity_data, dict)
    assert identity_data["remote_url"] == "https://github.com/user/repo"
    assert identity_data["root_commits"] == ["abc"]


def test_locate_repo_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = cast(CommandRunner, object())

    def _no_match(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(handlers, "locate_matching_repo", _no_match)

    request = _make_request(
        RpcMethod.LOCATE_REPO,
        args={"identity": {"remote_url": None, "root_commits": ["abc"]}},
    )
    response = handle_rpc_request(request, runner)

    assert response["ok"] is False
    assert "no matching repository found" in (response["error"] or "")


def test_locate_repo_passes_cached_root(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = cast(CommandRunner, object())
    captured_kwargs: dict[str, object] = {}

    def fake_locate(
        peer_identity: Identity, runner: CommandRunner, *, cached_root: Path | None = None
    ) -> None:
        captured_kwargs["cached_root"] = cached_root
        return None

    monkeypatch.setattr(handlers, "locate_matching_repo", fake_locate)

    request = _make_request(
        RpcMethod.LOCATE_REPO,
        args={
            "identity": {"remote_url": None, "root_commits": ["abc"]},
            "cached_root": "/previous/path",
        },
    )
    handle_rpc_request(request, runner)

    assert captured_kwargs["cached_root"] == Path("/previous/path")


def test_configure_peer_saves_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = cast(CommandRunner, object())
    config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=None,
    )
    saved: dict[str, object] = {}

    def load_with_paths_stub(
        runner: CommandRunner,
        cwd: Path | None = None,
    ) -> tuple[WdsyncConfig, Path, Path]:
        del runner, cwd
        return config, Path("/repo"), Path("/repo/.git/wdsync")

    def save_config_stub(updated: WdsyncConfig, sdir: Path) -> None:
        saved["config"] = updated
        saved["sdir"] = sdir

    monkeypatch.setattr(
        handlers,
        "load_wdsync_config_with_paths",
        load_with_paths_stub,
    )

    def ensure_rsync_stub(env: object, runner: object) -> None:
        del env, runner

    monkeypatch.setattr(handlers, "ensure_local_rsync_available", ensure_rsync_stub)
    monkeypatch.setattr(handlers, "save_wdsync_config", save_config_stub)

    request = _make_request(
        RpcMethod.CONFIGURE_PEER,
        args={
            "repo_root_native": "/repo",
            "peer": {
                "command_argv": ["wsl.exe", "--exec", "wdsync"],
                "root": r"\\wsl.localhost\Ubuntu\home\user\repo",
                "root_native": "/home/user/repo",
            },
        },
    )
    response = handle_rpc_request(request, runner)

    assert response["ok"] is True
    assert saved["sdir"] == Path("/repo/.git/wdsync")
    updated = cast(WdsyncConfig, saved["config"])
    assert updated.peer == PeerConfig(
        command_argv=("wsl.exe", "--exec", "wdsync"),
        root=Path(r"\\wsl.localhost\Ubuntu\home\user\repo"),
        root_native="/home/user/repo",
    )


def test_configure_peer_persists_validated_runtime_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = cast(CommandRunner, object())
    config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=None,
    )
    saved: dict[str, object] = {}

    def load_with_paths_stub(
        runner: CommandRunner,
        cwd: Path | None = None,
    ) -> tuple[WdsyncConfig, Path, Path]:
        del runner, cwd
        return config, Path("/repo"), Path("/repo/.git/wdsync")

    def save_config_stub(updated: WdsyncConfig, sdir: Path) -> None:
        saved["config"] = updated
        saved["sdir"] = sdir

    def ensure_rsync_stub(env: object, runner: object) -> None:
        del env, runner

    monkeypatch.setattr(handlers, "load_wdsync_config_with_paths", load_with_paths_stub)
    monkeypatch.setattr(handlers, "ensure_local_rsync_available", ensure_rsync_stub)
    monkeypatch.setattr(handlers, "save_wdsync_config", save_config_stub)
    monkeypatch.setattr(handlers, "detect_environment", lambda: Environment.WINDOWS)

    response = handle_rpc_request(
        _make_request(
            RpcMethod.CONFIGURE_PEER,
            args={
                "repo_root_native": "/repo",
                "peer": {
                    "command_argv": ["/home/user/.local/bin/wdsync"],
                    "root": r"\\wsl.localhost\Ubuntu\home\user\repo",
                    "root_native": "/home/user/repo",
                },
            },
        ),
        runner,
    )

    assert response["ok"] is True
    updated = cast(WdsyncConfig, saved["config"])
    assert updated.runtime.wsl_peer_command_argv == ("/home/user/.local/bin/wdsync",)


def test_configure_peer_unwraps_windows_wsl_exec_command_for_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = cast(CommandRunner, object())
    config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=None,
    )
    saved: dict[str, object] = {}

    def load_with_paths_stub(
        runner: CommandRunner,
        cwd: Path | None = None,
    ) -> tuple[WdsyncConfig, Path, Path]:
        del runner, cwd
        return config, Path("/repo"), Path("/repo/.git/wdsync")

    def save_config_stub(updated: WdsyncConfig, sdir: Path) -> None:
        saved["config"] = updated
        saved["sdir"] = sdir

    def ensure_rsync_stub(env: object, runner: object) -> None:
        del env, runner

    monkeypatch.setattr(handlers, "load_wdsync_config_with_paths", load_with_paths_stub)
    monkeypatch.setattr(handlers, "ensure_local_rsync_available", ensure_rsync_stub)
    monkeypatch.setattr(handlers, "save_wdsync_config", save_config_stub)
    monkeypatch.setattr(handlers, "detect_environment", lambda: Environment.WINDOWS)

    response = handle_rpc_request(
        _make_request(
            RpcMethod.CONFIGURE_PEER,
            args={
                "repo_root_native": "/repo",
                "peer": {
                    "command_argv": [
                        "wsl.exe",
                        "-d",
                        "Ubuntu",
                        "--exec",
                        "/home/user/.local/bin/wdsync",
                    ],
                    "root": r"\\wsl.localhost\Ubuntu\home\user\repo",
                    "root_native": "/home/user/repo",
                },
            },
        ),
        runner,
    )

    assert response["ok"] is True
    updated = cast(WdsyncConfig, saved["config"])
    assert updated.runtime.wsl_peer_command_argv == ("/home/user/.local/bin/wdsync",)
    assert updated.runtime.wsl_distro == "Ubuntu"


def test_status_returns_destination_state(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = cast(CommandRunner, object())
    state = DestinationState(
        head="abc",
        modified_count=1,
        staged_count=0,
        untracked_count=0,
        dirty_paths=frozenset({"a.txt"}),
        wt_deleted_paths=frozenset(),
        entries=(),
    )

    def read_status_stub(repo_root: Path, runner: CommandRunner) -> DestinationState:
        del repo_root, runner
        return state

    monkeypatch.setattr(handlers, "_read_local_repo_status", read_status_stub)

    response = handle_rpc_request(
        _make_request(RpcMethod.STATUS, args={"repo_root_native": "/repo"}),
        runner,
    )

    assert response["ok"] is True
    assert response["data"]["head"] == "abc"
    assert response["data"]["dirty_paths"] == ["a.txt"]


def test_unknown_method_returns_error() -> None:
    runner = cast(CommandRunner, object())
    request = _make_request("nonexistent_method")

    response = handle_rpc_request(request, runner)

    assert response["ok"] is False
    assert "unknown method" in (response["error"] or "")


def test_version_mismatch_returns_error() -> None:
    runner = cast(CommandRunner, object())
    request = _make_request(RpcMethod.HANDSHAKE, version=999)

    response = handle_rpc_request(request, runner)

    assert response["ok"] is False
    assert "unsupported protocol version" in (response["error"] or "")

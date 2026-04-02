from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any, cast

import pytest

from wdsync.core.environment import Environment
from wdsync.core.exceptions import IdentityMismatchError, PeerConnectionError
from wdsync.core.interop import ResolvedPeerCommand, peer_command_for_environment
from wdsync.core.models import Identity, PeerConfig, RuntimePreferences, WdsyncConfig
from wdsync.core.protocol import HANDSHAKE_CAPABILITIES, PROTOCOL_VERSION, RpcRequest, RpcResponse
from wdsync.core.runner import CommandRunner
from wdsync.rpc import connect as connect_mod
from wdsync.rpc.connect import connect_to_peer


def _identity() -> Identity:
    return Identity(remote_url="https://github.com/user/repo", root_commits=("abc",))


def _config(*, peer: PeerConfig | None = None) -> WdsyncConfig:
    return WdsyncConfig(version=1, identity=_identity(), peer=peer)


def _request_args_dict(request: RpcRequest) -> dict[str, object]:
    return request["args"]


def _peer_payload(request: RpcRequest) -> dict[str, object]:
    args = _request_args_dict(request)
    return cast(dict[str, object], args["peer"])


class FakeRpcClient:
    """Mock RPC client that returns canned responses."""

    def __init__(self, responses: list[RpcResponse]) -> None:
        self._responses = list(responses)
        self._call_index = 0
        self.requests: list[RpcRequest] = []

    def __enter__(self) -> FakeRpcClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    def send(self, request: RpcRequest) -> RpcResponse:
        self.requests.append(request)
        if self._call_index >= len(self._responses):
            raise PeerConnectionError("wdsync: unexpected extra send call")
        resp = self._responses[self._call_index]
        self._call_index += 1
        if not resp["ok"]:
            raise PeerConnectionError(f"wdsync: peer returned error: {resp['error']}")
        return resp


def _handshake_ok() -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {
            "protocol_version": PROTOCOL_VERSION,
            "capabilities": list(HANDSHAKE_CAPABILITIES),
        },
        "error": None,
    }


def _locate_ok(
    *,
    remote_url: str | None = "https://github.com/user/repo",
    root_commits: list[str] | None = None,
    repo_root_native: str = "C:\\Users\\user\\repo",
    matched_by: str = "remote_url",
) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {
            "identity": {
                "remote_url": remote_url,
                "root_commits": root_commits or ["abc"],
            },
            "repo_root": "/mnt/c/Users/user/repo",
            "repo_root_native": repo_root_native,
            "matched_by": matched_by,
        },
        "error": None,
    }


def _configure_ok() -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {"configured": True},
        "error": None,
    }


def _fake_rpc_client_factory(client: object) -> Any:
    def factory(*_args: object, **_kwargs: object) -> object:
        return client

    return factory


def _fake_local_path_for_peer_string(
    env: Environment,
    repo_root: Path,
    runner: CommandRunner,
) -> str:
    del runner
    if env is Environment.WSL:
        return r"\\wsl.localhost\Ubuntu\home\user\repo"
    return "/mnt/c/Users/user/repo"


def _fake_peer_native_to_local_path(
    env: Environment,
    native: str,
    runner: CommandRunner,
) -> Path:
    del runner
    if env is Environment.WSL:
        return Path("/mnt/c/Users/user/repo")
    return Path(r"\\wsl.localhost\Ubuntu\home\user\repo")


def _resolved_windows_peer(
    local_env: Environment,
    runtime: RuntimePreferences,
    runner: CommandRunner,
    *,
    local_wsl_distro: str | None = None,
) -> ResolvedPeerCommand:
    del local_env, runtime, runner, local_wsl_distro
    return ResolvedPeerCommand(
        spawn_argv=("C:\\Python\\Scripts\\wdsync.exe",),
        stored_argv=("C:\\Python\\Scripts\\wdsync.exe",),
    )


def _resolved_wsl_peer(
    local_env: Environment,
    runtime: RuntimePreferences,
    runner: CommandRunner,
    *,
    local_wsl_distro: str | None = None,
) -> ResolvedPeerCommand:
    del local_env, runtime, runner, local_wsl_distro
    return ResolvedPeerCommand(
        spawn_argv=("wsl.exe", "--exec", "/home/user/.local/bin/wdsync"),
        stored_argv=("/home/user/.local/bin/wdsync",),
    )


def _resolved_python_peer(
    local_env: Environment,
    runtime: RuntimePreferences,
    runner: CommandRunner,
    *,
    local_wsl_distro: str | None = None,
) -> ResolvedPeerCommand:
    del local_env, runtime, runner, local_wsl_distro
    return ResolvedPeerCommand(
        spawn_argv=("python.exe",),
        stored_argv=("python.exe",),
    )


def _resolved_reverse_wsl_command(
    local_env: Environment,
    runtime: RuntimePreferences,
    runner: CommandRunner,
    *,
    local_wsl_distro: str | None = None,
) -> tuple[str, ...]:
    del local_env, runtime, runner, local_wsl_distro
    return ("wsl.exe", "--exec", "/home/user/.local/bin/wdsync")


def _resolved_reverse_windows_command(
    local_env: Environment,
    runtime: RuntimePreferences,
    runner: CommandRunner,
    *,
    local_wsl_distro: str | None = None,
) -> tuple[str, ...]:
    del local_env, runtime, runner, local_wsl_distro
    return ("/mnt/c/Users/user/AppData/Roaming/Python/Scripts/wdsync.exe",)


def test_connect_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git_runner: CommandRunner,
) -> None:
    sdir = tmp_path / "state"
    sdir.mkdir()
    fake_client = FakeRpcClient([_handshake_ok(), _locate_ok(), _configure_ok()])

    monkeypatch.setattr(connect_mod, "detect_environment", lambda: Environment.WSL)
    monkeypatch.setattr(connect_mod, "RpcClient", _fake_rpc_client_factory(fake_client))
    monkeypatch.setattr(connect_mod, "peer_native_to_local_path", _fake_peer_native_to_local_path)
    monkeypatch.setattr(connect_mod, "local_path_for_peer_string", _fake_local_path_for_peer_string)
    monkeypatch.setattr(connect_mod, "resolve_peer_command_for_environment", _resolved_windows_peer)
    monkeypatch.setattr(
        connect_mod,
        "resolve_reverse_peer_command_for_environment",
        _resolved_reverse_wsl_command,
    )

    result = connect_to_peer(_config(), tmp_path, git_runner, sdir)

    assert result.matched_by == "remote_url"
    assert result.peer.root_native == "C:\\Users\\user\\repo"
    assert result.peer.root == Path("/mnt/c/Users/user/repo")
    assert fake_client.requests[2]["method"] == "configure_peer"
    peer_payload = _peer_payload(fake_client.requests[2])
    assert peer_payload["command_argv"] == ["wsl.exe", "--exec", "/home/user/.local/bin/wdsync"]
    # Config should be saved
    assert (sdir / "config.json").exists()


def test_connect_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git_runner: CommandRunner,
) -> None:
    sdir = tmp_path / "state"
    sdir.mkdir()
    # Peer has a different identity
    locate = _locate_ok(remote_url="https://github.com/other/repo", root_commits=["xyz"])
    fake_client = FakeRpcClient([_handshake_ok(), locate])

    monkeypatch.setattr(connect_mod, "detect_environment", lambda: Environment.WSL)
    monkeypatch.setattr(connect_mod, "RpcClient", _fake_rpc_client_factory(fake_client))
    monkeypatch.setattr(connect_mod, "peer_native_to_local_path", _fake_peer_native_to_local_path)
    monkeypatch.setattr(connect_mod, "resolve_peer_command_for_environment", _resolved_windows_peer)

    with pytest.raises(IdentityMismatchError, match="does not match"):
        connect_to_peer(_config(), tmp_path, git_runner, sdir)


def test_connect_peer_not_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git_runner: CommandRunner,
) -> None:
    sdir = tmp_path / "state"
    sdir.mkdir()
    locate_error: RpcResponse = {
        "version": PROTOCOL_VERSION,
        "ok": False,
        "data": {},
        "error": "no matching repository found",
    }
    fake_client = FakeRpcClient([_handshake_ok(), locate_error])

    monkeypatch.setattr(connect_mod, "detect_environment", lambda: Environment.WSL)
    monkeypatch.setattr(connect_mod, "RpcClient", _fake_rpc_client_factory(fake_client))
    monkeypatch.setattr(connect_mod, "resolve_peer_command_for_environment", _resolved_windows_peer)

    with pytest.raises(PeerConnectionError, match="no matching repository"):
        connect_to_peer(_config(), tmp_path, git_runner, sdir)


def test_connect_spawn_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git_runner: CommandRunner,
) -> None:
    sdir = tmp_path / "state"
    sdir.mkdir()

    class FailClient:
        def __enter__(self) -> FailClient:
            raise PeerConnectionError("wdsync: peer command not found: python.exe")

        def __exit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr(connect_mod, "detect_environment", lambda: Environment.WSL)
    monkeypatch.setattr(connect_mod, "RpcClient", _fake_rpc_client_factory(FailClient()))
    monkeypatch.setattr(connect_mod, "resolve_peer_command_for_environment", _resolved_python_peer)

    with pytest.raises(PeerConnectionError, match="not found"):
        connect_to_peer(_config(), tmp_path, git_runner, sdir)


def test_connect_non_wsl_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connect_mod, "detect_environment", lambda: Environment.LINUX)

    with pytest.raises(PeerConnectionError, match="only supported between WSL and Windows"):
        connect_to_peer(_config(), Path("/tmp"), CommandRunner(), Path("/tmp"))


def test_connect_from_windows_uses_wsl_peer_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git_runner: CommandRunner,
) -> None:
    sdir = tmp_path / "state"
    sdir.mkdir()
    fake_client = FakeRpcClient(
        [_handshake_ok(), _locate_ok(repo_root_native="/home/user/repo"), _configure_ok()]
    )

    monkeypatch.setattr(connect_mod, "detect_environment", lambda: Environment.WINDOWS)
    monkeypatch.setattr(connect_mod, "current_wsl_distro", lambda: None)
    monkeypatch.setattr(connect_mod, "RpcClient", _fake_rpc_client_factory(fake_client))
    monkeypatch.setattr(connect_mod, "peer_native_to_local_path", _fake_peer_native_to_local_path)
    monkeypatch.setattr(connect_mod, "local_path_for_peer_string", _fake_local_path_for_peer_string)
    monkeypatch.setattr(connect_mod, "resolve_peer_command_for_environment", _resolved_wsl_peer)
    monkeypatch.setattr(
        connect_mod,
        "resolve_reverse_peer_command_for_environment",
        _resolved_reverse_windows_command,
    )

    result = connect_to_peer(_config(), Path(r"C:\Users\user\repo"), git_runner, sdir)

    assert result.peer.command_argv == ("wsl.exe", "--exec", "/home/user/.local/bin/wdsync")
    assert result.peer.root == Path(r"\\wsl.localhost\Ubuntu\home\user\repo")
    assert result.peer.root_native == "/home/user/repo"
    peer_payload = _peer_payload(fake_client.requests[2])
    assert peer_payload["command_argv"] == [
        "/mnt/c/Users/user/AppData/Roaming/Python/Scripts/wdsync.exe"
    ]


def test_connect_persists_resolved_runtime_preferences(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git_runner: CommandRunner,
) -> None:
    sdir = tmp_path / "state"
    sdir.mkdir()
    fake_client = FakeRpcClient(
        [_handshake_ok(), _locate_ok(repo_root_native="/home/user/repo"), _configure_ok()]
    )

    monkeypatch.setattr(connect_mod, "detect_environment", lambda: Environment.WINDOWS)
    monkeypatch.setattr(connect_mod, "current_wsl_distro", lambda: None)
    monkeypatch.setattr(connect_mod, "RpcClient", _fake_rpc_client_factory(fake_client))
    monkeypatch.setattr(connect_mod, "peer_native_to_local_path", _fake_peer_native_to_local_path)
    monkeypatch.setattr(connect_mod, "local_path_for_peer_string", _fake_local_path_for_peer_string)
    monkeypatch.setattr(connect_mod, "resolve_peer_command_for_environment", _resolved_wsl_peer)
    monkeypatch.setattr(
        connect_mod,
        "resolve_reverse_peer_command_for_environment",
        _resolved_reverse_windows_command,
    )

    connect_to_peer(_config(), Path(r"C:\Users\user\repo"), git_runner, sdir)

    saved = (sdir / "config.json").read_text(encoding="utf-8")
    assert '"/home/user/.local/bin/wdsync"' in saved


def test_peer_command_for_wsl() -> None:
    argv = peer_command_for_environment(Environment.WSL, RuntimePreferences())

    assert argv == ("wdsync.exe",)


def test_peer_command_for_windows() -> None:
    argv = peer_command_for_environment(Environment.WINDOWS, RuntimePreferences())

    assert argv == ("wsl.exe", "--exec", "wdsync")


def test_peer_command_for_non_wsl_raises() -> None:
    with pytest.raises(PeerConnectionError, match="only supported between WSL and Windows"):
        peer_command_for_environment(Environment.LINUX, RuntimePreferences())


def test_peer_command_respects_runtime_overrides() -> None:
    runtime = RuntimePreferences(
        windows_peer_command_argv=("python.exe", "-m", "wdsync"),
        wsl_peer_command_argv=("python", "-m", "wdsync"),
        wsl_distro="Ubuntu-24.04",
    )

    assert peer_command_for_environment(Environment.WSL, runtime) == ("python.exe", "-m", "wdsync")
    assert peer_command_for_environment(Environment.WINDOWS, runtime) == (
        "wsl.exe",
        "-d",
        "Ubuntu-24.04",
        "--exec",
        "python",
        "-m",
        "wdsync",
    )

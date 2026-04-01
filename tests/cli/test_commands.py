from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
import typer
from typer.testing import CliRunner

from wdsync.cli import commands as cli
from wdsync.core.exceptions import (
    MissingConfigError,
    NotGitRepositoryError,
    ShellDetectionError,
)
from wdsync.core.models import (
    DestinationState,
    Identity,
    InitializeResult,
    ShellInstallResult,
    ShellName,
    SourceState,
    StatusKind,
    StatusRecord,
    WdsyncConfig,
)
from wdsync.core.runner import CommandRunner

# ---------------------------------------------------------------------------
# Kept tests — shell install, parse_shell_name, main
# ---------------------------------------------------------------------------


def test_shell_install_uses_requested_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    def install_shell_assets_stub(
        app: typer.Typer,
        *,
        shell_name: ShellName | None = None,
    ) -> ShellInstallResult:
        del app
        return ShellInstallResult(
            shell=shell_name or "bash",
            installed_paths=(Path("/tmp/a"), Path("/tmp/b")),
            notes=("ok",),
        )

    monkeypatch.setattr(cli, "install_shell_assets", install_shell_assets_stub)

    result = CliRunner().invoke(cli.app, ["shell", "install", "--shell", "fish"])

    assert result.exit_code == 0
    assert "Installed fish shell assets:" in result.stdout


def test_parse_shell_name_rejects_unknown_value() -> None:
    parse_shell_name = cast(
        Callable[[str | None], ShellName | None],
        cli._parse_shell_name,  # pyright: ignore[reportPrivateUsage]
    )

    with pytest.raises(typer.BadParameter):
        parse_shell_name("powershell")


def test_parse_shell_name_accepts_none() -> None:
    parse_shell_name = cast(
        Callable[[str | None], ShellName | None],
        cli._parse_shell_name,  # pyright: ignore[reportPrivateUsage]
    )

    assert parse_shell_name(None) is None


def test_shell_install_surfaces_user_facing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def install_shell_assets_error(
        app: typer.Typer,
        *,
        shell_name: ShellName | None = None,
    ) -> ShellInstallResult:
        del app, shell_name
        raise ShellDetectionError("shell-error")

    monkeypatch.setattr(cli, "install_shell_assets", install_shell_assets_error)

    result = CliRunner().invoke(cli.app, ["shell", "install"])

    assert result.exit_code == 1
    assert "shell-error" in result.stderr


def test_main_invokes_typer_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_app() -> None:
        calls.append("called")

    monkeypatch.setattr(cli, "app", fake_app)

    cli.main()

    assert calls == ["called"]


# ---------------------------------------------------------------------------
# New tests — init
# ---------------------------------------------------------------------------


def test_init_creates_config(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    fake_result = InitializeResult(
        repo_root=Path("/tmp/repo"),
        config_path=Path("/tmp/repo/.git/wdsync/config.json"),
        marker_path=Path("/tmp/repo/.wdsync"),
        identity=Identity(remote_url="https://github.com/example/repo.git", root_commits=("abc",)),
    )

    def build_runner_stub() -> CommandRunner:
        return fake_runner

    def initialize_repo_stub(runner: CommandRunner) -> InitializeResult:
        del runner
        return fake_result

    monkeypatch.setattr(cli, "build_runner", build_runner_stub)
    monkeypatch.setattr(cli, "initialize_repo", initialize_repo_stub)

    result = CliRunner().invoke(cli.app, ["init"])

    assert result.exit_code == 0
    assert "Initialized" in result.stdout


def test_init_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def initialize_repo_error(runner: CommandRunner) -> InitializeResult:
        del runner
        raise NotGitRepositoryError("not a git repo")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "initialize_repo", initialize_repo_error)

    result = CliRunner().invoke(cli.app, ["init"])

    assert result.exit_code == 1
    assert "not a git repo" in result.stderr


# ---------------------------------------------------------------------------
# New tests — fetch / send / status surface errors
# ---------------------------------------------------------------------------


def test_fetch_requires_peer_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    config_no_peer = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=None,
    )

    def load_wdsync_config_stub(runner: CommandRunner, *, cwd: Path | None = None) -> WdsyncConfig:
        del runner, cwd
        return config_no_peer

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_wdsync_config", load_wdsync_config_stub)

    def find_repo_root_stub(runner: CommandRunner, **_: object) -> Path:
        del runner
        return Path("/tmp/repo")

    def state_dir_stub(root: Path, runner: CommandRunner) -> Path:
        del root, runner
        return Path("/tmp/repo/.git/wdsync")

    monkeypatch.setattr(cli, "find_repo_root", find_repo_root_stub)
    monkeypatch.setattr(cli, "state_dir", state_dir_stub)

    result = CliRunner().invoke(cli.app, ["fetch"])

    assert result.exit_code == 1
    assert "not connected" in result.stderr


def test_fetch_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def load_wdsync_config_error(runner: CommandRunner, *, cwd: Path | None = None) -> None:
        del runner, cwd
        raise MissingConfigError("fetch-config-missing")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_wdsync_config", load_wdsync_config_error)

    result = CliRunner().invoke(cli.app, ["fetch"])

    assert result.exit_code == 1
    assert "fetch-config-missing" in result.stderr


def test_send_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def load_wdsync_config_error(runner: CommandRunner, *, cwd: Path | None = None) -> None:
        del runner, cwd
        raise MissingConfigError("send-config-missing")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_wdsync_config", load_wdsync_config_error)

    result = CliRunner().invoke(cli.app, ["send"])

    assert result.exit_code == 1
    assert "send-config-missing" in result.stderr


def test_status_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def load_wdsync_config_error(runner: CommandRunner, *, cwd: Path | None = None) -> None:
        del runner, cwd
        raise MissingConfigError("status-config-missing")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_wdsync_config", load_wdsync_config_error)

    result = CliRunner().invoke(cli.app, ["status"])

    assert result.exit_code == 1
    assert "status-config-missing" in result.stderr


def test_status_json_uses_status_formatter_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    fake_dconfig = cast(cli.DirectionConfig, object())
    fake_sdir = Path("/tmp/repo/.git/wdsync")
    source_state = SourceState(
        head="abc",
        entries=(
            StatusRecord(raw_xy=" M", path="src/app.py", orig_path=None, kind=StatusKind.UNSTAGED),
        ),
    )
    destination_state = DestinationState(
        head="abc",
        modified_count=0,
        staged_count=0,
        untracked_count=0,
        entries=(),
    )

    class _FakeReport:
        head_relation = type("Value", (), {"value": "same"})()
        risk_level = type("Value", (), {"value": "low"})()

    def load_and_build_stub(
        runner: CommandRunner, direction: cli.SyncDirection
    ) -> tuple[cli.DirectionConfig, Path, WdsyncConfig]:
        del runner, direction
        return (
            fake_dconfig,
            fake_sdir,
            WdsyncConfig(
                version=1,
                identity=Identity(remote_url=None, root_commits=("abc",)),
                peer=None,
            ),
        )

    def read_source_state_stub(dconfig: cli.DirectionConfig, runner: CommandRunner) -> SourceState:
        del dconfig, runner
        return source_state

    def read_destination_state_stub(
        dconfig: cli.DirectionConfig, runner: CommandRunner
    ) -> DestinationState:
        del dconfig, runner
        return destination_state

    def detect_conflicts_stub(
        src_state: SourceState, dest_state: DestinationState
    ) -> tuple[object, ...]:
        del src_state, dest_state
        return ()

    def build_doctor_report_stub(*_: object) -> _FakeReport:
        return _FakeReport()

    def read_manifest_stub(sdir: Path) -> frozenset[str]:
        del sdir
        return frozenset()

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "_load_and_build", load_and_build_stub)
    monkeypatch.setattr(cli, "read_source_state", read_source_state_stub)
    monkeypatch.setattr(cli, "read_destination_state", read_destination_state_stub)
    monkeypatch.setattr(cli, "detect_conflicts", detect_conflicts_stub)
    monkeypatch.setattr(cli, "build_doctor_report", build_doctor_report_stub)
    monkeypatch.setattr(cli, "read_manifest", read_manifest_stub)

    result = CliRunner().invoke(cli.app, ["status", "--json"])

    assert result.exit_code == 0
    assert '"source_entries"' in result.stdout
    assert '"destination_entries"' in result.stdout
    assert '"conflicts"' in result.stdout


# ---------------------------------------------------------------------------
# New tests — connect / disconnect
# ---------------------------------------------------------------------------


def test_connect_stub_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    fake_config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=()),
        peer=None,
    )

    def build_runner_stub() -> CommandRunner:
        return fake_runner

    def load_wdsync_config_stub(runner: CommandRunner, *, cwd: Path | None = None) -> WdsyncConfig:
        del runner, cwd
        return fake_config

    monkeypatch.setattr(cli, "build_runner", build_runner_stub)
    monkeypatch.setattr(cli, "load_wdsync_config", load_wdsync_config_stub)

    result = CliRunner().invoke(cli.app, ["connect"])

    assert result.exit_code == 1


def test_disconnect_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def load_wdsync_config_error(runner: CommandRunner, **kw: object) -> None:
        del runner, kw
        raise MissingConfigError("disconnect-config-missing")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_wdsync_config", load_wdsync_config_error)

    result = CliRunner().invoke(cli.app, ["disconnect"])

    assert result.exit_code == 1
    assert "disconnect-config-missing" in result.stderr

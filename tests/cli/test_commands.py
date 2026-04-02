from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
import typer
from typer.testing import CliRunner

from wdsync.cli import commands as cli
from wdsync.core.environment import Environment
from wdsync.core.exceptions import (
    MissingConfigError,
    NotGitRepositoryError,
    ShellDetectionError,
)
from wdsync.core.models import (
    ConnectResult,
    DeinitializeResult,
    DeleteOutcome,
    DestinationState,
    DirectionConfig,
    DoctorReport,
    GitExecution,
    HeadRelation,
    Identity,
    InitializeResult,
    PeerConfig,
    RepoEndpoint,
    RestoreResult,
    RiskLevel,
    RuntimePreferences,
    ShellInstallResult,
    ShellName,
    SourceState,
    StatusKind,
    StatusRecord,
    SyncContext,
    SyncDirection,
    SyncPlan,
    SyncResult,
    TransferExecution,
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


def test_parse_command_argv_handles_windows_and_wsl_quoting() -> None:
    parse_command_argv = cast(
        Callable[..., tuple[str, ...] | None],
        cli._parse_command_argv,  # pyright: ignore[reportPrivateUsage]
    )

    assert parse_command_argv(
        r'"C:\Program Files\Python\python.exe" -m wdsync',
        option_name="--windows-peer-command",
        posix=False,
    ) == (r"C:\Program Files\Python\python.exe", "-m", "wdsync")
    assert parse_command_argv(
        '"python3" -m wdsync',
        option_name="--wsl-peer-command",
        posix=True,
    ) == ("python3", "-m", "wdsync")


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

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)

    def initialize_repo_stub(runner: CommandRunner) -> InitializeResult:
        del runner
        return fake_result

    monkeypatch.setattr(cli, "initialize_repo", initialize_repo_stub)

    result = CliRunner().invoke(cli.app, ["init"])

    assert result.exit_code == 0


def test_init_reports_already_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    fake_result = InitializeResult(
        repo_root=Path("/tmp/repo"),
        config_path=Path("/tmp/repo/.git/wdsync/config.json"),
        marker_path=Path("/tmp/repo/.wdsync"),
        identity=Identity(remote_url="https://github.com/example/repo.git", root_commits=("abc",)),
        already_initialized=True,
    )

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)

    def initialize_repo_stub(runner: CommandRunner) -> InitializeResult:
        del runner
        return fake_result

    monkeypatch.setattr(cli, "initialize_repo", initialize_repo_stub)

    result = CliRunner().invoke(cli.app, ["init"])

    assert result.exit_code == 0
    assert "already initialized" in result.stderr


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


def _config_with_paths_error(
    msg: str,
) -> Callable[..., tuple[WdsyncConfig, Path, Path]]:
    """Return a stub for ``load_wdsync_config_with_paths`` that raises."""

    def _stub(runner: CommandRunner, *, cwd: Path | None = None) -> tuple[WdsyncConfig, Path, Path]:
        del runner, cwd
        raise MissingConfigError(msg)

    return _stub


def test_fetch_requires_peer_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    config_no_peer = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=None,
    )

    def load_stub(
        runner: CommandRunner, *, cwd: Path | None = None
    ) -> tuple[WdsyncConfig, Path, Path]:
        del runner, cwd
        return config_no_peer, Path("/tmp/repo"), Path("/tmp/repo/.git/wdsync")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_wdsync_config_with_paths", load_stub)

    result = CliRunner().invoke(cli.app, ["fetch"])

    assert result.exit_code == 1
    assert "not connected" in result.stderr


def test_fetch_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(
        cli, "load_wdsync_config_with_paths", _config_with_paths_error("fetch-config-missing")
    )

    result = CliRunner().invoke(cli.app, ["fetch"])

    assert result.exit_code == 1
    assert "fetch-config-missing" in result.stderr


def test_send_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(
        cli, "load_wdsync_config_with_paths", _config_with_paths_error("send-config-missing")
    )

    result = CliRunner().invoke(cli.app, ["send"])

    assert result.exit_code == 1
    assert "send-config-missing" in result.stderr


def test_status_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(
        cli, "load_wdsync_config_with_paths", _config_with_paths_error("status-config-missing")
    )

    result = CliRunner().invoke(cli.app, ["status"])

    assert result.exit_code == 1
    assert "status-config-missing" in result.stderr


def test_status_json_uses_status_formatter_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    fake_dconfig = DirectionConfig(
        direction=SyncDirection.FETCH,
        source=RepoEndpoint(root=Path("/tmp/peer"), native_root="/tmp/peer"),
        destination=RepoEndpoint(root=Path("/tmp/repo"), native_root="/tmp/repo"),
        source_git=GitExecution(command_argv=("git",), repo_native_root="/tmp/peer"),
        destination_git=GitExecution(command_argv=("git",), repo_native_root="/tmp/repo"),
        transfer=TransferExecution(
            command_argv=("rsync",),
            source_root="/tmp/peer",
            dest_root="/tmp/repo",
        ),
        source_is_local=False,
        destination_is_local=True,
        peer_command_argv=("wdsync.exe",),
    )
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
    doctor_report = DoctorReport(
        source_head="abc",
        destination_head="abc",
        source_dirty_count=1,
        head_relation=HeadRelation.SAME,
        destination_state=destination_state,
        warnings=(),
        risk_level=RiskLevel.LOW,
    )
    fake_ctx = SyncContext(
        dconfig=fake_dconfig,
        source_state=source_state,
        destination_state=destination_state,
        conflicts=(),
        doctor_report=doctor_report,
        manifest_paths=frozenset(),
        orphaned_paths=frozenset(),
    )

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

    class DummyPeerSession:
        def __enter__(self) -> DummyPeerSession:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def build_sync_context_stub(
        dconfig: cli.DirectionConfig,
        runner: CommandRunner,
        state_path: Path,
        *,
        peer_session: object | None = None,
    ) -> SyncContext:
        del dconfig, runner, state_path, peer_session
        return fake_ctx

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(
        cli,
        "_load_and_build",
        load_and_build_stub,  # pyright: ignore[reportPrivateUsage]
    )
    monkeypatch.setattr(cli, "build_sync_context", build_sync_context_stub)

    def peer_session_stub(dconfig: DirectionConfig) -> DummyPeerSession:
        del dconfig
        return DummyPeerSession()

    monkeypatch.setattr(
        cli,
        "_peer_session_for",
        peer_session_stub,  # pyright: ignore[reportPrivateUsage]
    )

    result = CliRunner().invoke(cli.app, ["status", "--json"])

    assert result.exit_code == 0
    assert '"source_entries"' in result.stdout
    assert '"destination_entries"' in result.stdout
    assert '"conflicts"' in result.stdout


def test_sync_flow_persists_manifest_to_local_and_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    fake_dconfig = DirectionConfig(
        direction=SyncDirection.FETCH,
        source=RepoEndpoint(root=Path("/tmp/peer"), native_root="/tmp/peer"),
        destination=RepoEndpoint(root=Path("/tmp/repo"), native_root="/tmp/repo"),
        source_git=GitExecution(command_argv=("git",), repo_native_root="/tmp/peer"),
        destination_git=GitExecution(command_argv=("git",), repo_native_root="/tmp/repo"),
        transfer=TransferExecution(
            command_argv=("rsync",),
            source_root="/tmp/peer",
            dest_root="/tmp/repo",
        ),
        source_is_local=False,
        destination_is_local=True,
        peer_command_argv=("wdsync.exe",),
    )
    fake_ctx = SyncContext(
        dconfig=fake_dconfig,
        source_state=SourceState(
            head="abc",
            entries=(
                StatusRecord(raw_xy="??", path="scratch.txt", orig_path=None, kind=StatusKind.NEW),
            ),
        ),
        destination_state=DestinationState(
            head="abc",
            modified_count=0,
            staged_count=0,
            untracked_count=0,
            entries=(),
        ),
        conflicts=(),
        doctor_report=DoctorReport(
            source_head="abc",
            destination_head="abc",
            source_dirty_count=1,
            head_relation=HeadRelation.SAME,
            destination_state=DestinationState(
                head="abc",
                modified_count=0,
                staged_count=0,
                untracked_count=0,
                entries=(),
            ),
            warnings=(),
            risk_level=RiskLevel.LOW,
        ),
        manifest_paths=frozenset(),
        orphaned_paths=frozenset(),
    )
    observed_local: list[tuple[Path, frozenset[str]]] = []
    observed_remote: list[frozenset[str]] = []
    destination_after = DestinationState(
        head="abc",
        modified_count=0,
        staged_count=0,
        untracked_count=0,
        entries=(),
    )

    class DummyPeerSession:
        def __enter__(self) -> DummyPeerSession:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def status(self) -> DestinationState:
            return destination_after

        def write_manifest(self, mirrored_paths: frozenset[str]) -> None:
            observed_remote.append(mirrored_paths)

    def peer_session_stub(dconfig: DirectionConfig) -> DummyPeerSession:
        del dconfig
        return DummyPeerSession()

    def build_sync_context_stub(
        dconfig: cli.DirectionConfig,
        runner: CommandRunner,
        state_path: Path,
        *,
        peer_session: object | None = None,
    ) -> SyncContext:
        del dconfig, runner, state_path, peer_session
        return fake_ctx

    def execute_plan_stub(
        plan: SyncPlan,
        dconfig: DirectionConfig,
        dest_dirty_paths: frozenset[str],
        runner: CommandRunner,
        *,
        confirm_sudo: Callable[[str], bool],
        peer_session: object | None,
    ) -> SyncResult:
        del dconfig, dest_dirty_paths, runner, confirm_sudo, peer_session
        return SyncResult(
            plan=plan,
            copied_count=1,
            deleted_count=0,
            skipped_count=0,
            performed_copy=True,
        )

    def write_manifest_stub(state_path: Path, untracked_paths: frozenset[str]) -> None:
        observed_local.append((state_path, untracked_paths))

    def ensure_local_rsync_available_stub(env: Environment, runner: CommandRunner) -> None:
        del env, runner

    def read_destination_state_stub(
        dconfig: DirectionConfig,
        runner: CommandRunner,
    ) -> DestinationState:
        del dconfig, runner
        return destination_after

    monkeypatch.setattr(cli, "ensure_local_rsync_available", ensure_local_rsync_available_stub)
    monkeypatch.setattr(
        cli,
        "_peer_session_for",
        peer_session_stub,  # pyright: ignore[reportPrivateUsage]
    )
    monkeypatch.setattr(cli, "build_sync_context", build_sync_context_stub)
    monkeypatch.setattr(cli, "_execute_plan", execute_plan_stub)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(cli, "read_destination_state", read_destination_state_stub)
    monkeypatch.setattr(cli, "write_manifest", write_manifest_stub)

    cli._sync_flow(  # pyright: ignore[reportPrivateUsage]
        fake_runner,
        fake_dconfig,
        Path("/tmp/repo/.git/wdsync"),
        as_json=False,
    )

    expected = frozenset({"scratch.txt"})
    assert observed_local == [(Path("/tmp/repo/.git/wdsync"), expected)]
    assert observed_remote == [expected]


def test_sync_flow_preserves_orphaned_manifest_paths_until_destination_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_runner = cast(CommandRunner, object())
    fake_dconfig = DirectionConfig(
        direction=SyncDirection.SEND,
        source=RepoEndpoint(root=Path("/tmp/repo"), native_root="/tmp/repo"),
        destination=RepoEndpoint(root=Path("/tmp/peer"), native_root="/tmp/peer"),
        source_git=GitExecution(command_argv=("git",), repo_native_root="/tmp/repo"),
        destination_git=GitExecution(command_argv=("git",), repo_native_root="/tmp/peer"),
        transfer=TransferExecution(
            command_argv=("rsync",),
            source_root="/tmp/repo",
            dest_root="/tmp/peer",
        ),
        source_is_local=True,
        destination_is_local=False,
        peer_command_argv=("wdsync.exe",),
    )
    dirty_destination = DestinationState(
        head="abc",
        modified_count=1,
        staged_count=0,
        untracked_count=0,
        dirty_paths=frozenset({"README.md"}),
        entries=(
            StatusRecord(raw_xy=" M", path="README.md", orig_path=None, kind=StatusKind.UNSTAGED),
        ),
    )
    fake_ctx = SyncContext(
        dconfig=fake_dconfig,
        source_state=SourceState(head="abc", entries=()),
        destination_state=dirty_destination,
        conflicts=(),
        doctor_report=DoctorReport(
            source_head="abc",
            destination_head="abc",
            source_dirty_count=0,
            head_relation=HeadRelation.SAME,
            destination_state=dirty_destination,
            warnings=(),
            risk_level=RiskLevel.LOW,
        ),
        manifest_paths=frozenset({"README.md"}),
        orphaned_paths=frozenset({"README.md"}),
    )
    observed_local: list[tuple[Path, frozenset[str]]] = []
    observed_remote: list[frozenset[str]] = []

    class DummyPeerSession:
        def __enter__(self) -> DummyPeerSession:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def status(self) -> DestinationState:
            return dirty_destination

        def restore(self, paths: tuple[str, ...]) -> RestoreResult:
            return RestoreResult(restored_count=0, warnings=("warning: could not restore",))

        def delete(self, paths: tuple[str, ...]) -> tuple[DeleteOutcome, ...]:
            return ()

        def write_manifest(self, mirrored_paths: frozenset[str]) -> None:
            observed_remote.append(mirrored_paths)

    def build_sync_context_stub(
        dconfig: cli.DirectionConfig,
        runner: CommandRunner,
        state_path: Path,
        *,
        peer_session: object | None = None,
    ) -> SyncContext:
        del dconfig, runner, state_path, peer_session
        return fake_ctx

    def write_manifest_stub(state_path: Path, mirrored_paths: frozenset[str]) -> None:
        observed_local.append((state_path, mirrored_paths))

    def ensure_local_rsync_available_stub(env: Environment, runner: CommandRunner) -> None:
        del env, runner

    def peer_session_stub(dconfig: DirectionConfig) -> DummyPeerSession:
        del dconfig
        return DummyPeerSession()

    monkeypatch.setattr(cli, "ensure_local_rsync_available", ensure_local_rsync_available_stub)
    monkeypatch.setattr(
        cli,
        "_peer_session_for",
        peer_session_stub,  # pyright: ignore[reportPrivateUsage]
    )
    monkeypatch.setattr(cli, "build_sync_context", build_sync_context_stub)
    monkeypatch.setattr(cli, "write_manifest", write_manifest_stub)

    cli._sync_flow(  # pyright: ignore[reportPrivateUsage]
        fake_runner,
        fake_dconfig,
        Path("/tmp/repo/.git/wdsync"),
        as_json=False,
    )

    expected = frozenset({"README.md"})
    assert observed_local == [(Path("/tmp/repo/.git/wdsync"), expected)]
    assert observed_remote == [expected]


# ---------------------------------------------------------------------------
# New tests — connect / disconnect
# ---------------------------------------------------------------------------


def test_connect_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(
        cli,
        "load_wdsync_config_with_paths",
        _config_with_paths_error("connect-config-missing"),
    )

    result = CliRunner().invoke(cli.app, ["connect"])

    assert result.exit_code == 1
    assert "connect-config-missing" in result.stderr


def test_connect_applies_runtime_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=None,
    )
    observed: dict[str, object] = {}

    def load_stub(
        runner: CommandRunner, *, cwd: Path | None = None
    ) -> tuple[WdsyncConfig, Path, Path]:
        del runner, cwd
        return config, Path("/tmp/repo"), Path("/tmp/repo/.git/wdsync")

    def connect_stub(
        updated: WdsyncConfig,
        repo_root: Path,
        runner: CommandRunner,
        sdir: Path,
    ) -> ConnectResult:
        del repo_root, runner, sdir
        observed["runtime"] = updated.runtime
        return ConnectResult(
            matched_by="remote_url",
            peer=PeerConfig(
                command_argv=("wdsync.exe",),
                root=Path("/tmp/peer"),
                root_native="C:\\peer",
            ),
        )

    def attach_file_logging_stub(sdir: Path) -> None:
        del sdir

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_wdsync_config_with_paths", load_stub)
    monkeypatch.setattr(cli, "connect_to_peer", connect_stub)
    monkeypatch.setattr(cli, "attach_file_logging", attach_file_logging_stub)

    result = CliRunner().invoke(
        cli.app,
        [
            "connect",
            "--wsl-distro",
            "Ubuntu-24.04",
            "--windows-peer-command",
            "python.exe -m wdsync",
            "--wsl-peer-command",
            "python -m wdsync",
        ],
    )

    assert result.exit_code == 0
    assert observed["runtime"] == RuntimePreferences(
        windows_peer_command_argv=("python.exe", "-m", "wdsync"),
        wsl_peer_command_argv=("python", "-m", "wdsync"),
        wsl_distro="Ubuntu-24.04",
    )


def test_disconnect_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(
        cli,
        "load_wdsync_config_with_paths",
        _config_with_paths_error("disconnect-config-missing"),
    )

    result = CliRunner().invoke(cli.app, ["disconnect"])

    assert result.exit_code == 1
    assert "disconnect-config-missing" in result.stderr


def test_disconnect_preserves_runtime_preferences(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url=None, root_commits=("abc",)),
        peer=PeerConfig(
            command_argv=("wdsync.exe",),
            root=Path("/tmp/peer"),
            root_native="C:\\peer",
        ),
        runtime=RuntimePreferences(wsl_distro="Ubuntu-24.04"),
    )
    saved: list[WdsyncConfig] = []

    def load_stub(
        runner: CommandRunner, *, cwd: Path | None = None
    ) -> tuple[WdsyncConfig, Path, Path]:
        del runner, cwd
        return config, Path("/tmp/repo"), Path("/tmp/repo/.git/wdsync")

    def save_stub(updated: WdsyncConfig, sdir: Path) -> None:
        del sdir
        saved.append(updated)

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_wdsync_config_with_paths", load_stub)
    monkeypatch.setattr(cli, "save_wdsync_config", save_stub)

    result = CliRunner().invoke(cli.app, ["disconnect"])

    assert result.exit_code == 0
    assert saved
    assert saved[0].peer is None
    assert saved[0].runtime == RuntimePreferences(wsl_distro="Ubuntu-24.04")


def test_deinit_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    fake_result = DeinitializeResult(
        repo_root=Path("/tmp/repo"),
        state_path=Path("/tmp/repo/.git/wdsync"),
        marker_path=Path("/tmp/repo/.wdsync"),
        removed_config=True,
        removed_manifest=True,
        removed_log=False,
        removed_marker=True,
        removed_exclude_entry=True,
        removed_state_dir=True,
    )

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)

    def deinitialize_repo_stub(runner: CommandRunner) -> DeinitializeResult:
        del runner
        return fake_result

    monkeypatch.setattr(cli, "deinitialize_repo", deinitialize_repo_stub)

    result = CliRunner().invoke(cli.app, ["deinit"])

    assert result.exit_code == 0
    assert "Deinitialized wdsync" in result.stderr


def test_deinit_reports_already_deinitialized(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    fake_result = DeinitializeResult(
        repo_root=Path("/tmp/repo"),
        state_path=Path("/tmp/repo/.git/wdsync"),
        marker_path=Path("/tmp/repo/.wdsync"),
        removed_config=False,
        removed_manifest=False,
        removed_log=False,
        removed_marker=False,
        removed_exclude_entry=False,
        removed_state_dir=False,
        already_deinitialized=True,
    )

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)

    def deinitialize_repo_stub(runner: CommandRunner) -> DeinitializeResult:
        del runner
        return fake_result

    monkeypatch.setattr(cli, "deinitialize_repo", deinitialize_repo_stub)

    result = CliRunner().invoke(cli.app, ["deinit"])

    assert result.exit_code == 0
    assert "already deinitialized" in result.stderr

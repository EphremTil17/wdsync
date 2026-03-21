from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
import typer
from typer.testing import CliRunner

from wdsync import cli
from wdsync.exceptions import MissingConfigError, ShellDetectionError
from wdsync.models import (
    DestinationState,
    DoctorReport,
    HeadRelation,
    InitResult,
    PreviewRow,
    ProjectConfig,
    RiskLevel,
    ShellInstallResult,
    ShellName,
    SourceState,
    SyncPlan,
    SyncResult,
)
from wdsync.runner import CommandRunner


def _record_preview(
    calls: list[tuple[str, bool]],
    runner: CommandRunner,
    *,
    as_json: bool,
) -> None:
    del runner
    calls.append(("preview", as_json))


def _record_sync(
    calls: list[tuple[str, bool]],
    runner: CommandRunner,
    *,
    as_json: bool,
) -> None:
    del runner
    calls.append(("sync", as_json))


def test_root_defaults_to_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool]] = []
    fake_runner = cast(CommandRunner, object())

    def preview_flow(runner: CommandRunner, *, as_json: bool) -> None:
        _record_preview(calls, runner, as_json=as_json)

    def sync_flow(runner: CommandRunner, *, as_json: bool) -> None:
        _record_sync(calls, runner, as_json=as_json)

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "_preview_flow", preview_flow)
    monkeypatch.setattr(cli, "_sync_flow", sync_flow)

    result = CliRunner().invoke(cli.app, [])

    assert result.exit_code == 0
    assert calls == [("preview", False)]


def test_fetch_alias_dispatches_to_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool]] = []
    fake_runner = cast(CommandRunner, object())

    def preview_flow(runner: CommandRunner, *, as_json: bool) -> None:
        _record_preview(calls, runner, as_json=as_json)

    def sync_flow(runner: CommandRunner, *, as_json: bool) -> None:
        _record_sync(calls, runner, as_json=as_json)

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "_preview_flow", preview_flow)
    monkeypatch.setattr(cli, "_sync_flow", sync_flow)

    result = CliRunner().invoke(cli.app, ["-f", "--json"])

    assert result.exit_code == 0
    assert calls == [("sync", True)]


def test_init_command_reports_written_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    project_config = ProjectConfig(
        dest_root=Path("/tmp/dest"),
        config_path=Path("/tmp/dest/.wdsync"),
        source_root=Path("/tmp/source"),
        source_root_windows="C:\\tmp\\source",
    )
    fake_runner = cast(CommandRunner, object())

    def init_project_stub(source: str, runner: CommandRunner) -> InitResult:
        del source, runner
        return InitResult(
            config=project_config,
            wrote_config=True,
            exclude_path=Path("/tmp/dest/.git/info/exclude"),
            updated_exclude=True,
        )

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "init_project", init_project_stub)

    result = CliRunner().invoke(cli.app, ["init", "/tmp/source"])

    assert result.exit_code == 0
    assert "Updated /tmp/dest/.wdsync" in result.stdout
    assert "Added .wdsync to /tmp/dest/.git/info/exclude" in result.stdout


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


def test_preview_command_uses_real_flow_with_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    config = ProjectConfig(
        dest_root=Path("/tmp/dest"),
        config_path=Path("/tmp/dest/.wdsync"),
        source_root=Path("/tmp/source"),
        source_root_windows="C:\\tmp\\source",
    )
    source_state = SourceState(head="abc123", entries=())
    plan = SyncPlan(
        source_root=config.source_root,
        dest_root=config.dest_root,
        preview_rows=(
            PreviewRow(
                path="tracked.txt",
                raw_xy=" M",
                label="unstaged",
                syncable=True,
            ),
        ),
        copy_paths=("tracked.txt",),
        skipped_paths=(),
        warnings=(),
    )

    def load_project_config_stub(runner: CommandRunner) -> ProjectConfig:
        del runner
        return config

    def read_source_state_stub(cfg: ProjectConfig, runner: CommandRunner) -> SourceState:
        del cfg, runner
        return source_state

    def build_sync_plan_stub(cfg: ProjectConfig, state: SourceState) -> SyncPlan:
        del cfg, state
        return plan

    def preview_to_json_stub(built_plan: SyncPlan) -> dict[str, bool]:
        del built_plan
        return {"ok": True}

    def render_json_stub(payload: object) -> str:
        del payload
        return "preview-json"

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_project_config", load_project_config_stub)
    monkeypatch.setattr(cli, "read_source_state", read_source_state_stub)
    monkeypatch.setattr(cli, "build_sync_plan", build_sync_plan_stub)
    monkeypatch.setattr(cli, "preview_to_json", preview_to_json_stub)
    monkeypatch.setattr(cli, "render_json", render_json_stub)

    result = CliRunner().invoke(cli.app, ["preview", "--json"])

    assert result.exit_code == 0
    assert result.stdout == "preview-json\n"


def test_sync_command_uses_real_flow_with_text(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    config = ProjectConfig(
        dest_root=Path("/tmp/dest"),
        config_path=Path("/tmp/dest/.wdsync"),
        source_root=Path("/tmp/source"),
        source_root_windows="C:\\tmp\\source",
    )
    source_state = SourceState(head="abc123", entries=())
    plan = SyncPlan(
        source_root=config.source_root,
        dest_root=config.dest_root,
        preview_rows=(
            PreviewRow(
                path="tracked.txt",
                raw_xy=" M",
                label="unstaged",
                syncable=True,
            ),
        ),
        copy_paths=("tracked.txt",),
        skipped_paths=(),
        warnings=(),
    )
    sync_result = SyncResult(plan=plan, copied_count=1, skipped_count=0, performed_copy=True)

    def load_project_config_stub(runner: CommandRunner) -> ProjectConfig:
        del runner
        return config

    def read_source_state_stub(cfg: ProjectConfig, runner: CommandRunner) -> SourceState:
        del cfg, runner
        return source_state

    def build_sync_plan_stub(cfg: ProjectConfig, state: SourceState) -> SyncPlan:
        del cfg, state
        return plan

    def execute_sync_stub(built_plan: SyncPlan, runner: CommandRunner) -> SyncResult:
        del built_plan, runner
        return sync_result

    def format_sync_result_stub(result_obj: SyncResult) -> str:
        del result_obj
        return "sync-text"

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_project_config", load_project_config_stub)
    monkeypatch.setattr(cli, "read_source_state", read_source_state_stub)
    monkeypatch.setattr(cli, "build_sync_plan", build_sync_plan_stub)
    monkeypatch.setattr(cli, "execute_sync", execute_sync_stub)
    monkeypatch.setattr(cli, "format_sync_result", format_sync_result_stub)

    result = CliRunner().invoke(cli.app, ["sync"])

    assert result.exit_code == 0
    assert result.stdout == "sync-text\n"


def test_doctor_command_uses_real_flow_with_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())
    config = ProjectConfig(
        dest_root=Path("/tmp/dest"),
        config_path=Path("/tmp/dest/.wdsync"),
        source_root=Path("/tmp/source"),
        source_root_windows="C:\\tmp\\source",
    )
    source_state = SourceState(head="abc123", entries=())
    destination_state = DestinationState(
        head="abc123",
        modified_count=0,
        staged_count=0,
        untracked_count=0,
    )
    report = DoctorReport(
        source_head="abc123",
        destination_head="abc123",
        source_dirty_count=0,
        head_relation=HeadRelation.SAME,
        destination_state=destination_state,
        warnings=(),
        risk_level=RiskLevel.LOW,
    )

    def load_project_config_stub(runner: CommandRunner) -> ProjectConfig:
        del runner
        return config

    def read_source_state_stub(cfg: ProjectConfig, runner: CommandRunner) -> SourceState:
        del cfg, runner
        return source_state

    def read_destination_state_stub(dest_root: Path, runner: CommandRunner) -> DestinationState:
        del dest_root, runner
        return destination_state

    def build_doctor_report_stub(
        cfg: ProjectConfig,
        src_state: SourceState,
        dest_state: DestinationState,
        runner: CommandRunner,
    ) -> DoctorReport:
        del cfg, src_state, dest_state, runner
        return report

    def doctor_to_json_stub(report_obj: DoctorReport) -> dict[str, bool]:
        del report_obj
        return {"ok": True}

    def render_json_stub(payload: object) -> str:
        del payload
        return "doctor-json"

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "load_project_config", load_project_config_stub)
    monkeypatch.setattr(cli, "read_source_state", read_source_state_stub)
    monkeypatch.setattr(cli, "read_destination_state", read_destination_state_stub)
    monkeypatch.setattr(cli, "build_doctor_report", build_doctor_report_stub)
    monkeypatch.setattr(cli, "doctor_to_json", doctor_to_json_stub)
    monkeypatch.setattr(cli, "render_json", render_json_stub)

    result = CliRunner().invoke(cli.app, ["doctor", "--json"])

    assert result.exit_code == 0
    assert result.stdout == "doctor-json\n"


def test_root_surfaces_user_facing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def preview_flow_error(runner: CommandRunner, *, as_json: bool) -> None:
        del runner, as_json
        raise MissingConfigError("missing-root")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "_preview_flow", preview_flow_error)

    result = CliRunner().invoke(cli.app, [])

    assert result.exit_code == 1
    assert "missing-root" in result.stderr


def test_preview_command_surfaces_user_facing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def preview_flow_error(runner: CommandRunner, *, as_json: bool) -> None:
        del runner, as_json
        raise MissingConfigError("missing")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "_preview_flow", preview_flow_error)

    result = CliRunner().invoke(cli.app, ["preview"])

    assert result.exit_code == 1
    assert "missing" in result.stderr


def test_sync_command_surfaces_user_facing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def sync_flow_error(runner: CommandRunner, *, as_json: bool) -> None:
        del runner, as_json
        raise MissingConfigError("sync-missing")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "_sync_flow", sync_flow_error)

    result = CliRunner().invoke(cli.app, ["sync"])

    assert result.exit_code == 1
    assert "sync-missing" in result.stderr


def test_init_command_reports_verified_when_nothing_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_config = ProjectConfig(
        dest_root=Path("/tmp/dest"),
        config_path=Path("/tmp/dest/.wdsync"),
        source_root=Path("/tmp/source"),
        source_root_windows="C:\\tmp\\source",
    )
    fake_runner = cast(CommandRunner, object())

    def init_project_stub(source: str, runner: CommandRunner) -> InitResult:
        del source, runner
        return InitResult(
            config=project_config,
            wrote_config=False,
            exclude_path=Path("/tmp/dest/.git/info/exclude"),
            updated_exclude=False,
        )

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "init_project", init_project_stub)

    result = CliRunner().invoke(cli.app, ["init", "/tmp/source"])

    assert result.exit_code == 0
    assert "Verified /tmp/dest/.wdsync" in result.stdout
    assert "Added .wdsync" not in result.stdout


def test_init_command_surfaces_user_facing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def init_project_error(source: str, runner: CommandRunner) -> InitResult:
        del source, runner
        raise MissingConfigError("init-error")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "init_project", init_project_error)

    result = CliRunner().invoke(cli.app, ["init", "/tmp/source"])

    assert result.exit_code == 1
    assert "init-error" in result.stderr


def test_doctor_command_surfaces_user_facing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_runner = cast(CommandRunner, object())

    def doctor_flow_error(runner: CommandRunner, *, as_json: bool) -> None:
        del runner, as_json
        raise MissingConfigError("doctor-missing")

    monkeypatch.setattr(cli, "build_runner", lambda: fake_runner)
    monkeypatch.setattr(cli, "_doctor_flow", doctor_flow_error)

    result = CliRunner().invoke(cli.app, ["doctor"])

    assert result.exit_code == 1
    assert "doctor-missing" in result.stderr


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

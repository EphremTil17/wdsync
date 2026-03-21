from __future__ import annotations

from typing import Annotated, NoReturn, cast

import typer

from wdsync.config import init_project, load_project_config
from wdsync.doctor import build_doctor_report
from wdsync.exceptions import WdSyncError
from wdsync.formatters import (
    doctor_to_json,
    format_doctor,
    format_preview,
    format_sync_result,
    preview_to_json,
    render_json,
    sync_to_json,
)
from wdsync.git_dest import read_destination_state
from wdsync.git_source import read_source_state
from wdsync.models import ShellName
from wdsync.planner import build_sync_plan
from wdsync.runner import CommandRunner, build_runner
from wdsync.shell import install_shell_assets
from wdsync.sync import execute_sync

app = typer.Typer(
    add_completion=True,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
)
shell_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(shell_app, name="shell")


def _exit_with_error(error: WdSyncError) -> NoReturn:
    typer.echo(str(error), err=True)
    raise typer.Exit(code=1)


def _parse_shell_name(value: str | None) -> ShellName | None:
    if value is None:
        return None
    if value not in {"bash", "fish", "zsh"}:
        raise typer.BadParameter("Shell must be one of: bash, fish, zsh.")
    return cast(ShellName, value)


def _preview_flow(runner: CommandRunner, *, as_json: bool) -> None:
    config = load_project_config(runner)
    source_state = read_source_state(config, runner)
    plan = build_sync_plan(config, source_state)
    typer.echo(render_json(preview_to_json(plan)) if as_json else format_preview(plan))


def _sync_flow(runner: CommandRunner, *, as_json: bool) -> None:
    config = load_project_config(runner)
    source_state = read_source_state(config, runner)
    plan = build_sync_plan(config, source_state)
    result = execute_sync(plan, runner)
    typer.echo(render_json(sync_to_json(result)) if as_json else format_sync_result(result))


def _doctor_flow(runner: CommandRunner, *, as_json: bool) -> None:
    config = load_project_config(runner)
    source_state = read_source_state(config, runner)
    destination_state = read_destination_state(config.dest_root, runner)
    report = build_doctor_report(config, source_state, destination_state, runner)
    typer.echo(render_json(doctor_to_json(report)) if as_json else format_doctor(report))


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    fetch: Annotated[
        bool,
        typer.Option("--fetch", "-f", help="Compatibility alias for sync."),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Render preview output as JSON when no subcommand is given."),
    ] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return

    runner = build_runner()
    try:
        if fetch:
            _sync_flow(runner, as_json=as_json)
        else:
            _preview_flow(runner, as_json=as_json)
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def preview(
    as_json: Annotated[bool, typer.Option("--json", help="Render preview output as JSON.")] = False,
) -> None:
    runner = build_runner()
    try:
        _preview_flow(runner, as_json=as_json)
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def sync(
    as_json: Annotated[bool, typer.Option("--json", help="Render sync output as JSON.")] = False,
) -> None:
    runner = build_runner()
    try:
        _sync_flow(runner, as_json=as_json)
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def init(
    source: Annotated[
        str,
        typer.Argument(help="WSL path to the Windows source repository."),
    ],
) -> None:
    runner = build_runner()
    try:
        result = init_project(source, runner)
    except WdSyncError as error:
        _exit_with_error(error)

    action = "Updated" if result.wrote_config else "Verified"
    typer.echo(f"{action} {result.config.config_path}")
    typer.echo(f"  SRC={result.config.source_root}")
    if result.updated_exclude:
        typer.echo(f"Added .wdsync to {result.exclude_path}")


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Render doctor output as JSON.")] = False,
) -> None:
    runner = build_runner()
    try:
        _doctor_flow(runner, as_json=as_json)
    except WdSyncError as error:
        _exit_with_error(error)


@shell_app.command("install")
def shell_install(
    shell_name: Annotated[
        str | None,
        typer.Option("--shell", help="Override auto-detection with bash, fish, or zsh."),
    ] = None,
) -> None:
    try:
        result = install_shell_assets(app, shell_name=_parse_shell_name(shell_name))
    except WdSyncError as error:
        _exit_with_error(error)

    typer.echo(f"Installed {result.shell} shell assets:")
    for path in result.installed_paths:
        typer.echo(f"  {path}")
    for note in result.notes:
        typer.echo(f"  note: {note}")


def main() -> None:
    app()

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, NoReturn, cast

import typer

from wdsync.config import init_project, load_project_config
from wdsync.direction import build_direction_config
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
from wdsync.manifest import read_manifest, write_manifest
from wdsync.models import DirectionConfig, ShellName, StatusKind, SyncDirection
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


def _preview_flow(runner: CommandRunner, dconfig: DirectionConfig, *, as_json: bool) -> None:
    source_state = read_source_state(dconfig, runner)
    plan = build_sync_plan(dconfig, source_state)
    typer.echo(render_json(preview_to_json(plan)) if as_json else format_preview(plan))


def _sync_flow(runner: CommandRunner, dconfig: DirectionConfig, *, as_json: bool) -> None:
    source_state = read_source_state(dconfig, runner)
    destination_state = read_destination_state(dconfig, runner)
    plan = build_sync_plan(dconfig, source_state)

    # Reconciliation: restore tracked files deleted in dest but no longer deleted in source
    source_deleted_paths = frozenset(
        entry.path for entry in source_state.entries if entry.kind is StatusKind.DELETED
    )
    restore_candidates = destination_state.wt_deleted_paths - source_deleted_paths
    if restore_candidates:
        plan = replace(plan, restore_paths=tuple(sorted(restore_candidates)))

    # Manifest: detect orphaned untracked files from previous syncs
    source_dirty_paths = frozenset(entry.path for entry in source_state.entries)
    prev_untracked = read_manifest(dconfig.dest_root)
    orphaned = prev_untracked - source_dirty_paths
    if orphaned:
        plan = replace(plan, delete_paths=plan.delete_paths + tuple(sorted(orphaned)))

    def _confirm_sudo(rel_path: str) -> bool:
        return typer.confirm(
            f"  Permission denied on {rel_path!r}. Retry with sudo?",
            default=False,
        )

    result = execute_sync(
        plan,
        runner,
        dest_dirty_paths=destination_state.dirty_paths,
        confirm_sudo=_confirm_sudo,
        dest_git=dconfig.dest_git,
        dest_root_native=dconfig.dest_root_native,
    )

    # Update manifest with currently synced untracked files
    current_untracked = frozenset(
        entry.path for entry in source_state.entries if entry.kind is StatusKind.NEW
    )
    write_manifest(dconfig.dest_root, current_untracked)

    typer.echo(render_json(sync_to_json(result)) if as_json else format_sync_result(result))


def _doctor_flow(runner: CommandRunner, dconfig: DirectionConfig, *, as_json: bool) -> None:
    source_state = read_source_state(dconfig, runner)
    destination_state = read_destination_state(dconfig, runner)
    report = build_doctor_report(dconfig, source_state, destination_state, runner)
    typer.echo(render_json(doctor_to_json(report)) if as_json else format_doctor(report))


def _build_dconfig(runner: CommandRunner, direction: SyncDirection) -> DirectionConfig:
    config = load_project_config(runner)
    return build_direction_config(config, direction)


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    fetch_flag: Annotated[
        bool,
        typer.Option("--fetch", "-f", help="Compatibility alias for fetch."),
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
        dconfig = _build_dconfig(runner, SyncDirection.FETCH)
        if fetch_flag:
            _sync_flow(runner, dconfig, as_json=as_json)
        else:
            _preview_flow(runner, dconfig, as_json=as_json)
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def preview(
    as_json: Annotated[bool, typer.Option("--json", help="Render output as JSON.")] = False,
    send_flag: Annotated[
        bool, typer.Option("--send", help="Preview the send direction (WSL to Windows).")
    ] = False,
) -> None:
    runner = build_runner()
    try:
        direction = SyncDirection.SEND if send_flag else SyncDirection.FETCH
        dconfig = _build_dconfig(runner, direction)
        _preview_flow(runner, dconfig, as_json=as_json)
    except WdSyncError as error:
        _exit_with_error(error)


@app.command(name="sync")
def sync_cmd(
    as_json: Annotated[bool, typer.Option("--json", help="Render output as JSON.")] = False,
) -> None:
    runner = build_runner()
    try:
        dconfig = _build_dconfig(runner, SyncDirection.FETCH)
        _sync_flow(runner, dconfig, as_json=as_json)
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def fetch(
    as_json: Annotated[bool, typer.Option("--json", help="Render output as JSON.")] = False,
) -> None:
    runner = build_runner()
    try:
        dconfig = _build_dconfig(runner, SyncDirection.FETCH)
        _sync_flow(runner, dconfig, as_json=as_json)
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def send(
    as_json: Annotated[bool, typer.Option("--json", help="Render output as JSON.")] = False,
) -> None:
    runner = build_runner()
    try:
        dconfig = _build_dconfig(runner, SyncDirection.SEND)
        _sync_flow(runner, dconfig, as_json=as_json)
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
    as_json: Annotated[bool, typer.Option("--json", help="Render output as JSON.")] = False,
    send_flag: Annotated[
        bool, typer.Option("--send", help="Doctor report for the send direction.")
    ] = False,
) -> None:
    runner = build_runner()
    try:
        direction = SyncDirection.SEND if send_flag else SyncDirection.FETCH
        dconfig = _build_dconfig(runner, direction)
        _doctor_flow(runner, dconfig, as_json=as_json)
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

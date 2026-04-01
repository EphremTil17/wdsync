from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Annotated, NoReturn, cast

import typer

from wdsync.core.config import (
    find_repo_root,
    initialize_repo,
    load_wdsync_config,
    save_wdsync_config,
    state_dir,
)
from wdsync.core.exceptions import WdSyncError
from wdsync.core.logging import attach_file_logging, configure_logging, log
from wdsync.core.models import (
    DirectionConfig,
    ShellName,
    StatusKind,
    SyncDirection,
    WdsyncConfig,
)
from wdsync.core.protocol import (
    PROTOCOL_VERSION,
    RpcMethod,
    build_error_response,
    build_handshake_response,
)
from wdsync.core.runner import CommandRunner, build_runner
from wdsync.git.dest import read_destination_state
from wdsync.git.source import read_source_state
from wdsync.output.formatters import (
    format_status,
    format_sync_result,
    render_json,
    status_to_json,
    sync_to_json,
)
from wdsync.shell.assets import install_shell_assets
from wdsync.sync.conflict import detect_conflicts
from wdsync.sync.direction import build_direction_from_wdsync_config
from wdsync.sync.doctor import build_doctor_report
from wdsync.sync.engine import execute_sync
from wdsync.sync.manifest import read_manifest, write_manifest
from wdsync.sync.planner import build_sync_plan

app = typer.Typer(
    add_completion=True,
    no_args_is_help=True,
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


def _load_and_build(
    runner: CommandRunner, direction: SyncDirection
) -> tuple[DirectionConfig, Path, WdsyncConfig]:
    config = load_wdsync_config(runner)
    repo_root = find_repo_root(runner)
    sdir = state_dir(repo_root, runner)
    attach_file_logging(sdir)
    dconfig = build_direction_from_wdsync_config(config, direction, repo_root)
    return dconfig, sdir, config


def _sync_flow(
    runner: CommandRunner,
    dconfig: DirectionConfig,
    sdir: Path,
    *,
    as_json: bool,
    force: bool = False,
) -> None:
    log.debug(f"Starting sync ({dconfig.direction.value} direction)")
    source_state = read_source_state(dconfig, runner)
    destination_state = read_destination_state(dconfig, runner)

    conflicts = detect_conflicts(source_state, destination_state)
    if conflicts and not force:
        for c in conflicts:
            log.error(
                f"Conflict: {c.path!r} modified on both sides "
                f"(source: {c.source_xy}, dest: {c.dest_xy})"
            )
        log.error(f"{len(conflicts)} conflict(s) detected. Use --force to override.")
        return
    if conflicts and force:
        for c in conflicts:
            log.warning(f"Forcing sync of conflicting file: {c.path!r}")
    plan = build_sync_plan(dconfig, source_state)

    source_deleted_paths = frozenset(
        entry.path for entry in source_state.entries if entry.kind is StatusKind.DELETED
    )
    restore_candidates = destination_state.wt_deleted_paths - source_deleted_paths
    if restore_candidates:
        plan = replace(plan, restore_paths=tuple(sorted(restore_candidates)))

    source_dirty_paths = frozenset(entry.path for entry in source_state.entries)
    prev_untracked = read_manifest(sdir)
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

    current_untracked = frozenset(
        entry.path for entry in source_state.entries if entry.kind is StatusKind.NEW
    )
    write_manifest(sdir, current_untracked)

    if as_json:
        typer.echo(render_json(sync_to_json(result)))
    else:
        log.info(format_sync_result(result))


@app.callback()
def root(
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable verbose debug logging."),
    ] = False,
) -> None:
    configure_logging(debug=debug)


@app.command()
def init() -> None:
    """Initialize wdsync in the current git repository."""
    runner = build_runner()
    try:
        result = initialize_repo(runner)
    except WdSyncError as error:
        _exit_with_error(error)

    typer.echo(f"Initialized wdsync in {result.repo_root}")
    typer.echo(f"  config: {result.config_path}")
    typer.echo(f"  marker: {result.marker_path}")
    identity = result.identity
    if identity.remote_url:
        typer.echo(f"  identity remote: {identity.remote_url}")
    if identity.root_commits:
        typer.echo(f"  identity roots: {', '.join(identity.root_commits)}")


@app.command()
def fetch(
    as_json: Annotated[bool, typer.Option("--json", help="Render output as JSON.")] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Override conflict detection and sync all files.")
    ] = False,
) -> None:
    runner = build_runner()
    try:
        dconfig, sdir, _ = _load_and_build(runner, SyncDirection.FETCH)
        _sync_flow(runner, dconfig, sdir, as_json=as_json, force=force)
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def send(
    as_json: Annotated[bool, typer.Option("--json", help="Render output as JSON.")] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Override conflict detection and sync all files.")
    ] = False,
) -> None:
    runner = build_runner()
    try:
        dconfig, sdir, _ = _load_and_build(runner, SyncDirection.SEND)
        _sync_flow(runner, dconfig, sdir, as_json=as_json, force=force)
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def status(
    as_json: Annotated[bool, typer.Option("--json", help="Render output as JSON.")] = False,
    send_flag: Annotated[
        bool, typer.Option("--send", help="Status for the send direction.")
    ] = False,
) -> None:
    runner = build_runner()
    try:
        direction = SyncDirection.SEND if send_flag else SyncDirection.FETCH
        dconfig, sdir, _ = _load_and_build(runner, direction)

        source_state = read_source_state(dconfig, runner)
        destination_state = read_destination_state(dconfig, runner)
        conflicts = detect_conflicts(source_state, destination_state)
        report = build_doctor_report(dconfig, source_state, destination_state, runner)

        source_dirty_paths = frozenset(entry.path for entry in source_state.entries)
        prev_untracked = read_manifest(sdir)
        orphaned_count = len(prev_untracked - source_dirty_paths)

        if as_json:
            typer.echo(
                render_json(
                    status_to_json(
                        direction=direction,
                        source_state=source_state,
                        destination_state=destination_state,
                        conflicts=conflicts,
                        head_relation=report.head_relation.value,
                        risk_level=report.risk_level.value,
                        orphaned_count=orphaned_count,
                    )
                )
            )
        else:
            log.info(
                format_status(
                    direction=direction,
                    source_state=source_state,
                    destination_state=destination_state,
                    conflicts=conflicts,
                    head_relation=report.head_relation.value,
                    risk_level=report.risk_level.value,
                    orphaned_count=orphaned_count,
                )
            )
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def connect() -> None:
    """Connect to a peer wdsync instance on the other side (WSL/Windows)."""
    runner = build_runner()
    try:
        _config = load_wdsync_config(runner)
    except WdSyncError as error:
        _exit_with_error(error)
    log.error(
        "connect is not yet implemented. "
        "Peer RPC requires wdsync installed on both sides. "
        "This will be available in a future release."
    )
    raise typer.Exit(code=1)


@app.command()
def disconnect() -> None:
    """Remove the peer connection from wdsync config."""
    runner = build_runner()
    try:
        config = load_wdsync_config(runner)
        if config.peer is None:
            log.info("No peer configured; nothing to disconnect.")
            return
        repo_root = find_repo_root(runner)
        sdir = state_dir(repo_root, runner)
        updated = WdsyncConfig(version=config.version, identity=config.identity, peer=None)
        save_wdsync_config(updated, sdir)
        log.info("Disconnected from peer.")
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


@app.command(hidden=True)
def rpc() -> None:
    """Hidden RPC mode for cross-platform communication."""
    import json
    import sys

    configure_logging(debug=False)
    raw = sys.stdin.readline().strip()
    if not raw:
        typer.echo(render_json(build_error_response("empty request")))
        raise typer.Exit(code=1)
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError:
        typer.echo(render_json(build_error_response("invalid JSON")))
        raise typer.Exit(code=1) from None

    if not isinstance(parsed, dict):
        typer.echo(render_json(build_error_response("expected JSON object")))
        raise typer.Exit(code=1)

    request: dict[str, object] = cast(dict[str, object], parsed)
    method = request.get("method")
    version = request.get("version")

    if method != RpcMethod.HANDSHAKE:
        typer.echo(render_json(build_error_response("expected handshake")))
        raise typer.Exit(code=1)

    if version != PROTOCOL_VERSION:
        typer.echo(render_json(build_error_response(f"unsupported protocol version: {version}")))
        raise typer.Exit(code=1)

    typer.echo(
        render_json(
            build_handshake_response(
                identity_dict={"remote_url": None, "root_commits": []},
                repo_root="<pending>",
                repo_root_native="<pending>",
            )
        )
    )


def main() -> None:
    app()

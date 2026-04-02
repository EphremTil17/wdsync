from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Annotated, NoReturn, cast

import typer

from wdsync.core.config import (
    initialize_repo,
    load_wdsync_config_with_paths,
    save_wdsync_config,
)
from wdsync.core.environment import detect_environment
from wdsync.core.exceptions import WdSyncError
from wdsync.core.interop import ensure_local_rsync_available
from wdsync.core.logging import attach_file_logging, configure_logging, log
from wdsync.core.models import (
    DeleteOutcome,
    DirectionConfig,
    PeerConfig,
    RestoreResult,
    RuntimePreferences,
    ShellName,
    StatusKind,
    SyncDirection,
    SyncPlan,
    SyncResult,
    WdsyncConfig,
)
from wdsync.core.protocol import build_error_response
from wdsync.core.runner import CommandRunner, build_runner
from wdsync.output.formatters import (
    format_status,
    format_sync_result,
    render_json,
    status_to_json,
    sync_to_json,
)
from wdsync.rpc.connect import connect_to_peer
from wdsync.rpc.handlers import handle_rpc_request
from wdsync.rpc.session import PeerSession
from wdsync.shell.assets import install_shell_assets
from wdsync.sync.context import build_sync_context
from wdsync.sync.direction import build_direction_from_wdsync_config
from wdsync.sync.engine import copy_files, execute_sync
from wdsync.sync.manifest import write_manifest
from wdsync.sync.planner import build_sync_plan

app = typer.Typer(
    add_completion=True,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
shell_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(shell_app, name="shell")


def _exit_with_error(error: WdSyncError) -> NoReturn:
    log.error(str(error))
    raise typer.Exit(code=1)


def _parse_shell_name(value: str | None) -> ShellName | None:
    if value is None:
        return None
    if value not in {"bash", "fish", "zsh"}:
        raise typer.BadParameter("Shell must be one of: bash, fish, zsh.")
    return cast(ShellName, value)


def _parse_command_argv(
    value: str | None,
    *,
    option_name: str,
    posix: bool,
) -> tuple[str, ...] | None:
    if value is None:
        return None
    try:
        argv = tuple(_strip_matching_quotes(part) for part in shlex.split(value, posix=posix))
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid {option_name}: {exc}") from exc
    if not argv:
        raise typer.BadParameter(f"{option_name} cannot be empty.")
    return argv


def _runtime_from_options(
    current: RuntimePreferences,
    *,
    wsl_distro: str | None,
    windows_peer_command: str | None,
    wsl_peer_command: str | None,
) -> RuntimePreferences:
    windows_peer_command_argv = _parse_command_argv(
        windows_peer_command,
        option_name="--windows-peer-command",
        posix=False,
    )
    wsl_peer_command_argv = _parse_command_argv(
        wsl_peer_command,
        option_name="--wsl-peer-command",
        posix=True,
    )
    return RuntimePreferences(
        windows_peer_command_argv=(
            windows_peer_command_argv
            if windows_peer_command is not None
            else current.windows_peer_command_argv
        ),
        wsl_peer_command_argv=(
            wsl_peer_command_argv if wsl_peer_command is not None else current.wsl_peer_command_argv
        ),
        wsl_distro=wsl_distro if wsl_distro is not None else current.wsl_distro,
    )


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _load_and_build(
    runner: CommandRunner, direction: SyncDirection
) -> tuple[DirectionConfig, Path, WdsyncConfig]:
    config, repo_root, sdir = load_wdsync_config_with_paths(runner)
    attach_file_logging(sdir)
    dconfig = build_direction_from_wdsync_config(config, direction, repo_root, runner)
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
    ensure_local_rsync_available(detect_environment(), runner)
    with _peer_session_for(dconfig) as peer_session:
        ctx = build_sync_context(dconfig, runner, sdir, peer_session=peer_session)

        if ctx.conflicts and not force:
            for c in ctx.conflicts:
                log.error(
                    f"Conflict: {c.path!r} modified on both sides "
                    f"(source: {c.source_xy}, dest: {c.dest_xy})"
                )
            log.error(f"{len(ctx.conflicts)} conflict(s) detected. Use --force to override.")
            return
        if ctx.conflicts and force:
            for c in ctx.conflicts:
                log.warning(f"Forcing sync of conflicting file: {c.path!r}")

        plan = build_sync_plan(dconfig, ctx.source_state)

        source_deleted_paths = frozenset(
            entry.path for entry in ctx.source_state.entries if entry.kind is StatusKind.DELETED
        )
        restore_candidates = ctx.destination_state.wt_deleted_paths - source_deleted_paths
        if restore_candidates:
            plan = replace(plan, restore_paths=tuple(sorted(restore_candidates)))

        if ctx.orphaned_paths:
            plan = replace(plan, delete_paths=plan.delete_paths + tuple(sorted(ctx.orphaned_paths)))

        def _confirm_sudo(rel_path: str) -> bool:
            return typer.confirm(
                f"  Permission denied on {rel_path!r}. Retry with sudo?",
                default=False,
            )

        result = _execute_plan(
            plan,
            dconfig,
            ctx.destination_state.dirty_paths,
            runner,
            confirm_sudo=_confirm_sudo,
            peer_session=peer_session,
        )

        current_untracked = frozenset(
            entry.path for entry in ctx.source_state.entries if entry.kind is StatusKind.NEW
        )
        write_manifest(sdir, current_untracked)

        if as_json:
            typer.echo(render_json(sync_to_json(result)))
        else:
            log.info(format_sync_result(result))


def _execute_plan(
    plan: SyncPlan,
    dconfig: DirectionConfig,
    dest_dirty_paths: frozenset[str],
    runner: CommandRunner,
    *,
    confirm_sudo: Callable[[str], bool],
    peer_session: PeerSession | None,
) -> SyncResult:
    if dconfig.destination_is_local:
        return execute_sync(
            plan,
            runner,
            dest_dirty_paths=dest_dirty_paths,
            confirm_sudo=confirm_sudo,
            dest_git_cmd=dconfig.destination_git.command_argv,
            dest_root_native=dconfig.dest_root_native,
            rsync_cmd=dconfig.transfer.command_argv,
            rsync_source_root=dconfig.transfer.source_root,
            rsync_dest_root=dconfig.transfer.dest_root,
        )
    if peer_session is None:
        raise WdSyncError("wdsync: peer session is required for remote destination sync")

    restore_result = peer_session.restore(plan.restore_paths)
    delete_outcomes = peer_session.delete(plan.delete_paths)
    result_plan = _merge_remote_warnings(plan, delete_outcomes, restore_result)
    performed_copy = copy_files(
        result_plan,
        runner,
        rsync_cmd=dconfig.transfer.command_argv,
        rsync_source_root=dconfig.transfer.source_root,
        rsync_dest_root=dconfig.transfer.dest_root,
    )
    return SyncResult(
        plan=result_plan,
        copied_count=len(result_plan.copy_paths) if performed_copy else 0,
        deleted_count=sum(1 for outcome in delete_outcomes if outcome.deleted),
        skipped_count=len(result_plan.skipped_paths),
        performed_copy=performed_copy,
        restored_count=restore_result.restored_count,
    )


def _merge_remote_warnings(
    plan: SyncPlan,
    delete_outcomes: tuple[DeleteOutcome, ...],
    restore_result: RestoreResult,
) -> SyncPlan:
    extra_warnings = list(plan.warnings)
    extra_warnings.extend(restore_result.warnings)
    for outcome in delete_outcomes:
        if outcome.skipped and outcome.skip_reason == "dest-modified":
            extra_warnings.append(
                f"warning: {outcome.path!r} has local changes in dest — skipping deletion"
            )
        elif (
            outcome.skipped
            and outcome.skip_reason is not None
            and outcome.skip_reason not in {"absent", "dest-modified"}
        ):
            extra_warnings.append(
                f"warning: could not delete {outcome.path!r} ({outcome.skip_reason})"
            )
    if not extra_warnings:
        return plan
    return replace(plan, warnings=tuple(extra_warnings))


def _peer_config_for_direction(dconfig: DirectionConfig) -> PeerConfig:
    if not dconfig.peer_command_argv:
        raise WdSyncError("wdsync: not connected to a peer. Run 'wdsync connect' first.")
    endpoint = dconfig.source if not dconfig.source_is_local else dconfig.destination
    return PeerConfig(
        command_argv=dconfig.peer_command_argv,
        root=endpoint.root,
        root_native=endpoint.native_root,
    )


def _peer_session_for(dconfig: DirectionConfig) -> PeerSession:
    return PeerSession(_peer_config_for_direction(dconfig))


def _version_callback(value: bool) -> None:
    if value:
        from wdsync import __version__

        typer.echo(f"wdsync {__version__}", err=True)
        raise typer.Exit()


@app.callback()
def root(
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable verbose debug logging."),
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = None,
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

    identity = result.identity
    headline = (
        f"wdsync already initialized in {result.repo_root}"
        if result.already_initialized
        else f"Initialized wdsync in {result.repo_root}"
    )
    lines = [
        headline,
        f"  config: {result.config_path}",
        f"  marker: {result.marker_path}",
    ]
    if identity.remote_url:
        lines.append(f"  identity remote: {identity.remote_url}")
    if identity.root_commits:
        lines.append(f"  identity roots: {', '.join(identity.root_commits)}")
    log.info("\n".join(lines))


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
        with _peer_session_for(dconfig) as peer_session:
            ctx = build_sync_context(dconfig, runner, sdir, peer_session=peer_session)

            if as_json:
                typer.echo(
                    render_json(
                        status_to_json(
                            direction=direction,
                            source_state=ctx.source_state,
                            destination_state=ctx.destination_state,
                            conflicts=ctx.conflicts,
                            head_relation=ctx.doctor_report.head_relation.value,
                            risk_level=ctx.doctor_report.risk_level.value,
                            orphaned_count=len(ctx.orphaned_paths),
                        )
                    )
                )
            else:
                log.info(
                    format_status(
                        direction=direction,
                        source_state=ctx.source_state,
                        destination_state=ctx.destination_state,
                        conflicts=ctx.conflicts,
                        head_relation=ctx.doctor_report.head_relation.value,
                        risk_level=ctx.doctor_report.risk_level.value,
                        orphaned_count=len(ctx.orphaned_paths),
                    )
                )
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def connect(
    wsl_distro: Annotated[
        str | None,
        typer.Option(
            "--wsl-distro",
            help="Override the WSL distro used when Windows starts the peer.",
        ),
    ] = None,
    windows_peer_command: Annotated[
        str | None,
        typer.Option(
            "--windows-peer-command",
            help="Command used from WSL to start the Windows peer.",
        ),
    ] = None,
    wsl_peer_command: Annotated[
        str | None,
        typer.Option(
            "--wsl-peer-command",
            help="Command used from Windows to start the WSL peer.",
        ),
    ] = None,
) -> None:
    """Connect to a peer wdsync instance on the other side (WSL/Windows)."""
    runner = build_runner()
    try:
        config, repo_root, sdir = load_wdsync_config_with_paths(runner)
        attach_file_logging(sdir)

        runtime = _runtime_from_options(
            config.runtime,
            wsl_distro=wsl_distro,
            windows_peer_command=windows_peer_command,
            wsl_peer_command=wsl_peer_command,
        )
        config = replace(config, runtime=runtime)

        if config.peer is not None and not typer.confirm(
            f"Already connected to {config.peer.root}. Reconnect?", default=False
        ):
            return

        result = connect_to_peer(config, repo_root, runner, sdir)
        log.info(
            f"Connected to peer at {result.peer.root}\n"
            f"  matched by:  {result.matched_by}\n"
            f"  native path: {result.peer.root_native}"
        )
    except WdSyncError as error:
        _exit_with_error(error)


@app.command()
def disconnect() -> None:
    """Remove the peer connection from wdsync config."""
    runner = build_runner()
    try:
        config, _, sdir = load_wdsync_config_with_paths(runner)
        if config.peer is None:
            log.info("No peer configured; nothing to disconnect.")
            return
        updated = replace(config, peer=None)
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

    log.info(f"Installed {result.shell} shell assets:")
    for path in result.installed_paths:
        log.info(f"  {path}")
    for note in result.notes:
        log.info(f"  note: {note}")


@app.command(hidden=True)
def rpc() -> None:
    """Hidden RPC mode for cross-platform communication."""
    configure_logging(debug=False)
    runner = build_runner()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        response = _dispatch_rpc(line, runner)
        sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
        sys.stdout.flush()


def _dispatch_rpc(line: str, runner: CommandRunner) -> dict[str, object]:
    try:
        parsed: object = json.loads(line)
    except json.JSONDecodeError:
        return cast(dict[str, object], build_error_response("invalid JSON request"))

    if not isinstance(parsed, dict):
        return cast(dict[str, object], build_error_response("invalid RPC request object"))

    request = cast(dict[str, object], parsed)
    return cast(dict[str, object], handle_rpc_request(request, runner))


def main() -> None:
    app()

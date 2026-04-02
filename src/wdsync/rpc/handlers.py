from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from wdsync.core.codec import (
    protocol_identity_from_object,
    protocol_peer_from_object,
)
from wdsync.core.config import (
    initialize_repo,
    load_wdsync_config_with_paths,
    resolve_identity,
    save_wdsync_config,
)
from wdsync.core.environment import detect_environment
from wdsync.core.exceptions import MissingConfigError, WdSyncError
from wdsync.core.interop import (
    ensure_local_rsync_available,
    local_git_command,
    runtime_with_configured_peer_command,
)
from wdsync.core.models import DestinationState, Identity, PeerConfig, SyncPlan, WdsyncConfig
from wdsync.core.protocol import (
    PROTOCOL_VERSION,
    RpcMethod,
    RpcResponse,
    build_compare_heads_response,
    build_configure_peer_response,
    build_delete_response,
    build_error_response,
    build_handshake_response,
    build_locate_repo_response,
    build_restore_response,
    build_status_response,
)
from wdsync.core.runner import CommandRunner
from wdsync.git.dest import read_repo_destination_state
from wdsync.rpc.discovery import locate_matching_repo
from wdsync.sync.deleter import delete_files
from wdsync.sync.doctor import determine_head_relation_from_command
from wdsync.sync.engine import restore_files


def handle_rpc_request(request: dict[str, object], runner: CommandRunner) -> RpcResponse:
    """Dispatch an RPC request to the appropriate handler."""
    version = request.get("version")
    if version != PROTOCOL_VERSION:
        return build_error_response(f"unsupported protocol version: {version}")

    method = request.get("method")
    if method == RpcMethod.HANDSHAKE:
        return _handle_handshake()
    if method == RpcMethod.LOCATE_REPO:
        return _handle_locate_repo(request, runner)
    if method == RpcMethod.CONFIGURE_PEER:
        return _handle_configure_peer(request, runner)
    if method == RpcMethod.STATUS:
        return _handle_status(request, runner)
    if method == RpcMethod.DELETE:
        return _handle_delete(request, runner)
    if method == RpcMethod.RESTORE:
        return _handle_restore(request, runner)
    if method == RpcMethod.COMPARE_HEADS:
        return _handle_compare_heads(request, runner)
    return build_error_response(f"unknown method: {method}")


def _handle_handshake() -> RpcResponse:
    """Protocol/version/capabilities only — no identity or repo resolution."""
    return build_handshake_response()


def _handle_locate_repo(request: dict[str, object], runner: CommandRunner) -> RpcResponse:
    """Discover a local repo matching the caller's identity."""
    try:
        peer_identity, cached_root = _parse_locate_args(request)
        result = locate_matching_repo(peer_identity, runner, cached_root=cached_root)
        if result is None:
            return build_error_response(
                "no matching repository found — run 'wdsync init' on this side first"
            )
        repo_root, matched_by = result
        local_identity = resolve_identity(repo_root, runner)
        return build_locate_repo_response(
            identity=local_identity,
            repo_root=str(repo_root),
            repo_root_native=str(repo_root),
            matched_by=matched_by,
        )
    except WdSyncError as exc:
        return build_error_response(str(exc))


def _handle_configure_peer(request: dict[str, object], runner: CommandRunner) -> RpcResponse:
    try:
        repo_root, peer, allow_initialize = _parse_configure_peer_args(request)
        local_env = detect_environment()
        ensure_local_rsync_available(local_env, runner)
        try:
            config, _, sdir = load_wdsync_config_with_paths(runner, cwd=repo_root)
        except MissingConfigError as exc:
            if not allow_initialize:
                raise WdSyncError("wdsync: peer repo is not initialized") from exc
            initialize_repo(runner, cwd=repo_root)
            config, _, sdir = load_wdsync_config_with_paths(
                runner,
                cwd=repo_root,
            )
        updated = WdsyncConfig(
            version=config.version,
            identity=config.identity,
            peer=peer,
            runtime=runtime_with_configured_peer_command(
                local_env,
                config.runtime,
                peer.command_argv,
            ),
        )
        save_wdsync_config(updated, sdir)
        return build_configure_peer_response()
    except WdSyncError as exc:
        return build_error_response(str(exc))


def _handle_status(request: dict[str, object], runner: CommandRunner) -> RpcResponse:
    try:
        repo_root = _parse_repo_root_arg(request, method_name="status")
        state = _read_local_repo_status(repo_root, runner)
        return build_status_response(state)
    except WdSyncError as exc:
        return build_error_response(str(exc))


def _handle_delete(request: dict[str, object], runner: CommandRunner) -> RpcResponse:
    try:
        repo_root, paths = _parse_repo_paths_args(request, method_name="delete")
        state = _read_local_repo_status(repo_root, runner)
        outcomes = delete_files(
            SyncPlan(
                source_root=repo_root,
                dest_root=repo_root,
                preview_rows=(),
                copy_paths=(),
                delete_paths=paths,
                skipped_paths=(),
                warnings=(),
            ),
            state.dirty_paths,
            confirm_sudo=lambda _: False,
        )
        return build_delete_response(outcomes)
    except WdSyncError as exc:
        return build_error_response(str(exc))


def _handle_restore(request: dict[str, object], runner: CommandRunner) -> RpcResponse:
    try:
        repo_root, paths = _parse_repo_paths_args(request, method_name="restore")
        git_cmd = local_git_command(detect_environment())
        result = restore_files(paths, runner, dest_git_cmd=git_cmd, dest_root_native=str(repo_root))
        return build_restore_response(result)
    except WdSyncError as exc:
        return build_error_response(str(exc))


def _handle_compare_heads(request: dict[str, object], runner: CommandRunner) -> RpcResponse:
    try:
        repo_root = _parse_repo_root_arg(request, method_name="compare_heads")
        source_head, destination_head = _parse_compare_heads_args(request)
        command = [*local_git_command(detect_environment()), "-C", str(repo_root)]
        relation = determine_head_relation_from_command(
            command,
            source_head,
            destination_head,
            runner,
        )
        return build_compare_heads_response(
            relation=(relation.value if relation is not None else "different")
        )
    except WdSyncError as exc:
        return build_error_response(str(exc))


def _parse_locate_args(request: dict[str, object]) -> tuple[Identity, Path | None]:
    """Extract identity and optional cached_root from a locate_repo request."""
    raw_args: object = request.get("args", {})
    if not isinstance(raw_args, dict):
        raw_args = {}
    args = cast(dict[str, Any], raw_args)

    raw_identity: object = args.get("identity", {})
    identity = protocol_identity_from_object(raw_identity)

    raw_cached: object = args.get("cached_root")
    cached_root = Path(str(raw_cached)) if isinstance(raw_cached, str) else None

    return identity, cached_root


def _parse_configure_peer_args(request: dict[str, object]) -> tuple[Path, PeerConfig, bool]:
    raw_args: object = request.get("args", {})
    if not isinstance(raw_args, dict):
        raise WdSyncError("wdsync: configure_peer requires args")
    args = cast(dict[str, Any], raw_args)

    raw_repo_root: object = args.get("repo_root_native")
    if not isinstance(raw_repo_root, str) or not raw_repo_root:
        raise WdSyncError("wdsync: configure_peer requires repo_root_native")
    repo_root = Path(raw_repo_root)

    raw_peer: object = args.get("peer")
    peer = protocol_peer_from_object(raw_peer)

    raw_allow_initialize: object = args.get("allow_initialize", False)
    allow_initialize = raw_allow_initialize is True

    return repo_root, peer, allow_initialize


def _parse_repo_root_arg(request: dict[str, object], *, method_name: str) -> Path:
    raw_args: object = request.get("args", {})
    if not isinstance(raw_args, dict):
        raise WdSyncError(f"wdsync: {method_name} requires args")
    args = cast(dict[str, Any], raw_args)
    raw_repo_root: object = args.get("repo_root_native")
    if not isinstance(raw_repo_root, str) or not raw_repo_root:
        raise WdSyncError(f"wdsync: {method_name} requires repo_root_native")
    return Path(raw_repo_root)


def _parse_repo_paths_args(
    request: dict[str, object],
    *,
    method_name: str,
) -> tuple[Path, tuple[str, ...]]:
    repo_root = _parse_repo_root_arg(request, method_name=method_name)
    raw_args = cast(dict[str, Any], request.get("args", {}))
    raw_paths: object = raw_args.get("paths", [])
    if not isinstance(raw_paths, list):
        raise WdSyncError(f"wdsync: {method_name} requires paths")
    paths: list[str] = []
    for raw_path in cast(list[object], raw_paths):
        if not isinstance(raw_path, str) or not raw_path:
            raise WdSyncError(f"wdsync: {method_name} paths must be non-empty strings")
        paths.append(raw_path)
    return repo_root, tuple(paths)


def _parse_compare_heads_args(request: dict[str, object]) -> tuple[str, str]:
    raw_args: object = request.get("args", {})
    if not isinstance(raw_args, dict):
        raise WdSyncError("wdsync: compare_heads requires args")
    args = cast(dict[str, Any], raw_args)
    raw_source_head = args.get("source_head")
    raw_destination_head = args.get("destination_head")
    if not isinstance(raw_source_head, str) or not raw_source_head:
        raise WdSyncError("wdsync: compare_heads requires source_head")
    if not isinstance(raw_destination_head, str) or not raw_destination_head:
        raise WdSyncError("wdsync: compare_heads requires destination_head")
    return raw_source_head, raw_destination_head


def _read_local_repo_status(repo_root: Path, runner: CommandRunner) -> DestinationState:
    command = [*local_git_command(detect_environment()), "-C", str(repo_root)]
    return read_repo_destination_state(command, runner)

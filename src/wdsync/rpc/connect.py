from __future__ import annotations

from pathlib import Path

from wdsync.core.codec import identity_from_object
from wdsync.core.config import match_identity, save_wdsync_config
from wdsync.core.environment import detect_environment
from wdsync.core.exceptions import (
    ConfigValidationError,
    IdentityMismatchError,
    PeerConnectionError,
)
from wdsync.core.interop import (
    current_wsl_distro,
    ensure_local_rsync_available,
    local_path_for_peer_string,
    peer_native_to_local_path,
    resolve_peer_command_for_environment,
    resolve_reverse_peer_command_for_environment,
    runtime_with_resolved_peer_command,
)
from wdsync.core.models import ConnectResult, Identity, PeerConfig, WdsyncConfig
from wdsync.core.protocol import (
    HANDSHAKE_CAPABILITIES,
    PROTOCOL_VERSION,
    RpcResponse,
    build_configure_peer_request,
    build_handshake_request,
    build_locate_repo_request,
)
from wdsync.core.runner import CommandRunner
from wdsync.rpc.client import RpcClient
from wdsync.rpc.session import capabilities_from_object


def connect_to_peer(
    config: WdsyncConfig,
    repo_root: Path,
    runner: CommandRunner,
    sdir: Path,
) -> ConnectResult:
    """Spawn a peer process, handshake, configure both sides, and save config."""
    local_env = detect_environment()
    ensure_local_rsync_available(local_env, runner)
    local_distro = current_wsl_distro()
    resolved_peer = resolve_peer_command_for_environment(
        local_env,
        config.runtime,
        runner,
        local_wsl_distro=local_distro,
    )
    peer_argv = resolved_peer.spawn_argv

    cached_root_native = config.peer.root_native if config.peer is not None else None

    with RpcClient(peer_argv) as client:
        handshake_resp = client.send(build_handshake_request())
        _validate_handshake(handshake_resp)

        locate_resp = client.send(
            build_locate_repo_request(config.identity, cached_root=cached_root_native)
        )
        peer_identity = _extract_peer_identity(locate_resp)
        repo_root_native = str(locate_resp["data"].get("repo_root_native", ""))
        peer = PeerConfig(
            command_argv=peer_argv,
            root=peer_native_to_local_path(local_env, repo_root_native, runner),
            root_native=repo_root_native,
        )

        match_result = match_identity(config.identity, peer_identity)
        if match_result is None:
            raise IdentityMismatchError(
                "wdsync: peer repo does not match local identity. "
                "Ensure both repos track the same project."
            )

        reverse_peer = PeerConfig(
            command_argv=resolve_reverse_peer_command_for_environment(
                local_env,
                config.runtime,
                runner,
                local_wsl_distro=local_distro,
            ),
            root=repo_root,
            root_native=str(repo_root),
        )
        client.send(
            build_configure_peer_request(
                repo_root_native=repo_root_native,
                peer_command_argv=reverse_peer.command_argv,
                peer_root=local_path_for_peer_string(local_env, repo_root, runner),
                peer_root_native=reverse_peer.root_native,
                allow_initialize=True,
            )
        )

    updated_runtime = runtime_with_resolved_peer_command(
        local_env,
        config.runtime,
        resolved_peer.stored_argv,
    )
    updated = WdsyncConfig(
        version=config.version,
        identity=config.identity,
        peer=peer,
        runtime=updated_runtime,
    )
    save_wdsync_config(updated, sdir)
    return ConnectResult(matched_by=match_result, peer=peer)


def _validate_handshake(response: RpcResponse) -> None:
    data = response["data"]
    peer_version: object = data.get("protocol_version")
    if peer_version != PROTOCOL_VERSION:
        raise PeerConnectionError(
            f"wdsync: peer protocol version mismatch "
            f"(local={PROTOCOL_VERSION}, peer={peer_version})"
        )
    capabilities = capabilities_from_object(data.get("capabilities", []))
    required = frozenset(HANDSHAKE_CAPABILITIES)
    missing = sorted(capability for capability in required if capability not in capabilities)
    if missing:
        missing_display = ", ".join(missing)
        raise PeerConnectionError(
            f"wdsync: peer is missing required RPC capabilities: {missing_display}"
        )


def _extract_peer_identity(response: RpcResponse) -> Identity:
    data = response["data"]
    raw_identity: object = data.get("identity", {})
    try:
        return identity_from_object(raw_identity, context="RPC response")
    except ConfigValidationError as exc:
        raise PeerConnectionError(
            "wdsync: peer identity missing from locate_repo response"
        ) from exc

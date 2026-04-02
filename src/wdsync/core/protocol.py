from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from wdsync.core.codec import (
    delete_outcomes_to_dict,
    destination_state_to_dict,
    identity_to_dict,
    manifest_to_dict,
    restore_result_to_dict,
)
from wdsync.core.models import DeleteOutcome, DestinationState, Identity, RestoreResult

PROTOCOL_VERSION = 1


class RpcMethod(StrEnum):
    HANDSHAKE = "handshake"
    LOCATE_REPO = "locate_repo"
    CONFIGURE_PEER = "configure_peer"
    STATUS = "status"
    READ_MANIFEST = "read_manifest"
    WRITE_MANIFEST = "write_manifest"
    DELETE = "delete"
    RESTORE = "restore"
    COMPARE_HEADS = "compare_heads"


class RpcRequest(TypedDict):
    version: int
    method: str
    args: dict[str, object]


class RpcResponse(TypedDict):
    version: int
    ok: bool
    data: dict[str, object]
    error: str | None


HANDSHAKE_CAPABILITIES: tuple[RpcMethod, ...] = (
    RpcMethod.LOCATE_REPO,
    RpcMethod.CONFIGURE_PEER,
    RpcMethod.STATUS,
    RpcMethod.READ_MANIFEST,
    RpcMethod.WRITE_MANIFEST,
    RpcMethod.DELETE,
    RpcMethod.RESTORE,
    RpcMethod.COMPARE_HEADS,
)


def build_handshake_request() -> RpcRequest:
    """Protocol negotiation only — no identity or repo state."""
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.HANDSHAKE,
        "args": {},
    }


def build_handshake_response() -> RpcResponse:
    """Protocol version + capabilities. No identity or repo resolution."""
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {
            "protocol_version": PROTOCOL_VERSION,
            "capabilities": list(HANDSHAKE_CAPABILITIES),
        },
        "error": None,
    }


def build_locate_repo_request(
    identity: Identity,
    *,
    cached_root: str | None = None,
) -> RpcRequest:
    args: dict[str, object] = {"identity": identity_to_dict(identity)}
    if cached_root is not None:
        args["cached_root"] = cached_root
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.LOCATE_REPO,
        "args": args,
    }


def build_locate_repo_response(
    identity: Identity,
    repo_root: str,
    repo_root_native: str,
    matched_by: str,
) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {
            "identity": identity_to_dict(identity),
            "repo_root": repo_root,
            "repo_root_native": repo_root_native,
            "matched_by": matched_by,
        },
        "error": None,
    }


def build_configure_peer_request(
    *,
    repo_root_native: str,
    peer_command_argv: tuple[str, ...],
    peer_root: str,
    peer_root_native: str,
    allow_initialize: bool,
) -> RpcRequest:
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.CONFIGURE_PEER,
        "args": {
            "repo_root_native": repo_root_native,
            "peer": {
                "command_argv": list(peer_command_argv),
                "root": peer_root,
                "root_native": peer_root_native,
            },
            "allow_initialize": allow_initialize,
        },
    }


def build_configure_peer_response() -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {"configured": True},
        "error": None,
    }


def build_status_request(*, repo_root_native: str) -> RpcRequest:
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.STATUS,
        "args": {"repo_root_native": repo_root_native},
    }


def build_status_response(state: DestinationState) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": destination_state_to_dict(state),
        "error": None,
    }


def build_read_manifest_request(*, repo_root_native: str) -> RpcRequest:
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.READ_MANIFEST,
        "args": {"repo_root_native": repo_root_native},
    }


def build_read_manifest_response(mirrored_paths: frozenset[str]) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": manifest_to_dict(mirrored_paths),
        "error": None,
    }


def build_write_manifest_request(
    *,
    repo_root_native: str,
    mirrored_paths: frozenset[str],
) -> RpcRequest:
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.WRITE_MANIFEST,
        "args": {
            "repo_root_native": repo_root_native,
            "paths": sorted(mirrored_paths),
        },
    }


def build_write_manifest_response() -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {"saved": True},
        "error": None,
    }


def build_delete_request(*, repo_root_native: str, paths: tuple[str, ...]) -> RpcRequest:
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.DELETE,
        "args": {
            "repo_root_native": repo_root_native,
            "paths": list(paths),
        },
    }


def build_delete_response(outcomes: tuple[DeleteOutcome, ...]) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": delete_outcomes_to_dict(outcomes),
        "error": None,
    }


def build_restore_request(*, repo_root_native: str, paths: tuple[str, ...]) -> RpcRequest:
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.RESTORE,
        "args": {
            "repo_root_native": repo_root_native,
            "paths": list(paths),
        },
    }


def build_restore_response(result: RestoreResult) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": restore_result_to_dict(result),
        "error": None,
    }


def build_compare_heads_request(
    *,
    repo_root_native: str,
    source_head: str,
    destination_head: str,
) -> RpcRequest:
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.COMPARE_HEADS,
        "args": {
            "repo_root_native": repo_root_native,
            "source_head": source_head,
            "destination_head": destination_head,
        },
    }


def build_compare_heads_response(*, relation: str) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {"relation": relation},
        "error": None,
    }


def build_error_response(error: str) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": False,
        "data": {},
        "error": error,
    }

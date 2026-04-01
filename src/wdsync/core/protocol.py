from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TypedDict

PROTOCOL_VERSION = 1


class RpcMethod(StrEnum):
    HANDSHAKE = "handshake"
    LOCATE_REPO = "locate_repo"
    STATUS = "status"
    SYNC = "sync"
    DELETE = "delete"
    RESTORE = "restore"


class RpcRequest(TypedDict):
    version: int
    method: str
    args: dict[str, object]


class RpcResponse(TypedDict):
    version: int
    ok: bool
    data: dict[str, object]
    error: str | None


def build_handshake_request(
    identity_dict: Mapping[str, object],
) -> RpcRequest:
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.HANDSHAKE,
        "args": {"identity": identity_dict},
    }


def build_handshake_response(
    identity_dict: Mapping[str, object],
    repo_root: str,
    repo_root_native: str,
) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {
            "protocol_version": PROTOCOL_VERSION,
            "identity": identity_dict,
            "repo_root": repo_root,
            "repo_root_native": repo_root_native,
        },
        "error": None,
    }


def build_locate_repo_request(identity_dict: dict[str, object]) -> RpcRequest:
    return {
        "version": PROTOCOL_VERSION,
        "method": RpcMethod.LOCATE_REPO,
        "args": {"identity": identity_dict},
    }


def build_locate_repo_response(
    repo_root: str,
    repo_root_native: str,
    matched_by: str,
) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": True,
        "data": {
            "repo_root": repo_root,
            "repo_root_native": repo_root_native,
            "matched_by": matched_by,
        },
        "error": None,
    }


def build_error_response(error: str) -> RpcResponse:
    return {
        "version": PROTOCOL_VERSION,
        "ok": False,
        "data": {},
        "error": error,
    }

from __future__ import annotations

from wdsync.core.protocol import (
    PROTOCOL_VERSION,
    RpcMethod,
    build_error_response,
    build_handshake_request,
    build_handshake_response,
    build_locate_repo_request,
    build_locate_repo_response,
)


def test_build_handshake_request_includes_identity() -> None:
    identity: dict[str, object] = {
        "remote_url": "https://github.com/user/repo",
        "root_commits": ["abc"],
    }
    req = build_handshake_request(identity)

    assert req["version"] == PROTOCOL_VERSION
    assert req["method"] == RpcMethod.HANDSHAKE
    assert req["args"]["identity"] == identity


def test_build_handshake_response_includes_identity_and_roots() -> None:
    identity: dict[str, object] = {
        "remote_url": "https://github.com/user/repo",
        "root_commits": ["abc"],
    }
    resp = build_handshake_response(identity, "/home/user/repo", "/home/user/repo")

    assert resp["version"] == PROTOCOL_VERSION
    assert resp["ok"] is True
    assert resp["error"] is None
    assert resp["data"]["identity"] == identity
    assert resp["data"]["repo_root"] == "/home/user/repo"


def test_build_locate_repo_request() -> None:
    identity: dict[str, object] = {"remote_url": None, "root_commits": ["abc"]}
    req = build_locate_repo_request(identity)

    assert req["method"] == RpcMethod.LOCATE_REPO
    assert req["args"]["identity"] == identity


def test_build_locate_repo_response() -> None:
    resp = build_locate_repo_response(
        repo_root="/mnt/c/Users/user/repo",
        repo_root_native="C:\\Users\\user\\repo",
        matched_by="root_commits",
    )

    assert resp["ok"] is True
    assert resp["data"]["repo_root"] == "/mnt/c/Users/user/repo"
    assert resp["data"]["matched_by"] == "root_commits"


def test_build_error_response() -> None:
    resp = build_error_response("something went wrong")

    assert resp["version"] == PROTOCOL_VERSION
    assert resp["ok"] is False
    assert resp["error"] == "something went wrong"
    assert resp["data"] == {}


def test_rpc_method_enum_values() -> None:
    assert RpcMethod.HANDSHAKE == "handshake"
    assert RpcMethod.LOCATE_REPO == "locate_repo"
    assert RpcMethod.STATUS == "status"
    assert RpcMethod.SYNC == "sync"

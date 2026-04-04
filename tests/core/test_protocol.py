from __future__ import annotations

from wdsync.core.models import DestinationState, Identity, PathFingerprint, RestoreResult
from wdsync.core.protocol import (
    HANDSHAKE_CAPABILITIES,
    PROTOCOL_VERSION,
    RpcMethod,
    build_configure_peer_request,
    build_configure_peer_response,
    build_delete_request,
    build_delete_response,
    build_error_response,
    build_fingerprint_paths_request,
    build_fingerprint_paths_response,
    build_handshake_request,
    build_handshake_response,
    build_locate_repo_request,
    build_locate_repo_response,
    build_read_manifest_request,
    build_read_manifest_response,
    build_restore_request,
    build_restore_response,
    build_status_request,
    build_status_response,
    build_write_manifest_request,
    build_write_manifest_response,
)


def test_build_handshake_request_is_protocol_only() -> None:
    req = build_handshake_request()

    assert req["version"] == PROTOCOL_VERSION
    assert req["method"] == RpcMethod.HANDSHAKE
    assert req["args"] == {}


def test_build_handshake_response_returns_version_and_capabilities() -> None:
    resp = build_handshake_response()

    assert resp["version"] == PROTOCOL_VERSION
    assert resp["ok"] is True
    assert resp["error"] is None
    assert resp["data"]["protocol_version"] == PROTOCOL_VERSION
    assert resp["data"]["capabilities"] == list(HANDSHAKE_CAPABILITIES)


def test_build_locate_repo_request_with_identity() -> None:
    identity = Identity(remote_url=None, root_commits=("abc",))
    req = build_locate_repo_request(identity)

    assert req["method"] == RpcMethod.LOCATE_REPO
    assert req["args"]["identity"] == {"remote_url": None, "root_commits": ["abc"]}
    assert "cached_root" not in req["args"]


def test_build_locate_repo_request_with_cached_root() -> None:
    identity = Identity(remote_url=None, root_commits=("abc",))
    req = build_locate_repo_request(identity, cached_root="C:\\Users\\user\\repo")

    assert req["args"]["cached_root"] == "C:\\Users\\user\\repo"


def test_build_locate_repo_response_includes_identity() -> None:
    identity = Identity(
        remote_url="https://github.com/user/repo",
        root_commits=("abc",),
    )
    resp = build_locate_repo_response(
        identity=identity,
        repo_root="/mnt/c/Users/user/repo",
        repo_root_native="C:\\Users\\user\\repo",
        matched_by="root_commits",
    )

    assert resp["ok"] is True
    assert resp["data"]["identity"] == {
        "remote_url": "https://github.com/user/repo",
        "root_commits": ["abc"],
    }
    assert resp["data"]["repo_root"] == "/mnt/c/Users/user/repo"
    assert resp["data"]["repo_root_native"] == "C:\\Users\\user\\repo"
    assert resp["data"]["matched_by"] == "root_commits"


def test_build_configure_peer_request_and_response() -> None:
    req = build_configure_peer_request(
        repo_root_native="C:\\Users\\user\\repo",
        peer_command_argv=("wsl.exe", "--exec", "wdsync"),
        peer_root="//wsl.localhost/Ubuntu/home/user/repo",
        peer_root_native="/home/user/repo",
        allow_initialize=True,
    )
    resp = build_configure_peer_response()

    assert req["method"] == RpcMethod.CONFIGURE_PEER
    assert req["args"]["repo_root_native"] == "C:\\Users\\user\\repo"
    assert req["args"]["allow_initialize"] is True
    assert resp["ok"] is True
    assert resp["data"]["configured"] is True


def test_build_status_delete_and_restore_requests() -> None:
    status_req = build_status_request(repo_root_native="/repo")
    fingerprint_req = build_fingerprint_paths_request(
        repo_root_native="/repo",
        paths=("a.txt", "b.txt"),
    )
    read_manifest_req = build_read_manifest_request(repo_root_native="/repo")
    write_manifest_req = build_write_manifest_request(
        repo_root_native="/repo",
        mirrored_paths=frozenset({"a.txt"}),
    )
    delete_req = build_delete_request(repo_root_native="/repo", paths=("a.txt", "b.txt"))
    restore_req = build_restore_request(repo_root_native="/repo", paths=("a.txt",))

    assert status_req["method"] == RpcMethod.STATUS
    assert status_req["args"]["repo_root_native"] == "/repo"
    assert fingerprint_req["method"] == RpcMethod.FINGERPRINT_PATHS
    assert fingerprint_req["args"]["paths"] == ["a.txt", "b.txt"]
    assert read_manifest_req["method"] == RpcMethod.READ_MANIFEST
    assert read_manifest_req["args"]["repo_root_native"] == "/repo"
    assert write_manifest_req["method"] == RpcMethod.WRITE_MANIFEST
    assert write_manifest_req["args"]["paths"] == ["a.txt"]
    assert delete_req["method"] == RpcMethod.DELETE
    assert delete_req["args"]["paths"] == ["a.txt", "b.txt"]
    assert restore_req["method"] == RpcMethod.RESTORE
    assert restore_req["args"]["paths"] == ["a.txt"]


def test_build_status_delete_and_restore_responses() -> None:
    status_resp = build_status_response(
        state=DestinationState(
            head=None,
            modified_count=1,
            staged_count=2,
            untracked_count=3,
            dirty_paths=frozenset({"a.txt"}),
            wt_deleted_paths=frozenset({"b.txt"}),
            entries=(),
        )
    )
    read_manifest_resp = build_read_manifest_response(frozenset({"a.txt"}))
    fingerprint_resp = build_fingerprint_paths_response(
        (
            PathFingerprint(path="a.txt", object_id="abc123"),
            PathFingerprint(path="gone.txt", object_id=None),
        )
    )
    write_manifest_resp = build_write_manifest_response()
    delete_resp = build_delete_response(())
    restore_resp = build_restore_response(result=RestoreResult(restored_count=0, warnings=()))

    assert status_resp["data"]["modified_count"] == 1
    assert fingerprint_resp["data"]["fingerprints"] == [
        {"path": "a.txt", "object_id": "abc123"},
        {"path": "gone.txt", "object_id": None},
    ]
    assert read_manifest_resp["data"]["paths"] == ["a.txt"]
    assert write_manifest_resp["data"]["saved"] is True
    assert delete_resp["data"]["outcomes"] == []
    assert restore_resp["data"]["warnings"] == []


def test_build_error_response() -> None:
    resp = build_error_response("something went wrong")

    assert resp["version"] == PROTOCOL_VERSION
    assert resp["ok"] is False
    assert resp["error"] == "something went wrong"
    assert resp["data"] == {}


def test_rpc_method_enum_values() -> None:
    assert RpcMethod.HANDSHAKE == "handshake"
    assert RpcMethod.LOCATE_REPO == "locate_repo"
    assert RpcMethod.CONFIGURE_PEER == "configure_peer"
    assert RpcMethod.STATUS == "status"
    assert RpcMethod.FINGERPRINT_PATHS == "fingerprint_paths"
    assert RpcMethod.READ_MANIFEST == "read_manifest"
    assert RpcMethod.WRITE_MANIFEST == "write_manifest"
    assert RpcMethod.DELETE == "delete"
    assert RpcMethod.RESTORE == "restore"
    assert RpcMethod.COMPARE_HEADS == "compare_heads"

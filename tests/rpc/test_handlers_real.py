from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from wdsync.core.config import load_wdsync_config
from wdsync.core.models import PeerConfig
from wdsync.core.protocol import PROTOCOL_VERSION, RpcMethod
from wdsync.core.runner import CommandRunner
from wdsync.rpc.handlers import handle_rpc_request


def _request(method: str, *, args: dict[str, object]) -> dict[str, object]:
    return {"version": PROTOCOL_VERSION, "method": method, "args": args}


def _rev_parse(repo: Path, rev: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", rev],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_status_handler_reports_real_repo_state(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("repo", files={"tracked.txt": "base\n"})
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")
    (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "staged.txt"], check=True, capture_output=True)

    response = handle_rpc_request(
        _request(RpcMethod.STATUS, args={"repo_root_native": str(repo)}),
        git_runner,
    )

    assert response["ok"] is True
    assert response["data"]["modified_count"] == 1
    assert response["data"]["staged_count"] == 1
    assert response["data"]["untracked_count"] == 1


def test_fingerprint_handler_reports_git_normalized_worktree_content(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("repo", files={"tracked.txt": "base\n", "deleted.txt": "gone\n"})
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")
    (repo / "deleted.txt").unlink()

    response = handle_rpc_request(
        _request(
            RpcMethod.FINGERPRINT_PATHS,
            args={
                "repo_root_native": str(repo),
                "paths": ["tracked.txt", "untracked.txt", "deleted.txt"],
            },
        ),
        git_runner,
    )

    assert response["ok"] is True
    fingerprints = {item["path"]: item["object_id"] for item in response["data"]["fingerprints"]}  # type: ignore[index]
    assert fingerprints["tracked.txt"]
    assert fingerprints["untracked.txt"]
    assert fingerprints["deleted.txt"] is None


def test_delete_handler_deletes_clean_paths_and_skips_edge_cases(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory(
        "repo",
        files={"remove.txt": "remove\n", "dirty.txt": "dirty\n", "keep.txt": "keep\n"},
    )
    (repo / "dirty.txt").write_text("modified\n", encoding="utf-8")

    response = handle_rpc_request(
        _request(
            RpcMethod.DELETE,
            args={
                "repo_root_native": str(repo),
                "paths": ["remove.txt", "dirty.txt", "../escape.txt", "absent.txt"],
            },
        ),
        git_runner,
    )

    assert response["ok"] is True
    outcomes = {item["path"]: item for item in response["data"]["outcomes"]}  # type: ignore[index]
    assert outcomes["remove.txt"]["deleted"] is True
    assert outcomes["dirty.txt"]["skip_reason"] == "dest-modified"
    assert outcomes["../escape.txt"]["skip_reason"] == "path-traversal"
    assert outcomes["absent.txt"]["skip_reason"] == "absent"
    assert not (repo / "remove.txt").exists()


def test_manifest_handlers_roundtrip_real_state(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("repo", files={"tracked.txt": "base\n"})

    write_response = handle_rpc_request(
        _request(
            RpcMethod.WRITE_MANIFEST,
            args={"repo_root_native": str(repo), "paths": ["scratch.txt", "nested/new.txt"]},
        ),
        git_runner,
    )
    read_response = handle_rpc_request(
        _request(RpcMethod.READ_MANIFEST, args={"repo_root_native": str(repo)}),
        git_runner,
    )

    assert write_response["ok"] is True
    assert write_response["data"]["saved"] is True
    assert read_response["ok"] is True
    assert set(read_response["data"]["paths"]) == {"scratch.txt", "nested/new.txt"}  # type: ignore[index]


def test_restore_handler_restores_deleted_file_in_real_repo(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("repo", files={"tracked.txt": "base\n"})
    (repo / "tracked.txt").unlink()

    response = handle_rpc_request(
        _request(
            RpcMethod.RESTORE,
            args={"repo_root_native": str(repo), "paths": ["tracked.txt"]},
        ),
        git_runner,
    )

    assert response["ok"] is True
    assert response["data"]["restored_count"] == 1
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "base\n"


def test_compare_heads_handler_reports_source_ahead_on_real_history(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("repo", files={"tracked.txt": "base\n"})
    old_head = _rev_parse(repo, "HEAD")
    (repo / "tracked.txt").write_text("next\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "next"],
        check=True,
        capture_output=True,
    )
    new_head = _rev_parse(repo, "HEAD")

    response = handle_rpc_request(
        _request(
            RpcMethod.COMPARE_HEADS,
            args={
                "repo_root_native": str(repo),
                "source_head": new_head,
                "destination_head": old_head,
            },
        ),
        git_runner,
    )

    assert response["ok"] is True
    assert response["data"]["relation"] == "source-ahead"


def test_configure_peer_handler_auto_initializes_missing_repo(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("repo", files={"tracked.txt": "base\n"})

    response = handle_rpc_request(
        _request(
            RpcMethod.CONFIGURE_PEER,
            args={
                "repo_root_native": str(repo),
                "peer": {
                    "command_argv": ["wsl.exe", "--exec", "wdsync"],
                    "root": r"\\wsl.localhost\Ubuntu\home\user\repo",
                    "root_native": "/home/user/repo",
                },
                "allow_initialize": True,
            },
        ),
        git_runner,
    )

    assert response["ok"] is True
    loaded = load_wdsync_config(git_runner, cwd=repo)
    assert loaded.peer == PeerConfig(
        command_argv=("wsl.exe", "--exec", "wdsync"),
        root=Path(r"\\wsl.localhost\Ubuntu\home\user\repo"),
        root_native="/home/user/repo",
    )


def test_handlers_reject_malformed_rpc_arguments(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
) -> None:
    repo = repo_factory("repo", files={"tracked.txt": "base\n"})

    status_response = handle_rpc_request(
        _request(RpcMethod.STATUS, args={}),
        git_runner,
    )
    delete_response = handle_rpc_request(
        _request(
            RpcMethod.DELETE,
            args={"repo_root_native": str(repo), "paths": ["ok.txt", 3]},
        ),
        git_runner,
    )
    compare_response = handle_rpc_request(
        _request(RpcMethod.COMPARE_HEADS, args={"repo_root_native": str(repo), "source_head": ""}),
        git_runner,
    )
    manifest_response = handle_rpc_request(
        _request(
            RpcMethod.WRITE_MANIFEST,
            args={"repo_root_native": str(repo), "paths": "bad"},
        ),
        git_runner,
    )
    fingerprint_response = handle_rpc_request(
        _request(
            RpcMethod.FINGERPRINT_PATHS,
            args={"repo_root_native": str(repo), "paths": ["ok.txt", 3]},
        ),
        git_runner,
    )

    assert status_response["ok"] is False
    assert "repo_root_native" in (status_response["error"] or "")
    assert delete_response["ok"] is False
    assert "paths must be non-empty strings" in (delete_response["error"] or "")
    assert compare_response["ok"] is False
    assert "source_head" in (compare_response["error"] or "")
    assert manifest_response["ok"] is False
    assert "requires paths" in (manifest_response["error"] or "")
    assert fingerprint_response["ok"] is False
    assert "paths must be non-empty strings" in (fingerprint_response["error"] or "")

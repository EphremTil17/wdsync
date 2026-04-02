from __future__ import annotations

from pathlib import Path

import pytest

from wdsync.core.codec import (
    delete_outcomes_from_object,
    delete_outcomes_to_dict,
    destination_state_from_object,
    destination_state_to_dict,
    manifest_from_object,
    manifest_to_dict,
    protocol_identity_from_object,
    protocol_peer_from_object,
    restore_result_from_object,
    restore_result_to_dict,
    wdsync_config_from_object,
    wdsync_config_to_dict,
)
from wdsync.core.exceptions import ConfigValidationError, WdSyncError
from wdsync.core.models import (
    DeleteOutcome,
    DestinationState,
    Identity,
    PeerConfig,
    RestoreResult,
    RuntimePreferences,
    StatusKind,
    StatusRecord,
    WdsyncConfig,
)


def test_wdsync_config_roundtrip_preserves_peer_and_runtime() -> None:
    config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url="https://github.com/user/repo", root_commits=("abc", "def")),
        peer=PeerConfig(
            command_argv=("wsl.exe", "--exec", "wdsync"),
            root=Path(r"\\wsl.localhost\Ubuntu\home\user\repo"),
            root_native="/home/user/repo",
        ),
        runtime=RuntimePreferences(
            windows_peer_command_argv=("python.exe", "-m", "wdsync"),
            wsl_peer_command_argv=("python", "-m", "wdsync"),
            wsl_distro="Ubuntu-24.04",
        ),
    )

    loaded = wdsync_config_from_object(wdsync_config_to_dict(config))

    assert loaded == config


def test_destination_state_roundtrip_preserves_entries_and_counts() -> None:
    state = DestinationState(
        head="abc123",
        modified_count=2,
        staged_count=1,
        untracked_count=1,
        dirty_paths=frozenset({"dirty.txt", "gone.txt"}),
        wt_deleted_paths=frozenset({"gone.txt"}),
        entries=(
            StatusRecord(raw_xy=" M", path="dirty.txt", orig_path=None, kind=StatusKind.UNSTAGED),
            StatusRecord(raw_xy=" D", path="gone.txt", orig_path=None, kind=StatusKind.DELETED),
            StatusRecord(raw_xy="??", path="new.txt", orig_path=None, kind=StatusKind.NEW),
        ),
    )

    loaded = destination_state_from_object(destination_state_to_dict(state), context="roundtrip")

    assert loaded == state


def test_destination_state_from_object_rejects_bad_dirty_paths() -> None:
    with pytest.raises(ConfigValidationError, match="dirty_paths must be a list"):
        destination_state_from_object(
            {
                "head": "abc",
                "modified_count": 1,
                "staged_count": 0,
                "untracked_count": 0,
                "dirty_paths": "dirty.txt",
                "wt_deleted_paths": [],
                "entries": [],
            },
            context="rpc",
        )


def test_delete_outcomes_roundtrip_preserves_flags() -> None:
    outcomes = (
        DeleteOutcome(
            path="a.txt",
            deleted=True,
            skipped=False,
            skip_reason=None,
            used_sudo=False,
        ),
        DeleteOutcome(
            path="b.txt",
            deleted=False,
            skipped=True,
            skip_reason="dest-modified",
            used_sudo=False,
        ),
    )

    loaded = delete_outcomes_from_object(delete_outcomes_to_dict(outcomes), context="rpc")

    assert loaded == outcomes


def test_delete_outcomes_from_object_rejects_non_boolean_flags() -> None:
    with pytest.raises(ConfigValidationError, match="used_sudo must be a boolean"):
        delete_outcomes_from_object(
            {
                "outcomes": [
                    {
                        "path": "a.txt",
                        "deleted": True,
                        "skipped": False,
                        "skip_reason": None,
                        "used_sudo": "no",
                    }
                ]
            },
            context="rpc",
        )


def test_restore_result_from_object_rejects_non_list_warnings() -> None:
    with pytest.raises(ConfigValidationError, match="warnings must be a list"):
        restore_result_from_object(
            {"restored_count": 1, "warnings": "bad"},
            context="rpc",
        )


def test_restore_result_roundtrip_preserves_warnings() -> None:
    result = RestoreResult(restored_count=2, warnings=("warning one", "warning two"))

    loaded = restore_result_from_object(restore_result_to_dict(result), context="rpc")

    assert loaded == result


def test_manifest_roundtrip_preserves_untracked_paths() -> None:
    manifest = frozenset({"scratch.txt", "nested/new.txt"})

    loaded = manifest_from_object(manifest_to_dict(manifest), context="rpc")

    assert loaded == manifest


def test_manifest_from_object_rejects_non_list_untracked() -> None:
    with pytest.raises(ConfigValidationError, match="paths must be a list"):
        manifest_from_object({"paths": "scratch.txt"}, context="rpc")


def test_protocol_identity_from_object_wraps_validation_errors() -> None:
    with pytest.raises(WdSyncError, match="identity.root_commits must be a list"):
        protocol_identity_from_object({"remote_url": None, "root_commits": "abc"})


def test_protocol_peer_from_object_wraps_validation_errors() -> None:
    with pytest.raises(WdSyncError, match="peer.command_argv must contain only strings"):
        protocol_peer_from_object(
            {
                "command_argv": ["python", 3],
                "root": "/repo",
                "root_native": "/repo",
            }
        )


def test_wdsync_config_from_object_rejects_invalid_runtime_argv() -> None:
    with pytest.raises(
        ConfigValidationError,
        match="runtime.windows_peer_command_argv must contain only strings",
    ):
        wdsync_config_from_object(
            {
                "version": 1,
                "identity": {"remote_url": None, "root_commits": ["abc"]},
                "peer": None,
                "runtime": {"windows_peer_command_argv": ["python.exe", 3]},
            }
        )

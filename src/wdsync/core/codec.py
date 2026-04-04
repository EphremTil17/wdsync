from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from wdsync.core.exceptions import ConfigValidationError, WdSyncError
from wdsync.core.models import (
    DeleteOutcome,
    DestinationState,
    Identity,
    PathFingerprint,
    PeerConfig,
    RestoreResult,
    RuntimePreferences,
    StatusRecord,
    WdsyncConfig,
)
from wdsync.git.status_parser import classify_status


def identity_to_dict(identity: Identity) -> dict[str, object]:
    return {
        "remote_url": identity.remote_url,
        "root_commits": list(identity.root_commits),
    }


def identity_from_object(raw: object, *, context: str) -> Identity:
    if not isinstance(raw, dict):
        raise ConfigValidationError(f"wdsync: {context} has invalid identity block")
    id_dict = cast(dict[str, Any], raw)

    raw_url: object = id_dict.get("remote_url")
    if raw_url is not None and not isinstance(raw_url, str):
        raise ConfigValidationError(f"wdsync: {context} identity.remote_url must be a string")
    remote_url = raw_url if isinstance(raw_url, str) else None

    raw_commits: object = id_dict.get("root_commits", [])
    if not isinstance(raw_commits, list):
        raise ConfigValidationError(f"wdsync: {context} identity.root_commits must be a list")
    raw_commit_items = cast(list[Any], raw_commits)
    commits = tuple(
        sorted(_string_list(raw_commit_items, context=f"{context} identity.root_commits"))
    )
    return Identity(remote_url=remote_url, root_commits=commits)


def peer_to_dict(peer: PeerConfig) -> dict[str, object]:
    return {
        "command_argv": list(peer.command_argv),
        "root": peer.root.as_posix(),
        "root_native": peer.root_native,
    }


def peer_from_object(raw: object, *, context: str) -> PeerConfig:
    if not isinstance(raw, dict):
        raise ConfigValidationError(f"wdsync: {context} has invalid peer block")
    peer_dict = cast(dict[str, Any], raw)

    raw_argv: object = peer_dict.get("command_argv", [])
    if not isinstance(raw_argv, list):
        raise ConfigValidationError(f"wdsync: {context} peer.command_argv must be a list")
    raw_argv_items = cast(list[Any], raw_argv)
    argv = tuple(_string_list(raw_argv_items, context=f"{context} peer.command_argv"))

    raw_root: object = peer_dict.get("root", "")
    raw_root_native: object = peer_dict.get("root_native", "")
    root_str = raw_root if isinstance(raw_root, str) else ""
    root_native = raw_root_native if isinstance(raw_root_native, str) else ""
    if not argv or not root_str or not root_native:
        raise ConfigValidationError(
            f"wdsync: {context} has incomplete peer block — "
            "command_argv, root, and root_native are all required"
        )

    return PeerConfig(command_argv=argv, root=Path(root_str), root_native=root_native)


def runtime_preferences_to_dict(runtime: RuntimePreferences) -> dict[str, object]:
    return {
        "windows_peer_command_argv": (
            list(runtime.windows_peer_command_argv)
            if runtime.windows_peer_command_argv is not None
            else None
        ),
        "wsl_peer_command_argv": (
            list(runtime.wsl_peer_command_argv)
            if runtime.wsl_peer_command_argv is not None
            else None
        ),
        "wsl_distro": runtime.wsl_distro,
    }


def runtime_preferences_from_object(raw: object) -> RuntimePreferences:
    if raw is None:
        return RuntimePreferences()
    if not isinstance(raw, dict):
        raise ConfigValidationError("wdsync: config.json has invalid runtime block")
    runtime_dict = cast(dict[str, Any], raw)

    windows_peer_command_argv = _argv_from_value(
        runtime_dict.get("windows_peer_command_argv"),
        context="config.json runtime.windows_peer_command_argv",
    )
    wsl_peer_command_argv = _argv_from_value(
        runtime_dict.get("wsl_peer_command_argv"),
        context="config.json runtime.wsl_peer_command_argv",
    )
    raw_distro: object = runtime_dict.get("wsl_distro")
    wsl_distro = str(raw_distro) if isinstance(raw_distro, str) and raw_distro else None
    return RuntimePreferences(
        windows_peer_command_argv=windows_peer_command_argv,
        wsl_peer_command_argv=wsl_peer_command_argv,
        wsl_distro=wsl_distro,
    )


def wdsync_config_to_dict(config: WdsyncConfig) -> dict[str, object]:
    return {
        "version": config.version,
        "identity": identity_to_dict(config.identity),
        "peer": peer_to_dict(config.peer) if config.peer is not None else None,
        "runtime": runtime_preferences_to_dict(config.runtime),
    }


def wdsync_config_from_object(raw: object) -> WdsyncConfig:
    if not isinstance(raw, dict):
        raise ConfigValidationError("wdsync: config.json must be a JSON object")
    data = cast(dict[str, Any], raw)
    version: object = data.get("version", 1)
    raw_peer: object = data.get("peer")
    if raw_peer is not None and not isinstance(raw_peer, dict):
        raise ConfigValidationError("wdsync: config.json has invalid peer block")
    return WdsyncConfig(
        version=int(version) if isinstance(version, int) else 1,
        identity=identity_from_object(data.get("identity", {}), context="config.json"),
        peer=(
            peer_from_object(cast(dict[str, Any], raw_peer), context="config.json")
            if isinstance(raw_peer, dict)
            else None
        ),
        runtime=runtime_preferences_from_object(data.get("runtime")),
    )


def protocol_identity_from_object(raw: object) -> Identity:
    try:
        return identity_from_object(raw, context="RPC request")
    except ConfigValidationError as exc:
        raise WdSyncError(str(exc)) from exc


def protocol_peer_from_object(raw: object) -> PeerConfig:
    try:
        return peer_from_object(raw, context="RPC request")
    except ConfigValidationError as exc:
        raise WdSyncError(str(exc)) from exc


def status_record_to_dict(record: StatusRecord) -> dict[str, object]:
    return {
        "raw_xy": record.raw_xy,
        "path": record.path,
        "orig_path": record.orig_path,
        "kind": record.kind.value,
    }


def status_record_from_object(raw: object, *, context: str) -> StatusRecord:
    if not isinstance(raw, dict):
        raise ConfigValidationError(f"wdsync: {context} contains an invalid status record")
    data = cast(dict[str, Any], raw)
    raw_xy = _required_string(data.get("raw_xy"), context=f"{context} raw_xy")
    path = _required_string(data.get("path"), context=f"{context} path")
    raw_orig_path = data.get("orig_path")
    orig_path = raw_orig_path if isinstance(raw_orig_path, str) else None
    return StatusRecord(
        raw_xy=raw_xy,
        path=path,
        orig_path=orig_path,
        kind=classify_status(raw_xy),
    )


def destination_state_to_dict(state: DestinationState) -> dict[str, object]:
    return {
        "head": state.head,
        "modified_count": state.modified_count,
        "staged_count": state.staged_count,
        "untracked_count": state.untracked_count,
        "dirty_paths": sorted(state.dirty_paths),
        "wt_deleted_paths": sorted(state.wt_deleted_paths),
        "entries": [status_record_to_dict(entry) for entry in state.entries],
    }


def destination_state_from_object(raw: object, *, context: str) -> DestinationState:
    if not isinstance(raw, dict):
        raise ConfigValidationError(f"wdsync: {context} has invalid repo status payload")
    data = cast(dict[str, Any], raw)
    raw_head = data.get("head")
    head = raw_head if isinstance(raw_head, str) else None
    entries = _status_records_from_value(data.get("entries"), context=f"{context} entries")
    dirty_paths = frozenset(
        _string_list_from_value(data.get("dirty_paths"), context=f"{context} dirty_paths")
    )
    wt_deleted_paths = frozenset(
        _string_list_from_value(
            data.get("wt_deleted_paths"),
            context=f"{context} wt_deleted_paths",
        )
    )
    return DestinationState(
        head=head,
        modified_count=_required_int(
            data.get("modified_count"),
            context=f"{context} modified_count",
        ),
        staged_count=_required_int(data.get("staged_count"), context=f"{context} staged_count"),
        untracked_count=_required_int(
            data.get("untracked_count"),
            context=f"{context} untracked_count",
        ),
        dirty_paths=dirty_paths,
        wt_deleted_paths=wt_deleted_paths,
        entries=entries,
    )


def manifest_to_dict(mirrored_paths: frozenset[str]) -> dict[str, object]:
    return {"paths": sorted(mirrored_paths)}


def manifest_from_object(raw: object, *, context: str) -> frozenset[str]:
    if not isinstance(raw, dict):
        raise ConfigValidationError(f"wdsync: {context} has invalid manifest payload")
    data = cast(dict[str, Any], raw)
    return frozenset(_string_list_from_value(data.get("paths"), context=f"{context} paths"))


def fingerprints_to_dict(fingerprints: tuple[PathFingerprint, ...]) -> dict[str, object]:
    return {
        "fingerprints": [
            {
                "path": fingerprint.path,
                "object_id": fingerprint.object_id,
            }
            for fingerprint in fingerprints
        ]
    }


def fingerprints_from_object(raw: object, *, context: str) -> tuple[PathFingerprint, ...]:
    if not isinstance(raw, dict):
        raise ConfigValidationError(f"wdsync: {context} has invalid fingerprint payload")
    data = cast(dict[str, Any], raw)
    raw_items = data.get("fingerprints", [])
    if not isinstance(raw_items, list):
        raise ConfigValidationError(f"wdsync: {context} fingerprints must be a list")
    fingerprints: list[PathFingerprint] = []
    for index, raw_item in enumerate(cast(list[Any], raw_items)):
        if not isinstance(raw_item, dict):
            raise ConfigValidationError(
                f"wdsync: {context} fingerprints[{index}] has invalid structure"
            )
        item = cast(dict[str, Any], raw_item)
        object_id = item.get("object_id")
        if object_id is not None and not isinstance(object_id, str):
            raise ConfigValidationError(
                f"wdsync: {context} fingerprints[{index}].object_id must be a string or null"
            )
        fingerprints.append(
            PathFingerprint(
                path=_required_string(
                    item.get("path"),
                    context=f"{context} fingerprints[{index}].path",
                ),
                object_id=object_id,
            )
        )
    return tuple(fingerprints)


def delete_outcomes_to_dict(outcomes: tuple[DeleteOutcome, ...]) -> dict[str, object]:
    return {
        "outcomes": [
            {
                "path": outcome.path,
                "deleted": outcome.deleted,
                "skipped": outcome.skipped,
                "skip_reason": outcome.skip_reason,
                "used_sudo": outcome.used_sudo,
            }
            for outcome in outcomes
        ]
    }


def delete_outcomes_from_object(raw: object, *, context: str) -> tuple[DeleteOutcome, ...]:
    if not isinstance(raw, dict):
        raise ConfigValidationError(f"wdsync: {context} has invalid delete payload")
    data = cast(dict[str, Any], raw)
    raw_outcomes = data.get("outcomes", [])
    if not isinstance(raw_outcomes, list):
        raise ConfigValidationError(f"wdsync: {context} outcomes must be a list")
    outcomes: list[DeleteOutcome] = []
    for index, raw_outcome in enumerate(cast(list[Any], raw_outcomes)):
        if not isinstance(raw_outcome, dict):
            raise ConfigValidationError(
                f"wdsync: {context} outcomes[{index}] has invalid structure"
            )
        item = cast(dict[str, Any], raw_outcome)
        outcomes.append(
            DeleteOutcome(
                path=_required_string(
                    item.get("path"),
                    context=f"{context} outcomes[{index}].path",
                ),
                deleted=_required_bool(
                    item.get("deleted"),
                    context=f"{context} outcomes[{index}].deleted",
                ),
                skipped=_required_bool(
                    item.get("skipped"),
                    context=f"{context} outcomes[{index}].skipped",
                ),
                skip_reason=item.get("skip_reason")
                if isinstance(item.get("skip_reason"), str)
                else None,
                used_sudo=_required_bool(
                    item.get("used_sudo"),
                    context=f"{context} outcomes[{index}].used_sudo",
                ),
            )
        )
    return tuple(outcomes)


def restore_result_to_dict(result: RestoreResult) -> dict[str, object]:
    return {
        "restored_count": result.restored_count,
        "warnings": list(result.warnings),
    }


def restore_result_from_object(raw: object, *, context: str) -> RestoreResult:
    if not isinstance(raw, dict):
        raise ConfigValidationError(f"wdsync: {context} has invalid restore payload")
    data = cast(dict[str, Any], raw)
    warnings = tuple(_string_list_from_value(data.get("warnings"), context=f"{context} warnings"))
    return RestoreResult(
        restored_count=_required_int(
            data.get("restored_count"),
            context=f"{context} restored_count",
        ),
        warnings=warnings,
    )


def _argv_from_value(value: object, *, context: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ConfigValidationError(f"wdsync: {context} must be a JSON array of strings")
    items = cast(list[Any], value)
    argv = tuple(_string_list(items, context=context))
    return argv or None


def _required_string(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigValidationError(f"wdsync: {context} must be a non-empty string")
    return value


def _required_int(value: object, *, context: str) -> int:
    if not isinstance(value, int):
        raise ConfigValidationError(f"wdsync: {context} must be an integer")
    return value


def _required_bool(value: object, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigValidationError(f"wdsync: {context} must be a boolean")
    return value


def _status_records_from_value(value: object, *, context: str) -> tuple[StatusRecord, ...]:
    if not isinstance(value, list):
        raise ConfigValidationError(f"wdsync: {context} must be a list")
    items = cast(list[Any], value)
    return tuple(
        status_record_from_object(item, context=f"{context}[{index}]")
        for index, item in enumerate(items)
    )


def _string_list_from_value(value: object, *, context: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigValidationError(f"wdsync: {context} must be a list")
    items = cast(list[Any], value)
    return _string_list(items, context=context)


def _string_list(value: list[Any], *, context: str) -> list[str]:
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigValidationError(f"wdsync: {context} must contain only strings")
        strings.append(item)
    return strings

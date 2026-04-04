from __future__ import annotations

from typing import cast

from wdsync.core.codec import (
    delete_outcomes_from_object,
    destination_state_from_object,
    fingerprints_from_object,
    manifest_from_object,
    restore_result_from_object,
)
from wdsync.core.exceptions import ConfigValidationError, PeerConnectionError
from wdsync.core.models import (
    DeleteOutcome,
    DestinationState,
    HeadRelation,
    PathFingerprint,
    PeerConfig,
    RestoreResult,
)
from wdsync.core.protocol import (
    HANDSHAKE_CAPABILITIES,
    PROTOCOL_VERSION,
    RpcResponse,
    build_compare_heads_request,
    build_delete_request,
    build_fingerprint_paths_request,
    build_handshake_request,
    build_read_manifest_request,
    build_restore_request,
    build_status_request,
    build_write_manifest_request,
)
from wdsync.rpc.client import RpcClient

_REQUIRED_CAPABILITIES = frozenset(HANDSHAKE_CAPABILITIES)


class PeerSession:
    def __init__(self, peer: PeerConfig) -> None:
        self._peer = peer
        self._client = RpcClient(peer.command_argv)

    def __enter__(self) -> PeerSession:
        self._client.open()
        self._validate_handshake(self._client.send(build_handshake_request()))
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def status(self) -> DestinationState:
        response = self._client.send(build_status_request(repo_root_native=self._peer.root_native))
        try:
            return destination_state_from_object(response["data"], context="RPC response")
        except ConfigValidationError as exc:
            raise PeerConnectionError("wdsync: peer status response is malformed") from exc

    def compare_heads(self, source_head: str, destination_head: str) -> HeadRelation:
        response = self._client.send(
            build_compare_heads_request(
                repo_root_native=self._peer.root_native,
                source_head=source_head,
                destination_head=destination_head,
            )
        )
        raw_relation = response["data"].get("relation")
        if not isinstance(raw_relation, str):
            raise PeerConnectionError("wdsync: peer compare_heads response is malformed")
        try:
            return HeadRelation(raw_relation)
        except ValueError as exc:
            raise PeerConnectionError("wdsync: peer compare_heads response is malformed") from exc

    def fingerprint_paths(self, paths: tuple[str, ...]) -> dict[str, str | None]:
        if not paths:
            return {}
        response = self._client.send(
            build_fingerprint_paths_request(
                repo_root_native=self._peer.root_native,
                paths=paths,
            )
        )
        try:
            fingerprints = fingerprints_from_object(response["data"], context="RPC response")
        except ConfigValidationError as exc:
            raise PeerConnectionError("wdsync: peer fingerprint response is malformed") from exc
        return _fingerprint_map(fingerprints)

    def read_manifest(self) -> frozenset[str]:
        response = self._client.send(
            build_read_manifest_request(repo_root_native=self._peer.root_native)
        )
        try:
            return manifest_from_object(response["data"], context="RPC response")
        except ConfigValidationError as exc:
            raise PeerConnectionError("wdsync: peer manifest response is malformed") from exc

    def write_manifest(self, mirrored_paths: frozenset[str]) -> None:
        response = self._client.send(
            build_write_manifest_request(
                repo_root_native=self._peer.root_native,
                mirrored_paths=mirrored_paths,
            )
        )
        raw_saved = response["data"].get("saved")
        if raw_saved is not True:
            raise PeerConnectionError("wdsync: peer manifest write response is malformed")

    def delete(self, paths: tuple[str, ...]) -> tuple[DeleteOutcome, ...]:
        if not paths:
            return ()
        response = self._client.send(
            build_delete_request(repo_root_native=self._peer.root_native, paths=paths)
        )
        try:
            return delete_outcomes_from_object(response["data"], context="RPC response")
        except ConfigValidationError as exc:
            raise PeerConnectionError("wdsync: peer delete response is malformed") from exc

    def restore(self, paths: tuple[str, ...]) -> RestoreResult:
        if not paths:
            return RestoreResult(restored_count=0, warnings=())
        response = self._client.send(
            build_restore_request(repo_root_native=self._peer.root_native, paths=paths)
        )
        try:
            return restore_result_from_object(response["data"], context="RPC response")
        except ConfigValidationError as exc:
            raise PeerConnectionError("wdsync: peer restore response is malformed") from exc

    def _validate_handshake(self, response: RpcResponse) -> None:
        data = response["data"]
        peer_version: object = data.get("protocol_version")
        if peer_version != PROTOCOL_VERSION:
            raise PeerConnectionError(
                f"wdsync: peer protocol version mismatch "
                f"(local={PROTOCOL_VERSION}, peer={peer_version})"
            )
        raw_capabilities = data.get("capabilities", [])
        capabilities = capabilities_from_object(raw_capabilities)
        missing = sorted(
            capability for capability in _REQUIRED_CAPABILITIES if capability not in capabilities
        )
        if missing:
            missing_display = ", ".join(missing)
            raise PeerConnectionError(
                f"wdsync: peer is missing required RPC capabilities: {missing_display}"
            )


def capabilities_from_object(raw: object) -> frozenset[str]:
    if not isinstance(raw, list):
        raise PeerConnectionError("wdsync: peer handshake capabilities are malformed")
    capabilities: list[str] = []
    for item in cast(list[object], raw):
        if not isinstance(item, str):
            raise PeerConnectionError("wdsync: peer handshake capabilities are malformed")
        capabilities.append(item)
    return frozenset(capabilities)


def _fingerprint_map(fingerprints: tuple[PathFingerprint, ...]) -> dict[str, str | None]:
    return {fingerprint.path: fingerprint.object_id for fingerprint in fingerprints}

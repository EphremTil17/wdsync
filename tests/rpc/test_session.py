from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from wdsync.core.exceptions import PeerConnectionError
from wdsync.core.models import HeadRelation, PeerConfig, RestoreResult
from wdsync.core.protocol import HANDSHAKE_CAPABILITIES, PROTOCOL_VERSION
from wdsync.rpc.session import PeerSession


def _write_script(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_peer_session_roundtrips_status_manifest_delete_restore_and_compare_heads(
    tmp_path: Path,
) -> None:
    capabilities = [capability.value for capability in HANDSHAKE_CAPABILITIES]
    script = _write_script(
        tmp_path / "peer.py",
        "import json, sys\n"
        f"caps = {capabilities!r}\n"
        "manifest = ['before.txt']\n"
        "for raw in sys.stdin:\n"
        "    req = json.loads(raw)\n"
        "    method = req['method']\n"
        "    if method == 'handshake':\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        f"            'data': {{'protocol_version': {PROTOCOL_VERSION}, 'capabilities': caps}},\n"
        "            'error': None,\n"
        "        }\n"
        "    elif method == 'status':\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        "            'data': {\n"
        "                'head': 'abc123',\n"
        "                'modified_count': 1,\n"
        "                'staged_count': 0,\n"
        "                'untracked_count': 1,\n"
        "                'dirty_paths': ['dirty.txt'],\n"
        "                'wt_deleted_paths': [],\n"
        "                'entries': [\n"
        "                    {'raw_xy': ' M', 'path': 'dirty.txt',\n"
        "                     'orig_path': None, 'kind': 'unstaged'},\n"
        "                    {'raw_xy': '??', 'path': 'new.txt',\n"
        "                     'orig_path': None, 'kind': 'new'},\n"
        "                ],\n"
        "            },\n"
        "            'error': None,\n"
        "        }\n"
        "    elif method == 'read_manifest':\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        "            'data': {'paths': manifest},\n"
        "            'error': None,\n"
        "        }\n"
        "    elif method == 'write_manifest':\n"
        "        manifest = list(req['args']['paths'])\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        "            'data': {'saved': True},\n"
        "            'error': None,\n"
        "        }\n"
        "    elif method == 'delete':\n"
        "        paths = req['args']['paths']\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        "            'data': {'outcomes': [\n"
        "                {'path': p, 'deleted': True, 'skipped': False,\n"
        "                 'skip_reason': None, 'used_sudo': False}\n"
        "                for p in paths\n"
        "            ]},\n"
        "            'error': None,\n"
        "        }\n"
        "    elif method == 'restore':\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        "            'data': {'restored_count': len(req['args']['paths']), 'warnings': []},\n"
        "            'error': None,\n"
        "        }\n"
        "    elif method == 'compare_heads':\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        "            'data': {'relation': 'source-ahead'},\n"
        "            'error': None,\n"
        "        }\n"
        "    else:\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': False,\n"
        "            'data': {},\n"
        "            'error': 'bad method',\n"
        "        }\n"
        "    print(json.dumps(resp), flush=True)\n",
    )
    peer = PeerConfig(
        command_argv=(sys.executable, str(script)),
        root=Path("/tmp/peer"),
        root_native="/tmp/peer",
    )

    with PeerSession(peer) as session:
        state = session.status()
        initial_manifest = session.read_manifest()
        session.write_manifest(frozenset({"after.txt", "nested/new.txt"}))
        updated_manifest = session.read_manifest()
        delete_outcomes = session.delete(("gone.txt",))
        restore_result = session.restore(("gone.txt",))
        relation = session.compare_heads("new", "old")

    assert state.head == "abc123"
    assert state.modified_count == 1
    assert state.untracked_count == 1
    assert initial_manifest == frozenset({"before.txt"})
    assert updated_manifest == frozenset({"after.txt", "nested/new.txt"})
    assert delete_outcomes[0].path == "gone.txt"
    assert restore_result == RestoreResult(restored_count=1, warnings=())
    assert relation is HeadRelation.SOURCE_AHEAD


def test_peer_session_rejects_missing_capabilities(tmp_path: Path) -> None:
    script = _write_script(
        tmp_path / "missing_caps.py",
        "import json, sys\n"
        "for raw in sys.stdin:\n"
        "    req = json.loads(raw)\n"
        "    if req['method'] == 'handshake':\n"
        f"        resp = {{'version': {PROTOCOL_VERSION}, 'ok': True,\n"
        f"                'data': {{'protocol_version': {PROTOCOL_VERSION}, 'capabilities': []}},\n"
        "                'error': None}\n"
        "        print(json.dumps(resp), flush=True)\n"
        "        break\n",
    )
    peer = PeerConfig(
        command_argv=(sys.executable, str(script)),
        root=Path("/tmp/peer"),
        root_native="/tmp/peer",
    )

    with pytest.raises(PeerConnectionError, match="missing required RPC capabilities"):
        with PeerSession(peer):
            pass


def test_peer_session_rejects_malformed_status_payload(tmp_path: Path) -> None:
    capabilities = [capability.value for capability in HANDSHAKE_CAPABILITIES]
    script = _write_script(
        tmp_path / "bad_status.py",
        "import json, sys\n"
        f"caps = {capabilities!r}\n"
        "for raw in sys.stdin:\n"
        "    req = json.loads(raw)\n"
        "    if req['method'] == 'handshake':\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        f"            'data': {{'protocol_version': {PROTOCOL_VERSION}, 'capabilities': caps}},\n"
        "            'error': None,\n"
        "        }\n"
        "    else:\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        "            'data': {},\n"
        "            'error': None,\n"
        "        }\n"
        "    print(json.dumps(resp), flush=True)\n",
    )
    peer = PeerConfig(
        command_argv=(sys.executable, str(script)),
        root=Path("/tmp/peer"),
        root_native="/tmp/peer",
    )

    with PeerSession(peer) as session:
        with pytest.raises(PeerConnectionError, match="peer status response is malformed"):
            session.status()


def test_peer_session_rejects_malformed_manifest_payload(tmp_path: Path) -> None:
    capabilities = [capability.value for capability in HANDSHAKE_CAPABILITIES]
    script = _write_script(
        tmp_path / "bad_manifest.py",
        "import json, sys\n"
        f"caps = {capabilities!r}\n"
        "for raw in sys.stdin:\n"
        "    req = json.loads(raw)\n"
        "    if req['method'] == 'handshake':\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        f"            'data': {{'protocol_version': {PROTOCOL_VERSION}, 'capabilities': caps}},\n"
        "            'error': None,\n"
        "        }\n"
        "    else:\n"
        "        resp = {\n"
        f"            'version': {PROTOCOL_VERSION},\n"
        "            'ok': True,\n"
        "            'data': {'paths': 'bad'},\n"
        "            'error': None,\n"
        "        }\n"
        "    print(json.dumps(resp), flush=True)\n",
    )
    peer = PeerConfig(
        command_argv=(sys.executable, str(script)),
        root=Path("/tmp/peer"),
        root_native="/tmp/peer",
    )

    with PeerSession(peer) as session:
        with pytest.raises(PeerConnectionError, match="peer manifest response is malformed"):
            session.read_manifest()

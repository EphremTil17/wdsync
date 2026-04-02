from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from wdsync.core.exceptions import PeerConnectionError
from wdsync.core.protocol import PROTOCOL_VERSION, RpcMethod, RpcRequest
from wdsync.rpc.client import RpcClient


def _write_script(path: Path, body: str) -> Path:
    """Write a tiny Python script and make it executable."""
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture()
def echo_peer(tmp_path: Path) -> Path:
    """Peer script that echoes a valid handshake response for every line."""
    response = json.dumps(
        {
            "version": PROTOCOL_VERSION,
            "ok": True,
            "data": {"protocol_version": PROTOCOL_VERSION, "capabilities": []},
            "error": None,
        }
    )
    return _write_script(
        tmp_path / "echo_peer.py",
        "import sys\n"
        "for line in sys.stdin:\n"
        "    if line.strip():\n"
        f"        print({response!r}, flush=True)\n",
    )


def test_send_and_receive_happy_path(echo_peer: Path) -> None:
    with RpcClient((sys.executable, str(echo_peer))) as client:
        request: RpcRequest = {
            "version": PROTOCOL_VERSION,
            "method": RpcMethod.HANDSHAKE,
            "args": {},
        }
        response = client.send(request)

    assert response["ok"] is True
    assert response["data"]["protocol_version"] == PROTOCOL_VERSION


def test_spawn_failure_raises_peer_error() -> None:
    with pytest.raises(PeerConnectionError, match="not found"):
        with RpcClient(("nonexistent_binary_xyz",)):
            pass


def test_peer_invalid_json_raises_peer_error(tmp_path: Path) -> None:
    script = _write_script(
        tmp_path / "garbage.py",
        "import sys\n"
        "for line in sys.stdin:\n"
        "    print('this is not json', flush=True)\n"
        "    break\n",
    )
    with pytest.raises(PeerConnectionError, match="invalid JSON"):
        with RpcClient((sys.executable, str(script))) as client:
            client.send({"version": 1, "method": "handshake", "args": {}})


def test_peer_timeout_raises_peer_error(tmp_path: Path) -> None:
    script = _write_script(
        tmp_path / "sleeper.py",
        "import time\ntime.sleep(60)\n",
    )
    with pytest.raises(PeerConnectionError, match="did not respond"):
        with RpcClient((sys.executable, str(script)), timeout=0.3) as client:
            client.send({"version": 1, "method": "handshake", "args": {}})


def test_peer_exit_raises_peer_error(tmp_path: Path) -> None:
    script = _write_script(
        tmp_path / "exit_immediately.py",
        "pass\n",
    )
    with pytest.raises(PeerConnectionError, match="closed stdout"):
        with RpcClient((sys.executable, str(script))) as client:
            client.send({"version": 1, "method": "handshake", "args": {}})


def test_context_manager_cleans_up(echo_peer: Path) -> None:
    client = RpcClient((sys.executable, str(echo_peer)))
    client.open()
    assert client._process is not None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    pid = client._process.pid  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    client.close()
    assert client._process is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    import os
    import signal

    with pytest.raises(OSError):
        os.kill(pid, signal.SIG_DFL)


def test_error_response_raises_peer_error(tmp_path: Path) -> None:
    response = json.dumps(
        {"version": PROTOCOL_VERSION, "ok": False, "data": {}, "error": "test-error-msg"}
    )
    script = _write_script(
        tmp_path / "error_peer.py",
        "import sys\n"
        "for line in sys.stdin:\n"
        "    if line.strip():\n"
        f"        print({response!r}, flush=True)\n"
        "        break\n",
    )
    with pytest.raises(PeerConnectionError, match="test-error-msg"):
        with RpcClient((sys.executable, str(script))) as client:
            client.send({"version": 1, "method": "handshake", "args": {}})


def test_stderr_included_in_error(tmp_path: Path) -> None:
    script = _write_script(
        tmp_path / "stderr_peer.py",
        "import sys\n"
        "sys.stderr.write('peer-debug-info\\n')\n"
        "sys.stderr.flush()\n"
        "# exit without responding\n",
    )
    with pytest.raises(PeerConnectionError, match="peer-debug-info"):
        with RpcClient((sys.executable, str(script))) as client:
            client.send({"version": 1, "method": "handshake", "args": {}})


def test_malformed_version_field_raises_peer_error(tmp_path: Path) -> None:
    """A non-numeric version field should not raise a raw ValueError."""
    response = json.dumps({"version": "abc", "ok": True, "data": {}, "error": None})
    script = _write_script(
        tmp_path / "bad_version.py",
        "import sys\n"
        "for line in sys.stdin:\n"
        "    if line.strip():\n"
        f"        print({response!r}, flush=True)\n"
        "        break\n",
    )
    with RpcClient((sys.executable, str(script))) as client:
        resp = client.send({"version": 1, "method": "handshake", "args": {}})

    # Should not crash — version defaults to 0 for non-numeric
    assert resp["version"] == 0


def test_malformed_data_field_handled(tmp_path: Path) -> None:
    """A non-dict data field should not raise a raw TypeError."""
    response = json.dumps({"version": 1, "ok": True, "data": "not-a-dict", "error": None})
    script = _write_script(
        tmp_path / "bad_data.py",
        "import sys\n"
        "for line in sys.stdin:\n"
        "    if line.strip():\n"
        f"        print({response!r}, flush=True)\n"
        "        break\n",
    )
    with RpcClient((sys.executable, str(script))) as client:
        resp = client.send({"version": 1, "method": "handshake", "args": {}})

    # data should be normalized to empty dict
    assert resp["data"] == {}


def test_malformed_ok_field_raises_peer_error(tmp_path: Path) -> None:
    """A non-boolean ok field should be rejected instead of coerced."""
    response = json.dumps({"version": 1, "ok": "false", "data": {}, "error": None})
    script = _write_script(
        tmp_path / "bad_ok.py",
        "import sys\n"
        "for line in sys.stdin:\n"
        "    if line.strip():\n"
        f"        print({response!r}, flush=True)\n"
        "        break\n",
    )
    with pytest.raises(PeerConnectionError, match="unexpected structure"):
        with RpcClient((sys.executable, str(script))) as client:
            client.send({"version": 1, "method": "handshake", "args": {}})

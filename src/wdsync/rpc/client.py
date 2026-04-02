from __future__ import annotations

import json
import subprocess
from collections import deque
from queue import Empty, Queue
from threading import Thread
from typing import Any, BinaryIO, cast

from wdsync.core.exceptions import PeerConnectionError
from wdsync.core.protocol import RpcRequest, RpcResponse


class RpcClient:
    """Spawn a peer wdsync process and exchange JSON-RPC messages over stdin/stdout."""

    def __init__(self, command_argv: tuple[str, ...], *, timeout: float = 10.0) -> None:
        self._command_argv = command_argv
        self._timeout = timeout
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_queue: Queue[bytes | None] = Queue()
        self._stderr_lines: deque[str] = deque(maxlen=5)
        self._stdout_thread: Thread | None = None
        self._stderr_thread: Thread | None = None

    def open(self) -> None:
        try:
            self._process = subprocess.Popen(
                [*self._command_argv, "rpc"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise PeerConnectionError(
                f"wdsync: peer command not found: {self._command_argv[0]}"
            ) from exc
        except OSError as exc:
            raise PeerConnectionError(f"wdsync: failed to spawn peer process: {exc}") from exc
        self._stdout_queue = Queue()
        self._stderr_lines.clear()
        self._start_reader_threads()

    def send(self, request: RpcRequest) -> RpcResponse:
        if self._process is None:
            raise PeerConnectionError("wdsync: peer process not started")
        self._write_request(request)
        raw = self._read_line()
        response = self._parse_response(raw)
        if not response["ok"]:
            stderr_tail = self._drain_stderr()
            error_msg = response.get("error") or "unknown peer error"
            detail = f"wdsync: peer returned error: {error_msg}"
            if stderr_tail:
                detail += f"\npeer stderr:\n{stderr_tail}"
            raise PeerConnectionError(detail)
        return response

    def close(self) -> None:
        if self._process is None:
            return
        try:
            if self._process.stdin:
                self._process.stdin.close()
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        finally:
            # Drain remaining stderr/stdout to prevent leaking to terminal
            if self._process.stderr:
                try:
                    self._process.stderr.read()
                except OSError:
                    pass
                self._process.stderr.close()
            if self._process.stdout:
                try:
                    self._process.stdout.read()
                except OSError:
                    pass
                self._process.stdout.close()
            self._stdout_thread = None
            self._stderr_thread = None
            self._process = None

    def __enter__(self) -> RpcClient:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _write_request(self, request: RpcRequest) -> None:
        assert self._process is not None
        assert self._process.stdin is not None
        payload = json.dumps(request, sort_keys=True) + "\n"
        try:
            self._process.stdin.write(payload.encode("utf-8"))
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            stderr_tail = self._drain_stderr()
            detail = "wdsync: peer process terminated unexpectedly"
            if stderr_tail:
                detail += f"\npeer stderr:\n{stderr_tail}"
            raise PeerConnectionError(detail) from exc

    def _read_line(self) -> str:
        try:
            raw = self._stdout_queue.get(timeout=self._timeout)
        except Empty as exc:
            stderr_tail = self._drain_stderr()
            detail = f"wdsync: peer did not respond within {self._timeout}s"
            if stderr_tail:
                detail += f"\npeer stderr:\n{stderr_tail}"
            raise PeerConnectionError(detail) from exc
        if raw is None:
            stderr_tail = self._drain_stderr()
            detail = "wdsync: peer process closed stdout without responding"
            if stderr_tail:
                detail += f"\npeer stderr:\n{stderr_tail}"
            raise PeerConnectionError(detail)
        return raw.decode("utf-8", errors="surrogateescape").strip()

    def _parse_response(self, raw: str) -> RpcResponse:
        try:
            parsed: object = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PeerConnectionError(f"wdsync: peer sent invalid JSON: {raw[:200]}") from exc
        if not isinstance(parsed, dict):
            raise PeerConnectionError("wdsync: peer response is not a JSON object")
        data = cast(dict[str, Any], parsed)
        try:
            raw_version: object = data.get("version", 0)
            version = int(raw_version) if isinstance(raw_version, (int, float)) else 0
            raw_ok: object = data.get("ok", False)
            if not isinstance(raw_ok, bool):
                raise TypeError("response 'ok' field must be a boolean")
            raw_data: object = data.get("data", {})
            response_data = cast(dict[str, object], raw_data) if isinstance(raw_data, dict) else {}
            raw_error: object = data.get("error")
            error = str(raw_error) if raw_error is not None else None
            return RpcResponse(
                version=version,
                ok=raw_ok,
                data=response_data,
                error=error,
            )
        except (TypeError, ValueError) as exc:
            raise PeerConnectionError(
                f"wdsync: peer response has unexpected structure: {raw[:200]}"
            ) from exc

    def _drain_stderr(self) -> str:
        return "\n".join(self._stderr_lines)

    def _start_reader_threads(self) -> None:
        assert self._process is not None
        assert self._process.stdout is not None
        assert self._process.stderr is not None

        self._stdout_thread = Thread(
            target=self._pump_stdout,
            args=(self._process.stdout,),
            daemon=True,
        )
        self._stderr_thread = Thread(
            target=self._pump_stderr,
            args=(self._process.stderr,),
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _pump_stdout(self, stream: BinaryIO) -> None:
        while True:
            chunk = stream.readline()
            if not chunk:
                self._stdout_queue.put(None)
                return
            self._stdout_queue.put(chunk)

    def _pump_stderr(self, stream: BinaryIO) -> None:
        while True:
            chunk = stream.readline()
            if not chunk:
                return
            text = chunk.decode("utf-8", errors="replace").strip()
            if text:
                self._stderr_lines.append(text)

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from wdsync.exceptions import CommandExecutionError, MissingDependencyError


def _decode_output(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape")


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes

    def stdout_text(self) -> str:
        return _decode_output(self.stdout)

    def stderr_text(self) -> str:
        return _decode_output(self.stderr)


class CommandRunner:
    def __init__(self, program_overrides: Mapping[str, str | Path] | None = None) -> None:
        self._program_overrides = {
            key: str(value) for key, value in (program_overrides or {}).items()
        }

    def maybe_resolve_program(self, program: str) -> str | None:
        if program in self._program_overrides:
            return self._program_overrides[program]
        if "/" in program:
            return program if Path(program).exists() else None
        return shutil.which(program)

    def require_program(self, program: str) -> str:
        resolved = self.maybe_resolve_program(program)
        if resolved is None:
            raise MissingDependencyError(f"wdsync: required program not found: {program}")
        return resolved

    def _normalize_args(self, args: Sequence[str | Path]) -> list[str]:
        if not args:
            raise ValueError("CommandRunner.run requires at least one argument.")
        normalized = [str(arg) for arg in args]
        normalized[0] = self.require_program(normalized[0])
        return normalized

    def run(
        self,
        args: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        normalized = self._normalize_args(args)
        completed = subprocess.run(
            normalized,
            capture_output=True,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=False,
        )
        result = CommandResult(
            args=tuple(normalized),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and result.returncode != 0:
            detail = result.stderr_text().strip() or result.stdout_text().strip() or "unknown error"
            raise CommandExecutionError(
                f"wdsync: command failed: {detail}",
                command=result.args,
                returncode=result.returncode,
                stderr=result.stderr_text(),
                stdout=result.stdout_text(),
            )
        return result


def build_runner() -> CommandRunner:
    return CommandRunner()

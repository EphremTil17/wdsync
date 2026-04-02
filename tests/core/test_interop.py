from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from wdsync.core.environment import Environment
from wdsync.core.exceptions import MissingDependencyError
from wdsync.core.interop import (
    ensure_local_rsync_available,
    git_command_for_target,
    local_path_for_rsync_command,
    local_rsync_root,
    resolve_peer_command_for_environment,
    resolve_reverse_peer_command_for_environment,
    runtime_with_configured_peer_command,
    runtime_with_resolved_peer_command,
)
from wdsync.core.models import RuntimePreferences
from wdsync.core.runner import CommandResult, CommandRunner


class _CaptureRunner:
    def __init__(self, stdout: bytes) -> None:
        self.stdout = stdout
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        del cwd, check, env
        normalized = tuple(str(arg) for arg in args)
        self.calls.append(normalized)
        return CommandResult(
            args=normalized,
            returncode=0,
            stdout=self.stdout,
            stderr=b"",
        )


class _ResolutionRunner:
    def __init__(
        self,
        *,
        programs: Mapping[str, str] | None = None,
        responses: Mapping[tuple[str, ...], CommandResult] | None = None,
    ) -> None:
        self.programs = dict(programs or {})
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, ...]] = []

    def require_program(self, program: str) -> str:
        if program in self.programs:
            return self.programs[program]
        raise MissingDependencyError(f"missing program: {program}")

    def run(
        self,
        args: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        del cwd, env
        normalized = tuple(str(arg) for arg in args)
        self.calls.append(normalized)
        result = self.responses.get(normalized)
        if result is None:
            result = CommandResult(args=normalized, returncode=1, stdout=b"", stderr=b"missing")
        if check and result.returncode != 0:
            raise MissingDependencyError(f"missing command: {' '.join(normalized)}")
        return result


def test_git_command_for_windows_to_wsl_uses_exec() -> None:
    assert git_command_for_target(Environment.WINDOWS, Environment.WSL) == (
        "wsl.exe",
        "--exec",
        "git",
    )


def test_local_rsync_root_on_windows_uses_wsl_exec() -> None:
    runner = _CaptureRunner(b"/mnt/c/Users/user/repo\n")

    translated = local_rsync_root(
        Environment.WINDOWS,
        Path(r"C:\Users\user\repo"),
        cast(CommandRunner, runner),
    )

    assert translated == "/mnt/c/Users/user/repo"
    assert runner.calls == [
        ("wsl.exe", "--exec", "wslpath", "-a", r"C:\Users\user\repo"),
    ]


def test_local_rsync_root_on_wsl_keeps_local_path() -> None:
    runner = CommandRunner()

    translated = local_rsync_root(
        Environment.WSL,
        Path("/home/user/repo"),
        runner,
    )

    assert translated == "/home/user/repo"


def test_local_path_for_rsync_command_on_windows_uses_wsl_exec() -> None:
    runner = _CaptureRunner(b"/mnt/c/Temp/files-from.txt\n")

    translated = local_path_for_rsync_command(
        ("wsl.exe", "--exec", "rsync"),
        Path(r"C:\Temp\files-from.txt"),
        cast(CommandRunner, runner),
    )

    assert translated == "/mnt/c/Temp/files-from.txt"
    assert runner.calls == [
        ("wsl.exe", "--exec", "wslpath", "-a", r"C:\Temp\files-from.txt"),
    ]


def test_ensure_local_rsync_available_reports_install_hint_on_wsl() -> None:
    runner = _ResolutionRunner()

    with pytest.raises(MissingDependencyError, match="Install it system-wide"):
        ensure_local_rsync_available(Environment.WSL, cast(CommandRunner, runner))

    with pytest.raises(MissingDependencyError, match="Verify with: rsync --version"):
        ensure_local_rsync_available(Environment.WSL, cast(CommandRunner, runner))


def test_ensure_local_rsync_available_reports_install_hint_on_windows() -> None:
    runner = _ResolutionRunner()

    with pytest.raises(MissingDependencyError, match="Install or enable WSL"):
        ensure_local_rsync_available(Environment.WINDOWS, cast(CommandRunner, runner))

    with pytest.raises(MissingDependencyError, match="wsl.exe --exec rsync --version"):
        ensure_local_rsync_available(Environment.WINDOWS, cast(CommandRunner, runner))


def test_resolve_peer_command_for_windows_uses_explicit_wsl_path() -> None:
    runner = _ResolutionRunner(
        responses={
            ("wsl.exe", "--exec", "printenv", "HOME"): CommandResult(
                args=("wsl.exe", "--exec", "printenv", "HOME"),
                returncode=0,
                stdout=b"/home/ephrem\n",
                stderr=b"",
            ),
            ("wsl.exe", "--exec", "/home/ephrem/.local/bin/wdsync", "--version"): CommandResult(
                args=("wsl.exe", "--exec", "/home/ephrem/.local/bin/wdsync", "--version"),
                returncode=0,
                stdout=b"wdsync 0.1\n",
                stderr=b"",
            ),
            ("wsl.exe", "--exec", "which", "wdsync"): CommandResult(
                args=("wsl.exe", "--exec", "which", "wdsync"),
                returncode=1,
                stdout=b"",
                stderr=b"",
            ),
        },
    )

    resolved = resolve_peer_command_for_environment(
        Environment.WINDOWS,
        RuntimePreferences(),
        cast(CommandRunner, runner),
    )

    assert resolved.stored_argv == ("/home/ephrem/.local/bin/wdsync",)
    assert resolved.spawn_argv == ("wsl.exe", "--exec", "/home/ephrem/.local/bin/wdsync")


def test_resolve_peer_command_for_wsl_translates_windows_executable_to_wsl_path() -> None:
    runner = _ResolutionRunner(
        programs={
            "wdsync.exe": r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe",
            "/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe": (
                "/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe"
            ),
        },
        responses={
            (
                r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe",
                "--version",
            ): CommandResult(
                args=(
                    r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe",
                    "--version",
                ),
                returncode=0,
                stdout=b"wdsync 0.1\n",
                stderr=b"",
            ),
            (
                "wslpath",
                r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe",
            ): CommandResult(
                args=("wslpath", r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe"),
                returncode=0,
                stdout=b"/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe\n",
                stderr=b"",
            ),
            (
                "/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe",
                "--version",
            ): CommandResult(
                args=(
                    "/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe",
                    "--version",
                ),
                returncode=0,
                stdout=b"wdsync 0.1\n",
                stderr=b"",
            ),
        },
    )

    resolved = resolve_peer_command_for_environment(
        Environment.WSL,
        RuntimePreferences(),
        cast(CommandRunner, runner),
    )

    assert resolved.spawn_argv == ("/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe",)
    assert resolved.stored_argv == (
        "/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe",
    )


def test_resolve_reverse_peer_command_for_windows_translates_local_executable_for_wsl() -> None:
    runner = _ResolutionRunner(
        programs={"wdsync.exe": r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe"},
        responses={
            (
                r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe",
                "--version",
            ): CommandResult(
                args=(
                    r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe",
                    "--version",
                ),
                returncode=0,
                stdout=b"wdsync 0.1\n",
                stderr=b"",
            ),
            (
                "wsl.exe",
                "--exec",
                "wslpath",
                "-a",
                r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe",
            ): CommandResult(
                args=(
                    "wsl.exe",
                    "--exec",
                    "wslpath",
                    "-a",
                    r"C:\Users\Ephrem\AppData\Roaming\Python\Scripts\wdsync.exe",
                ),
                returncode=0,
                stdout=b"/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe\n",
                stderr=b"",
            ),
            (
                "wsl.exe",
                "--exec",
                "/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe",
                "--version",
            ): CommandResult(
                args=(
                    "wsl.exe",
                    "--exec",
                    "/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe",
                    "--version",
                ),
                returncode=0,
                stdout=b"wdsync 0.1\n",
                stderr=b"",
            ),
        },
    )

    resolved = resolve_reverse_peer_command_for_environment(
        Environment.WINDOWS,
        RuntimePreferences(),
        cast(CommandRunner, runner),
    )

    assert resolved == ("/mnt/c/Users/Ephrem/AppData/Roaming/Python/Scripts/wdsync.exe",)


def test_runtime_with_resolved_peer_command_updates_target_side_only() -> None:
    runtime = RuntimePreferences(
        windows_peer_command_argv=("wdsync.exe",),
        wsl_peer_command_argv=("python", "-m", "wdsync"),
        wsl_distro="Ubuntu",
    )

    updated = runtime_with_resolved_peer_command(
        Environment.WINDOWS,
        runtime,
        ("/home/ephrem/.local/bin/wdsync",),
    )

    assert updated.windows_peer_command_argv == ("wdsync.exe",)
    assert updated.wsl_peer_command_argv == ("/home/ephrem/.local/bin/wdsync",)
    assert updated.wsl_distro == "Ubuntu"


def test_runtime_with_configured_peer_command_unwraps_windows_wsl_exec() -> None:
    updated = runtime_with_configured_peer_command(
        Environment.WINDOWS,
        RuntimePreferences(),
        ("wsl.exe", "-d", "Ubuntu", "--exec", "/home/ephrem/.local/bin/wdsync"),
    )

    assert updated.wsl_peer_command_argv == ("/home/ephrem/.local/bin/wdsync",)
    assert updated.wsl_distro == "Ubuntu"

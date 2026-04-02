from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from wdsync.core.environment import Environment
from wdsync.core.exceptions import (
    CommandExecutionError,
    MissingDependencyError,
    PeerConnectionError,
)
from wdsync.core.models import RuntimePreferences
from wdsync.core.runner import CommandRunner


@dataclass(frozen=True)
class ResolvedPeerCommand:
    spawn_argv: tuple[str, ...]
    stored_argv: tuple[str, ...]


def _wsl_exec_command(
    *inner: str,
    distro: str | None = None,
) -> tuple[str, ...]:
    if distro:
        return ("wsl.exe", "-d", distro, "--exec", *inner)
    return ("wsl.exe", "--exec", *inner)


def peer_environment(local_env: Environment) -> Environment:
    if local_env is Environment.WSL:
        return Environment.WINDOWS
    if local_env is Environment.WINDOWS:
        return Environment.WSL
    raise PeerConnectionError("wdsync: peer discovery is only supported between WSL and Windows")


def current_wsl_distro() -> str | None:
    import os

    raw = os.environ.get("WSL_DISTRO_NAME", "").strip()
    return raw or None


def _validate_local_command(
    command_argv: tuple[str, ...],
    runner: CommandRunner,
    *,
    dependency_label: str,
) -> tuple[str, ...]:
    if not command_argv:
        raise MissingDependencyError(
            f"wdsync: required program not found or unusable: {dependency_label}"
        )
    resolved = (runner.require_program(command_argv[0]), *command_argv[1:])
    try:
        runner.run([*resolved, "--version"])
    except MissingDependencyError:
        raise
    except CommandExecutionError as exc:
        raise MissingDependencyError(
            f"wdsync: required program not found or unusable: {dependency_label}"
        ) from exc
    return resolved


def _resolve_wsl_program(
    program: str,
    runner: CommandRunner,
    *,
    distro: str | None,
) -> str | None:
    if "/" in program:
        return program
    result = runner.run(
        [*_wsl_exec_command("which", program, distro=distro)],
        check=False,
    )
    if result.returncode != 0:
        return None
    resolved = result.stdout_text().strip()
    return resolved or None


def _validate_wsl_command(
    command_argv: tuple[str, ...],
    runner: CommandRunner,
    *,
    distro: str | None,
    dependency_label: str,
) -> tuple[str, ...]:
    if not command_argv:
        raise MissingDependencyError(
            f"wdsync: required program not found or unusable: {dependency_label}"
        )
    resolved_program = (
        _resolve_wsl_program(command_argv[0], runner, distro=distro) or command_argv[0]
    )
    resolved = (resolved_program, *command_argv[1:])
    try:
        runner.run([*_wsl_exec_command(*resolved, distro=distro), "--version"])
    except MissingDependencyError:
        raise
    except CommandExecutionError as exc:
        raise MissingDependencyError(
            f"wdsync: required program not found or unusable: {dependency_label}"
        ) from exc
    return resolved


def _validate_windows_command_from_wsl(
    command_argv: tuple[str, ...],
    runner: CommandRunner,
    *,
    dependency_label: str,
) -> tuple[str, ...]:
    resolved = _validate_local_command(
        command_argv,
        runner,
        dependency_label=dependency_label,
    )
    if resolved[0].startswith("/"):
        return resolved
    translated_result = runner.run(["wslpath", resolved[0]])
    translated = (translated_result.stdout_text().strip(), *resolved[1:])
    return _validate_local_command(
        translated,
        runner,
        dependency_label=dependency_label,
    )


def _validate_windows_command_for_wsl(
    command_argv: tuple[str, ...],
    runner: CommandRunner,
    *,
    distro: str | None,
    dependency_label: str,
) -> tuple[str, ...]:
    resolved = _validate_local_command(
        command_argv,
        runner,
        dependency_label=dependency_label,
    )
    translated_result = runner.run(
        [*_wsl_exec_command("wslpath", "-a", resolved[0], distro=distro)]
    )
    translated = (translated_result.stdout_text().strip(), *resolved[1:])
    return _validate_wsl_command(
        translated,
        runner,
        distro=distro,
        dependency_label=dependency_label,
    )


def _discover_wsl_peer_command(
    runner: CommandRunner,
    *,
    distro: str | None,
) -> tuple[str, ...]:
    home_result = runner.run(
        [*_wsl_exec_command("printenv", "HOME", distro=distro)],
        check=False,
    )
    candidates: list[tuple[str, ...]] = []
    home_dir = home_result.stdout_text().strip() if home_result.returncode == 0 else ""
    if home_dir:
        candidates.append((f"{home_dir}/.local/bin/wdsync",))
    resolved_on_path = _resolve_wsl_program("wdsync", runner, distro=distro)
    if resolved_on_path is not None:
        candidates.append((resolved_on_path,))

    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return _validate_wsl_command(
                candidate,
                runner,
                distro=distro,
                dependency_label="wsl wdsync",
            )
        except MissingDependencyError:
            continue

    raise MissingDependencyError(
        "wdsync: could not resolve the WSL peer executable. "
        "Install wdsync in WSL or pass --wsl-peer-command."
    )


def peer_command_for_environment(
    local_env: Environment,
    runtime: RuntimePreferences,
    *,
    local_wsl_distro: str | None = None,
) -> tuple[str, ...]:
    if local_env is Environment.WSL:
        return runtime.windows_peer_command_argv or ("wdsync.exe",)
    if local_env is Environment.WINDOWS:
        inner, embedded_distro = _unwrap_wsl_exec_command(
            runtime.wsl_peer_command_argv or ("wdsync",)
        )
        distro = runtime.wsl_distro or embedded_distro or local_wsl_distro
        return _wsl_exec_command(*inner, distro=distro)
    raise PeerConnectionError("wdsync: connect is only supported between WSL and Windows")


def resolve_peer_command_for_environment(
    local_env: Environment,
    runtime: RuntimePreferences,
    runner: CommandRunner,
    *,
    local_wsl_distro: str | None = None,
) -> ResolvedPeerCommand:
    if local_env is Environment.WSL:
        stored = _validate_windows_command_from_wsl(
            runtime.windows_peer_command_argv or ("wdsync.exe",),
            runner,
            dependency_label="windows wdsync.exe",
        )
        return ResolvedPeerCommand(spawn_argv=stored, stored_argv=stored)
    if local_env is Environment.WINDOWS:
        configured_inner, embedded_distro = _unwrap_wsl_exec_command(
            runtime.wsl_peer_command_argv or ("wdsync",)
        )
        distro = runtime.wsl_distro or embedded_distro or local_wsl_distro
        stored = (
            _validate_wsl_command(
                configured_inner,
                runner,
                distro=distro,
                dependency_label="wsl peer command",
            )
            if runtime.wsl_peer_command_argv is not None
            else _discover_wsl_peer_command(runner, distro=distro)
        )
        return ResolvedPeerCommand(
            spawn_argv=_wsl_exec_command(*stored, distro=distro),
            stored_argv=stored,
        )
    raise PeerConnectionError("wdsync: connect is only supported between WSL and Windows")


def resolve_reverse_peer_command_for_environment(
    local_env: Environment,
    runtime: RuntimePreferences,
    runner: CommandRunner,
    *,
    local_wsl_distro: str | None = None,
) -> tuple[str, ...]:
    if local_env is Environment.WSL:
        configured_inner, embedded_distro = _unwrap_wsl_exec_command(
            runtime.wsl_peer_command_argv or ("wdsync",)
        )
        local_command = (
            _validate_local_command(
                configured_inner,
                runner,
                dependency_label="local wsl peer command",
            )
            if runtime.wsl_peer_command_argv is not None
            else _validate_local_command(("wdsync",), runner, dependency_label="local wdsync")
        )
        return _wsl_exec_command(
            *local_command,
            distro=embedded_distro or local_wsl_distro,
        )
    if local_env is Environment.WINDOWS:
        distro = runtime.wsl_distro or local_wsl_distro
        return _validate_windows_command_for_wsl(
            runtime.windows_peer_command_argv or ("wdsync.exe",),
            runner,
            distro=distro,
            dependency_label="local windows peer command",
        )
    raise PeerConnectionError("wdsync: connect is only supported between WSL and Windows")


def runtime_with_resolved_peer_command(
    local_env: Environment,
    runtime: RuntimePreferences,
    command_argv: tuple[str, ...],
) -> RuntimePreferences:
    if local_env is Environment.WSL:
        return replace(runtime, windows_peer_command_argv=command_argv)
    if local_env is Environment.WINDOWS:
        return replace(runtime, wsl_peer_command_argv=command_argv)
    raise PeerConnectionError("wdsync: connect is only supported between WSL and Windows")


def runtime_with_configured_peer_command(
    local_env: Environment,
    runtime: RuntimePreferences,
    command_argv: tuple[str, ...],
) -> RuntimePreferences:
    if local_env is Environment.WSL:
        return replace(runtime, windows_peer_command_argv=command_argv)
    if local_env is Environment.WINDOWS:
        inner_command, distro = _unwrap_wsl_exec_command(command_argv)
        return replace(
            runtime,
            wsl_peer_command_argv=inner_command,
            wsl_distro=distro if distro is not None else runtime.wsl_distro,
        )
    raise PeerConnectionError("wdsync: connect is only supported between WSL and Windows")


def _unwrap_wsl_exec_command(command_argv: tuple[str, ...]) -> tuple[tuple[str, ...], str | None]:
    if not command_argv or command_argv[0].lower() != "wsl.exe":
        return command_argv, None
    index = 1
    distro: str | None = None
    if len(command_argv) >= 4 and command_argv[1] == "-d":
        distro = command_argv[2]
        index = 3
    if index >= len(command_argv) or command_argv[index] != "--exec":
        return command_argv, None
    inner = command_argv[index + 1 :]
    return inner, distro


def git_command_for_target(local_env: Environment, target_env: Environment) -> tuple[str, ...]:
    if local_env is Environment.WINDOWS and target_env is Environment.WSL:
        return _wsl_exec_command("git")
    if local_env is Environment.WSL and target_env is Environment.WINDOWS:
        return ("git.exe",)
    if target_env is Environment.WINDOWS:
        return ("git.exe",)
    return ("git",)


def rsync_command_for_environment(local_env: Environment) -> tuple[str, ...]:
    if local_env is Environment.WINDOWS:
        return _wsl_exec_command("rsync")
    return ("rsync",)


def local_git_command(local_env: Environment) -> tuple[str, ...]:
    if local_env is Environment.WINDOWS:
        return ("git.exe",)
    return ("git",)


def ensure_local_rsync_available(local_env: Environment, runner: CommandRunner) -> None:
    command = rsync_command_for_environment(local_env)
    try:
        runner.run([*command, "--version"])
    except MissingDependencyError:
        raise
    except CommandExecutionError as exc:
        detail = command[0] if local_env is Environment.WSL else "wsl.exe --exec rsync"
        raise MissingDependencyError(
            f"wdsync: required program not found or unusable: {detail}"
        ) from exc


def local_path_for_peer(
    local_env: Environment,
    local_repo_root: Path,
    runner: CommandRunner,
) -> Path:
    return Path(local_path_for_peer_string(local_env, local_repo_root, runner))


def local_path_for_peer_string(
    local_env: Environment,
    local_repo_root: Path,
    runner: CommandRunner,
) -> str:
    if local_env is Environment.WSL:
        result = runner.run(["wslpath", "-w", str(local_repo_root)])
        return result.stdout_text().strip()
    if local_env is Environment.WINDOWS:
        result = runner.run([*_wsl_exec_command("wslpath", "-a", str(local_repo_root))])
        return result.stdout_text().strip()
    raise PeerConnectionError("wdsync: unsupported local environment for peer path translation")


def peer_native_to_local_path(
    local_env: Environment,
    peer_native_path: str,
    runner: CommandRunner,
) -> Path:
    if local_env is Environment.WSL:
        result = runner.run(["wslpath", peer_native_path])
        return Path(result.stdout_text().strip())
    if local_env is Environment.WINDOWS:
        result = runner.run([*_wsl_exec_command("wslpath", "-w", peer_native_path)])
        return Path(result.stdout_text().strip())
    raise PeerConnectionError("wdsync: unsupported local environment for peer path translation")


def local_rsync_root(
    local_env: Environment,
    local_repo_root: Path,
    runner: CommandRunner,
) -> str:
    if local_env is Environment.WINDOWS:
        result = runner.run([*_wsl_exec_command("wslpath", "-a", str(local_repo_root))])
        return result.stdout_text().strip()
    return str(local_repo_root)

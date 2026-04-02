from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from wdsync.core.models import (
    DirectionConfig,
    GitExecution,
    RepoEndpoint,
    SyncDirection,
    TransferExecution,
)
from wdsync.core.runner import CommandRunner


def _run(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture()
def git_runner(tmp_path: Path) -> CommandRunner:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git_exe = _write_executable(
        bin_dir / "git.exe",
        '#!/usr/bin/env bash\nexec git "$@"\n',
    )
    wslpath = _write_executable(
        bin_dir / "wslpath",
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "-w" ]]; then\n'
        '  if [[ "$2" =~ ^/mnt/([a-zA-Z])/(.*)$ ]]; then\n'
        "    drive=$(printf '%s' \"${BASH_REMATCH[1]}\" | tr '[:lower:]' '[:upper:]')\n"
        "    rest=${BASH_REMATCH[2]//\\//\\\\}\n"
        '    printf \'%s:\\\\%s\\n\' "$drive" "$rest"\n'
        "    exit 0\n"
        "  fi\n"
        '  if [[ "$2" == /home/* ]]; then\n'
        "    rest=${2//\\//\\\\}\n"
        "    printf '\\\\\\\\wsl.localhost\\\\Ubuntu%s\\n' \"$rest\"\n"
        "    exit 0\n"
        "  fi\n"
        "  printf '%s\\n' \"$2\"\n"
        "  exit 0\n"
        "fi\n"
        'if [[ "$1" == "-a" ]]; then\n'
        '  if [[ "$2" =~ ^([A-Za-z]):\\\\(.*)$ ]]; then\n'
        "    drive=$(printf '%s' \"${BASH_REMATCH[1]}\" | tr '[:upper:]' '[:lower:]')\n"
        "    rest=${BASH_REMATCH[2]//\\\\//}\n"
        '    printf \'/mnt/%s/%s\\n\' "$drive" "$rest"\n'
        "    exit 0\n"
        "  fi\n"
        "  printf '%s\\n' \"$2\"\n"
        "  exit 0\n"
        "fi\n"
        'if [[ "$1" =~ ^([A-Za-z]):\\\\(.*)$ ]]; then\n'
        "  drive=$(printf '%s' \"${BASH_REMATCH[1]}\" | tr '[:upper:]' '[:lower:]')\n"
        "  rest=${BASH_REMATCH[2]//\\\\//}\n"
        '  printf \'/mnt/%s/%s\\n\' "$drive" "$rest"\n'
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' \"$1\"\n"
        "exit 0\n",
    )
    wsl_exe = _write_executable(
        bin_dir / "wsl.exe",
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "--" || "$1" == "--exec" ]]; then\n'
        "  shift\n"
        "fi\n"
        'if [[ "$1" == "-d" ]]; then\n'
        "  shift 2\n"
        '  if [[ "$1" == "--" || "$1" == "--exec" ]]; then\n'
        "    shift\n"
        "  fi\n"
        "fi\n"
        'if [[ "$1" == "wslpath" ]]; then\n'
        "  shift\n"
        '  if [[ "$1" == "-a" || "$1" == "-w" ]]; then\n'
        '    if [[ "$1" == "-a" && "$2" =~ ^([A-Za-z]):\\\\(.*)$ ]]; then\n'
        "      drive=$(printf '%s' \"${BASH_REMATCH[1]}\" | tr '[:upper:]' '[:lower:]')\n"
        "      rest=${BASH_REMATCH[2]//\\\\//}\n"
        '      printf \'/mnt/%s/%s\\n\' "$drive" "$rest"\n'
        "      exit 0\n"
        "    fi\n"
        '    if [[ "$1" == "-w" && "$2" == /home/* ]]; then\n'
        "      rest=${2//\\//\\\\}\n"
        "      printf '\\\\\\\\wsl.localhost\\\\Ubuntu%s\\n' \"$rest\"\n"
        "      exit 0\n"
        "    fi\n"
        "    printf '%s\\n' \"$2\"\n"
        "    exit 0\n"
        "  fi\n"
        "  printf '%s\\n' \"$1\"\n"
        "  exit 0\n"
        "fi\n"
        'if [[ "$1" == "git" ]]; then\n'
        "  shift\n"
        '  exec git "$@"\n'
        "fi\n"
        'if [[ "$1" == "rsync" ]]; then\n'
        "  shift\n"
        '  exec rsync "$@"\n'
        "fi\n"
        'exec "$@"\n',
    )
    wdsync_exe = _write_executable(
        bin_dir / "wdsync.exe",
        '#!/usr/bin/env bash\nexec python -m wdsync "$@"\n',
    )
    return CommandRunner(
        {
            "git.exe": git_exe,
            "wsl.exe": wsl_exe,
            "wslpath": wslpath,
            "wdsync.exe": wdsync_exe,
        }
    )


@pytest.fixture()
def repo_factory(tmp_path: Path) -> Callable[..., Path]:
    def _factory(
        name: str,
        *,
        files: dict[str, str] | None = None,
        clone_from: Path | None = None,
    ) -> Path:
        repo_path = tmp_path / name
        if clone_from is not None:
            shutil.copytree(clone_from, repo_path)
            return repo_path

        repo_path.mkdir()
        _run(["git", "init", "-q"], cwd=repo_path)
        _run(["git", "config", "user.name", "wdsync-tests"], cwd=repo_path)
        _run(["git", "config", "user.email", "wdsync@example.com"], cwd=repo_path)
        for relative_path, content in (files or {}).items():
            file_path = repo_path / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        if files:
            _run(["git", "add", "."], cwd=repo_path)
            _run(["git", "commit", "-qm", "initial"], cwd=repo_path)
        return repo_path

    return _factory


@pytest.fixture()
def direction_config_factory() -> Callable[..., DirectionConfig]:
    def _factory(
        source_root: Path,
        dest_root: Path,
        direction: SyncDirection = SyncDirection.FETCH,
    ) -> DirectionConfig:
        if direction is SyncDirection.FETCH:
            return DirectionConfig(
                direction=direction,
                source=RepoEndpoint(root=source_root, native_root=str(source_root)),
                destination=RepoEndpoint(root=dest_root, native_root=str(dest_root)),
                source_git=GitExecution(command_argv=("git",), repo_native_root=str(source_root)),
                destination_git=GitExecution(
                    command_argv=("git",),
                    repo_native_root=str(dest_root),
                ),
                transfer=TransferExecution(
                    command_argv=("rsync",),
                    source_root=str(source_root),
                    dest_root=str(dest_root),
                ),
            )
        return DirectionConfig(
            direction=direction,
            source=RepoEndpoint(root=dest_root, native_root=str(dest_root)),
            destination=RepoEndpoint(root=source_root, native_root=str(source_root)),
            source_git=GitExecution(command_argv=("git",), repo_native_root=str(dest_root)),
            destination_git=GitExecution(
                command_argv=("git",),
                repo_native_root=str(source_root),
            ),
            transfer=TransferExecution(
                command_argv=("rsync",),
                source_root=str(dest_root),
                dest_root=str(source_root),
            ),
        )

    return _factory

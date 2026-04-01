from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from wdsync.core.models import ProjectConfig
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
        "  printf '%s\\n' \"$2\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
    )
    return CommandRunner({"git.exe": git_exe, "wslpath": wslpath})


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
def project_config_factory() -> Callable[[Path, Path], ProjectConfig]:
    def _factory(source_root: Path, dest_root: Path) -> ProjectConfig:
        return ProjectConfig(
            dest_root=dest_root,
            config_path=dest_root / ".wdsync",
            source_root=source_root,
            source_root_windows=str(source_root),
        )

    return _factory

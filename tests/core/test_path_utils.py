from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from wdsync.core import path_utils
from wdsync.core.exceptions import ShellDetectionError, UnsupportedEnvironmentError
from wdsync.core.runner import CommandRunner


def test_is_wsl_uses_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")

    assert path_utils.is_wsl() is True


def test_is_wsl_falls_back_to_kernel_release(monkeypatch: pytest.MonkeyPatch) -> None:
    def path_exists(self: Path) -> bool:
        del self
        return True

    def read_kernel_release(self: Path, encoding: str = "utf-8") -> str:
        del self, encoding
        return "6.6.87.2-microsoft-standard-WSL2"

    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    monkeypatch.setattr(path_utils.Path, "exists", path_exists)
    monkeypatch.setattr(path_utils.Path, "read_text", read_kernel_release)

    assert path_utils.is_wsl() is True


def test_ensure_wsl_environment_raises_when_not_in_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(path_utils, "is_wsl", lambda: False)

    with pytest.raises(UnsupportedEnvironmentError):
        path_utils.ensure_wsl_environment()


def test_normalize_and_validate_source_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    normalized = path_utils.normalize_source_path("~/project")

    assert normalized == tmp_path / "project"
    assert path_utils.is_wsl_windows_path(Path("/mnt/c/Users/example/project")) is True
    assert path_utils.is_wsl_windows_path(Path("/home/ephrem/project")) is False


def test_wsl_to_windows_path_uses_runner(git_runner: CommandRunner, tmp_path: Path) -> None:
    source_path = tmp_path / "project"

    assert path_utils.wsl_to_windows_path(source_path, git_runner) == str(source_path)


def test_detect_shell_prefers_explicit_then_env_then_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.setattr(path_utils, "_detect_parent_shell", lambda: "bash")

    assert path_utils.detect_shell("zsh") == "zsh"
    assert path_utils.detect_shell() == "fish"

    monkeypatch.delenv("SHELL", raising=False)
    assert path_utils.detect_shell() == "bash"


def test_detect_shell_raises_when_auto_detection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setattr(path_utils, "_detect_parent_shell", lambda: None)

    with pytest.raises(ShellDetectionError):
        path_utils.detect_shell()


def test_detect_parent_shell_reads_proc_comm(monkeypatch: pytest.MonkeyPatch) -> None:
    def path_exists(self: Path) -> bool:
        return self.as_posix() == "/proc/123/comm"

    def read_parent_comm(self: Path, encoding: str = "utf-8") -> str:
        del self, encoding
        return "zsh\n"

    detect_parent_shell = cast(
        Callable[[], str | None],
        path_utils._detect_parent_shell,  # pyright: ignore[reportPrivateUsage]
    )

    monkeypatch.setattr(path_utils.os, "getppid", lambda: 123)
    monkeypatch.setattr(path_utils.Path, "exists", path_exists)
    monkeypatch.setattr(path_utils.Path, "read_text", read_parent_comm)

    assert detect_parent_shell() == "zsh"

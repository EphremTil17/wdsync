from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from wdsync.config import (
    find_destination_root,
    init_project,
    load_project_config,
    parse_config_text,
)
from wdsync.exceptions import (
    ConfigValidationError,
    MissingConfigError,
    NotGitRepositoryError,
    SourceRepositoryError,
)
from wdsync.runner import CommandRunner, build_runner


def test_parse_config_text_supports_whitespace_and_comments() -> None:
    values = parse_config_text(
        """
        # comment
          SRC = /mnt/c/Users/example/project
        OTHER=value
        """
    )

    assert values["SRC"] == "/mnt/c/Users/example/project"
    assert values["OTHER"] == "value"


def test_parse_config_text_keeps_first_value_and_ignores_invalid_lines() -> None:
    values = parse_config_text(
        """
        SRC=/mnt/c/Users/example/one
        not valid
        SRC=/mnt/c/Users/example/two
        """
    )

    assert values["SRC"] == "/mnt/c/Users/example/one"


def test_find_destination_root_returns_repo_root(
    repo_factory: Callable[..., Path],
) -> None:
    repo = repo_factory("dest", files={"tracked.txt": "hello\n"})
    nested = repo / "nested/dir"
    nested.mkdir(parents=True)

    assert find_destination_root(build_runner(), cwd=nested) == repo


def test_find_destination_root_raises_outside_repo(tmp_path: Path) -> None:
    with pytest.raises(NotGitRepositoryError):
        find_destination_root(build_runner(), cwd=tmp_path)


def test_load_project_config_rejects_missing_src(
    tmp_path: Path,
    git_runner: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_true(path: Path) -> bool:
        del path
        return True

    def identity_wslpath(path: Path, runner: CommandRunner) -> str:
        del runner
        return str(path)

    monkeypatch.setattr("wdsync.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.config.wsl_to_windows_path", identity_wslpath)

    repo = tmp_path / "dest"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".wdsync").write_text("# empty\n", encoding="utf-8")

    def fake_find_destination_root(
        runner: CommandRunner,
        *,
        cwd: Path | None = None,
    ) -> Path:
        del runner, cwd
        return repo

    monkeypatch.setattr("wdsync.config.find_destination_root", fake_find_destination_root)

    with pytest.raises(ConfigValidationError):
        load_project_config(git_runner)


def test_load_project_config_rejects_missing_file(
    tmp_path: Path,
    git_runner: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "dest"
    repo.mkdir()
    (repo / ".git").mkdir()

    def fake_find_destination_root(
        runner: CommandRunner,
        *,
        cwd: Path | None = None,
    ) -> Path:
        del runner, cwd
        return repo

    monkeypatch.setattr("wdsync.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.config.find_destination_root", fake_find_destination_root)

    with pytest.raises(MissingConfigError):
        load_project_config(git_runner)


def test_load_project_config_rejects_non_windows_src_path(
    tmp_path: Path,
    git_runner: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "dest"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".wdsync").write_text("SRC=/home/ephrem/project\n", encoding="utf-8")

    def fake_find_destination_root(
        runner: CommandRunner,
        *,
        cwd: Path | None = None,
    ) -> Path:
        del runner, cwd
        return repo

    monkeypatch.setattr("wdsync.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.config.find_destination_root", fake_find_destination_root)

    with pytest.raises(ConfigValidationError):
        load_project_config(git_runner)


def test_load_project_config_rejects_missing_source_path(
    tmp_path: Path,
    git_runner: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "dest"
    repo.mkdir()
    (repo / ".git").mkdir()
    missing_source = tmp_path / "missing-source"
    (repo / ".wdsync").write_text(f"SRC={missing_source}\n", encoding="utf-8")

    def fake_find_destination_root(
        runner: CommandRunner,
        *,
        cwd: Path | None = None,
    ) -> Path:
        del runner, cwd
        return repo

    def always_true(path: Path) -> bool:
        del path
        return True

    def identity_wslpath(path: Path, runner: CommandRunner) -> str:
        del runner
        return str(path)

    monkeypatch.setattr("wdsync.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.config.find_destination_root", fake_find_destination_root)
    monkeypatch.setattr("wdsync.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.config.wsl_to_windows_path", identity_wslpath)

    with pytest.raises(ConfigValidationError):
        load_project_config(git_runner)


def test_load_project_config_rejects_non_git_source_repo(
    tmp_path: Path,
    git_runner: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "dest"
    repo.mkdir()
    (repo / ".git").mkdir()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (repo / ".wdsync").write_text(f"SRC={source_dir}\n", encoding="utf-8")

    def fake_find_destination_root(
        runner: CommandRunner,
        *,
        cwd: Path | None = None,
    ) -> Path:
        del runner, cwd
        return repo

    def always_true(path: Path) -> bool:
        del path
        return True

    def identity_wslpath(path: Path, runner: CommandRunner) -> str:
        del runner
        return str(path)

    monkeypatch.setattr("wdsync.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.config.find_destination_root", fake_find_destination_root)
    monkeypatch.setattr("wdsync.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.config.wsl_to_windows_path", identity_wslpath)

    with pytest.raises(SourceRepositoryError):
        load_project_config(git_runner)


def test_init_project_writes_config_and_git_exclude(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_true(path: Path) -> bool:
        del path
        return True

    def identity_wslpath(path: Path, runner: CommandRunner) -> str:
        del runner
        return str(path)

    monkeypatch.setattr("wdsync.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.config.wsl_to_windows_path", identity_wslpath)

    source_repo = repo_factory("source", files={"tracked.txt": "hello\n"})
    dest_repo = repo_factory("dest", files={"tracked.txt": "hello\n"})

    result = init_project(str(source_repo), git_runner, cwd=dest_repo)

    assert result.wrote_config is True
    config_text = (dest_repo / ".wdsync").read_text(encoding="utf-8").strip()
    assert config_text.endswith(f"SRC={source_repo}")
    assert ".wdsync" in result.exclude_path.read_text(encoding="utf-8")


def test_init_project_is_idempotent_when_config_already_matches(
    repo_factory: Callable[..., Path],
    git_runner: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_true(path: Path) -> bool:
        del path
        return True

    def identity_wslpath(path: Path, runner: CommandRunner) -> str:
        del runner
        return str(path)

    monkeypatch.setattr("wdsync.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.config.wsl_to_windows_path", identity_wslpath)

    source_repo = repo_factory("source", files={"tracked.txt": "hello\n"})
    dest_repo = repo_factory("dest", files={"tracked.txt": "hello\n"})

    first = init_project(str(source_repo), git_runner, cwd=dest_repo)
    second = init_project(str(source_repo), git_runner, cwd=dest_repo)

    assert first.wrote_config is True
    assert second.wrote_config is False
    assert second.updated_exclude is False

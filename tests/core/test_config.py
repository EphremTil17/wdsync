from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from wdsync.core.config import (
    _normalize_remote_url,  # pyright: ignore[reportPrivateUsage]
    find_destination_root,
    find_repo_root,
    init_project,
    initialize_repo,
    load_project_config,
    load_wdsync_config,
    match_identity,
    parse_config_text,
    resolve_identity,
    save_wdsync_config,
    state_dir,
)
from wdsync.core.exceptions import (
    ConfigValidationError,
    MissingConfigError,
    NotGitRepositoryError,
    SourceRepositoryError,
)
from wdsync.core.models import Identity, WdsyncConfig
from wdsync.core.runner import CommandRunner, build_runner


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

    monkeypatch.setattr("wdsync.core.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.core.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.core.config.wsl_to_windows_path", identity_wslpath)

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

    monkeypatch.setattr("wdsync.core.config.find_destination_root", fake_find_destination_root)

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

    monkeypatch.setattr("wdsync.core.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.core.config.find_destination_root", fake_find_destination_root)

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

    monkeypatch.setattr("wdsync.core.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.core.config.find_destination_root", fake_find_destination_root)

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

    monkeypatch.setattr("wdsync.core.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.core.config.find_destination_root", fake_find_destination_root)
    monkeypatch.setattr("wdsync.core.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.core.config.wsl_to_windows_path", identity_wslpath)

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

    monkeypatch.setattr("wdsync.core.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.core.config.find_destination_root", fake_find_destination_root)
    monkeypatch.setattr("wdsync.core.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.core.config.wsl_to_windows_path", identity_wslpath)

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

    monkeypatch.setattr("wdsync.core.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.core.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.core.config.wsl_to_windows_path", identity_wslpath)

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

    monkeypatch.setattr("wdsync.core.config.ensure_wsl_environment", lambda: None)
    monkeypatch.setattr("wdsync.core.config.is_wsl_windows_path", always_true)
    monkeypatch.setattr("wdsync.core.config.wsl_to_windows_path", identity_wslpath)

    source_repo = repo_factory("source", files={"tracked.txt": "hello\n"})
    dest_repo = repo_factory("dest", files={"tracked.txt": "hello\n"})

    first = init_project(str(source_repo), git_runner, cwd=dest_repo)
    second = init_project(str(source_repo), git_runner, cwd=dest_repo)

    assert first.wrote_config is True
    assert second.wrote_config is False
    assert second.updated_exclude is False


# ---------------------------------------------------------------------------
# New config system tests
# ---------------------------------------------------------------------------


def test_find_repo_root_returns_toplevel(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})
    nested = repo / "sub" / "dir"
    nested.mkdir(parents=True)

    assert find_repo_root(build_runner(), cwd=nested) == repo


def test_find_repo_root_raises_outside_repo(tmp_path: Path) -> None:
    with pytest.raises(NotGitRepositoryError):
        find_repo_root(build_runner(), cwd=tmp_path)


def test_state_dir_uses_git_derived_path(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})

    sdir = state_dir(repo, build_runner())

    assert "wdsync" in str(sdir)


def test_normalize_remote_url_strips_suffix_and_slash() -> None:
    assert (
        _normalize_remote_url("https://github.com/user/repo.git") == "https://github.com/user/repo"
    )
    assert _normalize_remote_url("https://github.com/user/repo/") == "https://github.com/user/repo"
    assert (
        _normalize_remote_url("https://github.com/user/repo.git/") == "https://github.com/user/repo"
    )
    assert _normalize_remote_url("git@github.com:user/repo.git") == "git@github.com:user/repo"


def test_resolve_identity_with_remote(
    repo_factory: Callable[..., Path],
) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})
    import subprocess

    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/user/repo.git"],
        check=True,
        capture_output=True,
    )

    identity = resolve_identity(repo, build_runner())

    assert identity.remote_url == "https://github.com/user/repo"
    assert len(identity.root_commits) == 1


def test_resolve_identity_without_remote(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})

    identity = resolve_identity(repo, build_runner())

    assert identity.remote_url is None
    assert len(identity.root_commits) == 1


def test_match_identity_by_remote_url() -> None:
    a = Identity(remote_url="https://github.com/user/repo", root_commits=("abc",))
    b = Identity(remote_url="https://github.com/user/repo.git", root_commits=("def",))

    assert match_identity(a, b) == "remote_url"


def test_match_identity_by_root_commits() -> None:
    a = Identity(remote_url=None, root_commits=("abc123",))
    b = Identity(remote_url=None, root_commits=("abc123",))

    assert match_identity(a, b) == "root_commits"


def test_match_identity_rejects_unrelated() -> None:
    a = Identity(remote_url=None, root_commits=("abc",))
    b = Identity(remote_url=None, root_commits=("def",))

    assert match_identity(a, b) is None


def test_initialize_repo_creates_config_and_marker(
    repo_factory: Callable[..., Path],
) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})

    result = initialize_repo(build_runner(), cwd=repo)

    assert result.config_path.exists()
    assert result.marker_path.exists()
    assert result.marker_path == repo / ".wdsync"
    assert result.identity.root_commits


def test_initialize_repo_is_idempotent(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})

    first = initialize_repo(build_runner(), cwd=repo)
    second = initialize_repo(build_runner(), cwd=repo)

    assert first.identity == second.identity


def test_save_and_load_config_roundtrip(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})
    runner = build_runner()
    sdir = state_dir(repo, runner)
    sdir.mkdir(parents=True, exist_ok=True)

    identity = Identity(remote_url="https://github.com/user/repo", root_commits=("abc123",))
    config = WdsyncConfig(version=1, identity=identity, peer=None)
    save_wdsync_config(config, sdir)

    loaded = load_wdsync_config(runner, cwd=repo)

    assert loaded.identity.remote_url == "https://github.com/user/repo"
    assert loaded.identity.root_commits == ("abc123",)
    assert loaded.peer is None


def test_load_wdsync_config_raises_on_missing(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})

    with pytest.raises(MissingConfigError):
        load_wdsync_config(build_runner(), cwd=repo)

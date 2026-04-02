from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from wdsync.core.config import (
    _normalize_remote_url,  # pyright: ignore[reportPrivateUsage]
    find_repo_root,
    initialize_repo,
    load_wdsync_config,
    match_identity,
    resolve_identity,
    save_wdsync_config,
    state_dir,
)
from wdsync.core.deinit import deinitialize_repo
from wdsync.core.exceptions import (
    ConfigValidationError,
    MissingConfigError,
    NotGitRepositoryError,
)
from wdsync.core.models import Identity, PeerConfig, RuntimePreferences, WdsyncConfig
from wdsync.core.runner import build_runner


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
    assert second.already_initialized is True


def test_initialize_repo_preserves_existing_peer_and_runtime(
    repo_factory: Callable[..., Path],
) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})
    runner = build_runner()

    initialize_repo(runner, cwd=repo)
    sdir = state_dir(repo, runner)
    config = load_wdsync_config(runner, cwd=repo)
    save_wdsync_config(
        WdsyncConfig(
            version=config.version,
            identity=config.identity,
            peer=PeerConfig(
                command_argv=("wsl.exe", "--exec", "/home/user/.local/bin/wdsync"),
                root=Path(r"\\wsl.localhost\Ubuntu\home\user\repo"),
                root_native="/home/user/repo",
            ),
            runtime=RuntimePreferences(
                windows_peer_command_argv=("wdsync.exe",),
                wsl_peer_command_argv=("/home/user/.local/bin/wdsync",),
                wsl_distro="Ubuntu-24.04",
            ),
        ),
        sdir,
    )

    result = initialize_repo(runner, cwd=repo)
    loaded = load_wdsync_config(runner, cwd=repo)

    assert result.already_initialized is True
    assert loaded.peer == PeerConfig(
        command_argv=("wsl.exe", "--exec", "/home/user/.local/bin/wdsync"),
        root=Path(r"\\wsl.localhost\Ubuntu\home\user\repo"),
        root_native="/home/user/repo",
    )
    assert loaded.runtime == RuntimePreferences(
        windows_peer_command_argv=("wdsync.exe",),
        wsl_peer_command_argv=("/home/user/.local/bin/wdsync",),
        wsl_distro="Ubuntu-24.04",
    )


def test_deinitialize_repo_removes_wdsync_state(
    repo_factory: Callable[..., Path],
) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})
    runner = build_runner()

    initialize_repo(runner, cwd=repo)
    sdir = state_dir(repo, runner)
    (sdir / "manifest.json").write_text("{}", encoding="utf-8")
    (sdir / "wdsync.log").write_text("log", encoding="utf-8")

    result = deinitialize_repo(runner, cwd=repo)
    exclude_path = repo / ".git" / "info" / "exclude"

    assert result.already_deinitialized is False
    assert result.removed_config is True
    assert result.removed_manifest is True
    assert result.removed_log is True
    assert result.removed_marker is True
    assert result.removed_exclude_entry is True
    assert result.removed_state_dir is True
    assert not result.marker_path.exists()
    assert not sdir.exists()
    assert ".wdsync" not in exclude_path.read_text(encoding="utf-8")


def test_deinitialize_repo_preserves_unknown_state_files(
    repo_factory: Callable[..., Path],
) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})
    runner = build_runner()

    initialize_repo(runner, cwd=repo)
    sdir = state_dir(repo, runner)
    extra = sdir / "keep.me"
    extra.write_text("custom", encoding="utf-8")

    result = deinitialize_repo(runner, cwd=repo)

    assert result.removed_config is True
    assert result.removed_state_dir is False
    assert result.leftover_state_files == ("keep.me",)
    assert extra.exists()


def test_deinitialize_repo_is_idempotent(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})
    runner = build_runner()

    initialize_repo(runner, cwd=repo)
    deinitialize_repo(runner, cwd=repo)
    second = deinitialize_repo(runner, cwd=repo)

    assert second.already_deinitialized is True


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


def test_save_and_load_runtime_preferences_roundtrip(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})
    runner = build_runner()
    sdir = state_dir(repo, runner)
    sdir.mkdir(parents=True, exist_ok=True)

    config = WdsyncConfig(
        version=1,
        identity=Identity(remote_url="https://github.com/user/repo", root_commits=("abc123",)),
        peer=None,
        runtime=RuntimePreferences(
            windows_peer_command_argv=("python.exe", "-m", "wdsync"),
            wsl_peer_command_argv=("python", "-m", "wdsync"),
            wsl_distro="Ubuntu-24.04",
        ),
    )
    save_wdsync_config(config, sdir)

    loaded = load_wdsync_config(runner, cwd=repo)

    assert loaded.runtime == config.runtime


def test_load_wdsync_config_raises_on_missing(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("test", files={"a.txt": "a\n"})

    with pytest.raises(MissingConfigError):
        load_wdsync_config(build_runner(), cwd=repo)


def test_load_config_rejects_incomplete_peer_block(repo_factory: Callable[..., Path]) -> None:
    """A peer block with empty fields should raise ConfigValidationError."""
    import json as json_mod

    repo = repo_factory("test", files={"a.txt": "a\n"})
    runner = build_runner()
    sdir = state_dir(repo, runner)
    sdir.mkdir(parents=True, exist_ok=True)
    config_file = sdir / "config.json"
    config_file.write_text(
        json_mod.dumps(
            {
                "version": 1,
                "identity": {"remote_url": None, "root_commits": ["abc"]},
                "peer": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match="incomplete peer block"):
        load_wdsync_config(runner, cwd=repo)


def test_load_config_rejects_non_object_peer_block(repo_factory: Callable[..., Path]) -> None:
    import json as json_mod

    repo = repo_factory("test", files={"a.txt": "a\n"})
    runner = build_runner()
    sdir = state_dir(repo, runner)
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "config.json").write_text(
        json_mod.dumps(
            {
                "version": 1,
                "identity": {"remote_url": None, "root_commits": ["abc"]},
                "peer": "broken",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match="invalid peer block"):
        load_wdsync_config(runner, cwd=repo)

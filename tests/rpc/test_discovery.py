from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from wdsync.core.config import resolve_identity
from wdsync.core.environment import Environment
from wdsync.core.models import Identity
from wdsync.core.runner import build_runner
from wdsync.rpc import discovery
from wdsync.rpc.discovery import (
    _project_search_dirs,  # pyright: ignore[reportPrivateUsage]
    locate_matching_repo,
)


def _add_remote(repo: Path, url: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", url],
        check=True,
        capture_output=True,
    )


def _none_stub(*_args: object, **_kwargs: object) -> None:
    return None


def _search_dirs_stub(
    scan_dir: Path,
) -> Callable[[Environment], tuple[Path, ...]]:
    """Return a typed stub that replaces ``_project_search_dirs``."""

    def _stub(env: Environment) -> tuple[Path, ...]:
        return (scan_dir,)

    return _stub


def _match_stub(repo_path: Path, peer_identity: Identity, runner: object) -> str:
    del repo_path, peer_identity, runner
    return "remote_url"


def _mounted_repo_root_stub(
    runner: object,
    *,
    cwd: Path | None = None,
) -> Path:
    del runner, cwd
    return Path("/mnt/c/Users/user/repo")


def _windows_wsl_mount_repo_root_stub(
    runner: object,
    *,
    cwd: Path | None = None,
) -> Path:
    del runner, cwd
    return Path(r"\\wsl.localhost\Ubuntu\home\user\repo")


def test_cached_root_found(repo_factory: Callable[..., Path]) -> None:
    repo = repo_factory("match", files={"a.txt": "a\n"})
    _add_remote(repo, "https://github.com/user/repo.git")
    runner = build_runner()
    identity = resolve_identity(repo, runner)

    result = locate_matching_repo(identity, runner, cached_root=repo)

    assert result is not None
    found_root, matched_by = result
    assert found_root == repo
    assert matched_by in ("remote_url", "root_commits")


def test_cached_root_no_match_falls_through(
    repo_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_a = repo_factory("a", files={"a.txt": "a\n"})
    repo_b = repo_factory("b", files={"b.txt": "b\n"})
    _add_remote(repo_a, "https://github.com/user/repo-a.git")
    _add_remote(repo_b, "https://github.com/user/repo-b.git")
    runner = build_runner()
    identity_b = resolve_identity(repo_b, runner)

    # cached_root is repo_a but we're looking for repo_b's identity
    # Mock _check_cwd and _scan_candidates so we know it fell through
    monkeypatch.setattr(discovery, "_check_cwd", _none_stub)
    monkeypatch.setattr(discovery, "_scan_candidates", _none_stub)

    result = locate_matching_repo(identity_b, runner, cached_root=repo_a)

    assert result is None


def test_cwd_match_found(
    repo_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = repo_factory("cwd_repo", files={"a.txt": "a\n"})
    runner = build_runner()
    identity = resolve_identity(repo, runner)

    monkeypatch.chdir(repo)

    # Only rely on cwd — disable cached_root and scanning
    monkeypatch.setattr(discovery, "_scan_candidates", _none_stub)

    result = locate_matching_repo(identity, runner)

    assert result is not None
    assert result[0] == repo


def test_cwd_cross_mounted_repo_is_ignored_on_wsl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = build_runner()
    identity = Identity(remote_url="https://github.com/user/repo", root_commits=("abc",))

    monkeypatch.setattr(discovery, "detect_environment", lambda: Environment.WSL)
    monkeypatch.setattr(discovery, "find_repo_root", _mounted_repo_root_stub)
    monkeypatch.setattr(discovery, "_check_repo", _match_stub)
    monkeypatch.setattr(discovery, "_scan_candidates", _none_stub)

    result = locate_matching_repo(identity, runner)

    assert result is None


def test_cached_cross_mounted_repo_is_ignored_on_wsl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = build_runner()
    identity = Identity(remote_url="https://github.com/user/repo", root_commits=("abc",))

    monkeypatch.setattr(discovery, "detect_environment", lambda: Environment.WSL)
    monkeypatch.setattr(discovery, "_check_repo", _match_stub)
    monkeypatch.setattr(discovery, "_check_cwd", _none_stub)
    monkeypatch.setattr(discovery, "_scan_candidates", _none_stub)

    result = locate_matching_repo(identity, runner, cached_root=Path("/mnt/c/Users/user/repo"))

    assert result is None


def test_cwd_wsl_mount_is_ignored_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = build_runner()
    identity = Identity(remote_url="https://github.com/user/repo", root_commits=("abc",))

    monkeypatch.setattr(discovery, "detect_environment", lambda: Environment.WINDOWS)
    monkeypatch.setattr(discovery, "find_repo_root", _windows_wsl_mount_repo_root_stub)
    monkeypatch.setattr(discovery, "_check_repo", _match_stub)
    monkeypatch.setattr(discovery, "_scan_candidates", _none_stub)

    result = locate_matching_repo(identity, runner)

    assert result is None


def test_finds_repo_in_search_dir(
    repo_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = repo_factory("target", files={"a.txt": "a\n"})
    _add_remote(repo, "https://github.com/user/repo.git")
    runner = build_runner()
    identity = resolve_identity(repo, runner)

    # Move the repo under a "projects" dir to simulate scan
    scan_dir = tmp_path / "projects"
    scan_dir.mkdir()
    target = scan_dir / "target"
    repo.rename(target)

    monkeypatch.setattr(discovery, "_check_cwd", _none_stub)
    monkeypatch.setattr(discovery, "_project_search_dirs", _search_dirs_stub(scan_dir))

    result = locate_matching_repo(identity, runner)

    assert result is not None
    assert result[0] == target


def test_no_match_returns_none(
    repo_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = repo_factory("unrelated", files={"a.txt": "a\n"})
    runner = build_runner()

    # Search with an identity that won't match
    fake_identity = Identity(remote_url="https://github.com/other/repo", root_commits=("000",))

    scan_dir = tmp_path / "projects"
    scan_dir.mkdir()
    target = scan_dir / "unrelated"
    repo.rename(target)

    monkeypatch.setattr(discovery, "_check_cwd", _none_stub)
    monkeypatch.setattr(discovery, "_project_search_dirs", _search_dirs_stub(scan_dir))

    result = locate_matching_repo(fake_identity, runner)

    assert result is None


def test_bounded_walk_respects_depth(
    repo_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Create a repo at depth 3 — should NOT be found with max_depth=2
    deep_parent = tmp_path / "projects" / "level1" / "level2" / "level3"
    deep_parent.mkdir(parents=True)
    repo = repo_factory("deep", files={"a.txt": "a\n"})
    target = deep_parent / "deep"
    repo.rename(target)
    runner = build_runner()
    identity = resolve_identity(target, runner)

    scan_dir = tmp_path / "projects"
    monkeypatch.setattr(discovery, "_check_cwd", _none_stub)
    monkeypatch.setattr(discovery, "_project_search_dirs", _search_dirs_stub(scan_dir))

    result = locate_matching_repo(identity, runner)

    assert result is None


def test_permission_error_skipped(
    repo_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scan_dir = tmp_path / "projects"
    scan_dir.mkdir()
    restricted = scan_dir / "noaccess"
    restricted.mkdir()
    restricted.chmod(0o000)

    try:
        fake_identity = Identity(remote_url=None, root_commits=("000",))
        runner = build_runner()

        monkeypatch.setattr(discovery, "_check_cwd", _none_stub)
        monkeypatch.setattr(discovery, "_project_search_dirs", _search_dirs_stub(scan_dir))

        result = locate_matching_repo(fake_identity, runner)

        assert result is None
    finally:
        restricted.chmod(0o755)


def test_search_dirs_environment_aware() -> None:
    windows_dirs = _project_search_dirs(Environment.WINDOWS)
    wsl_dirs = _project_search_dirs(Environment.WSL)
    linux_dirs = _project_search_dirs(Environment.LINUX)

    # Windows has "source/repos" and "Documents/Projects"
    windows_names = {d.name for d in windows_dirs}
    assert "repos" in windows_names
    assert any("Documents" in str(d) for d in windows_dirs)

    # WSL and Linux share layout
    assert wsl_dirs == linux_dirs
    wsl_names = {d.name for d in wsl_dirs}
    assert "projects" in wsl_names
    assert "src" in wsl_names

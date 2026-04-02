from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from wdsync.core.codec import wdsync_config_from_object, wdsync_config_to_dict
from wdsync.core.environment import detect_environment
from wdsync.core.exceptions import (
    CommandExecutionError,
    ConfigValidationError,
    MissingConfigError,
    NotGitRepositoryError,
)
from wdsync.core.interop import ensure_local_rsync_available
from wdsync.core.models import Identity, InitializeResult, WdsyncConfig
from wdsync.core.runner import CommandRunner

CONFIG_FILENAME = ".wdsync"


# ---------------------------------------------------------------------------
# Config system (JSON-based, identity-aware)
# ---------------------------------------------------------------------------

_CONFIG_VERSION = 1
_CONFIG_FILENAME_JSON = "config.json"
_MARKER_CONTENT = (
    "# This repository is linked by wdsync.\n# Configuration: .git/wdsync/config.json\n"
)


def find_repo_root(runner: CommandRunner, *, cwd: Path | None = None) -> Path:
    try:
        result = runner.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    except CommandExecutionError as exc:
        raise NotGitRepositoryError("wdsync: not inside a git repository") from exc
    return Path(result.stdout_text().strip())


def state_dir(repo_root: Path, runner: CommandRunner) -> Path:
    result = runner.run(["git", "-C", str(repo_root), "rev-parse", "--git-path", "wdsync"])
    raw = Path(result.stdout_text().strip())
    if raw.is_absolute():
        return raw
    return repo_root / raw


def _git_exclude_path(dest_root: Path, runner: CommandRunner) -> Path:
    result = runner.run(["git", "-C", str(dest_root), "rev-parse", "--git-path", "info/exclude"])
    return Path(result.stdout_text().strip())


def _ensure_exclude_contains(exclude_path: Path, pattern: str) -> bool:
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    lines = [line.strip() for line in existing.splitlines()]
    if pattern in lines:
        return False

    prefix = "" if not existing or existing.endswith("\n") else "\n"
    exclude_path.write_text(f"{existing}{prefix}{pattern}\n", encoding="utf-8")
    return True


def _marker_is_current(marker_path: Path) -> bool:
    if not marker_path.exists():
        return False
    try:
        return marker_path.read_text(encoding="utf-8") == _MARKER_CONTENT
    except OSError:
        return False


def _get_remote_url(repo_root: Path, git_cmd: str, runner: CommandRunner) -> str | None:
    try:
        result = runner.run(
            [git_cmd, "-C", str(repo_root), "remote", "get-url", "origin"],
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout_text().strip() or None
    except (CommandExecutionError, OSError):
        return None


def _normalize_remote_url(url: str) -> str:
    return url.rstrip("/").removesuffix(".git").rstrip("/")


def _get_root_commits(repo_root: Path, runner: CommandRunner) -> tuple[str, ...]:
    result = runner.run(
        ["git", "-C", str(repo_root), "rev-list", "--max-parents=0", "HEAD"],
        check=False,
    )
    if result.returncode != 0:
        return ()
    lines = result.stdout_text().strip().splitlines()
    return tuple(sorted(line.strip() for line in lines if line.strip()))


def resolve_identity(repo_root: Path, runner: CommandRunner) -> Identity:
    raw_url = _get_remote_url(repo_root, "git", runner)
    normalized_url = _normalize_remote_url(raw_url) if raw_url else None
    root_commits = _get_root_commits(repo_root, runner)
    if not root_commits:
        raise ConfigValidationError("wdsync: repo has no commits — cannot resolve identity")
    return Identity(remote_url=normalized_url, root_commits=root_commits)


def match_identity(local: Identity, remote: Identity) -> str | None:
    if (
        local.remote_url
        and remote.remote_url
        and _normalize_remote_url(local.remote_url) == _normalize_remote_url(remote.remote_url)
    ):
        return "remote_url"
    if local.root_commits and remote.root_commits and local.root_commits == remote.root_commits:
        return "root_commits"
    return None


def save_wdsync_config(config: WdsyncConfig, sdir: Path) -> None:
    sdir.mkdir(parents=True, exist_ok=True)
    config_file = sdir / _CONFIG_FILENAME_JSON
    config_file.write_text(
        json.dumps(wdsync_config_to_dict(config), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_wdsync_config(runner: CommandRunner, *, cwd: Path | None = None) -> WdsyncConfig:
    config, _, _ = load_wdsync_config_with_paths(runner, cwd=cwd)
    return config


def load_wdsync_config_with_paths(
    runner: CommandRunner, *, cwd: Path | None = None
) -> tuple[WdsyncConfig, Path, Path]:
    """Load config and return ``(config, repo_root, state_dir)``."""
    repo_root = find_repo_root(runner, cwd=cwd)
    sdir = state_dir(repo_root, runner)
    config_file = sdir / _CONFIG_FILENAME_JSON
    if not config_file.exists():
        raise MissingConfigError("wdsync: not initialized. Run 'wdsync init' first.")
    try:
        raw: object = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"wdsync: config.json is malformed: {exc}") from exc
    data = cast(dict[str, Any], raw) if isinstance(raw, dict) else None
    if data is None:
        raise ConfigValidationError("wdsync: config.json must be a JSON object")
    if data.get("version") != _CONFIG_VERSION:
        raise ConfigValidationError(f"wdsync: unsupported config version: {data.get('version')}")
    return wdsync_config_from_object(data), repo_root, sdir


def initialize_repo(runner: CommandRunner, *, cwd: Path | None = None) -> InitializeResult:
    repo_root = find_repo_root(runner, cwd=cwd)
    ensure_local_rsync_available(detect_environment(), runner)
    sdir = state_dir(repo_root, runner)
    identity = resolve_identity(repo_root, runner)

    marker = repo_root / CONFIG_FILENAME
    existing_config: WdsyncConfig | None = None
    try:
        existing_config, _, _ = load_wdsync_config_with_paths(runner, cwd=repo_root)
    except MissingConfigError:
        existing_config = None

    exclude_path = _git_exclude_path(repo_root, runner)
    exclude_updated = _ensure_exclude_contains(exclude_path, CONFIG_FILENAME)
    marker_current = _marker_is_current(marker)

    if (
        existing_config is not None
        and existing_config.identity == identity
        and marker_current
        and not exclude_updated
    ):
        return InitializeResult(
            repo_root=repo_root,
            config_path=sdir / _CONFIG_FILENAME_JSON,
            marker_path=marker,
            identity=identity,
            already_initialized=True,
        )

    config = (
        WdsyncConfig(
            version=_CONFIG_VERSION,
            identity=identity,
            peer=existing_config.peer,
            runtime=existing_config.runtime,
        )
        if existing_config is not None
        else WdsyncConfig(version=_CONFIG_VERSION, identity=identity, peer=None)
    )
    save_wdsync_config(config, sdir)

    if not marker_current:
        marker.write_text(_MARKER_CONTENT, encoding="utf-8")

    return InitializeResult(
        repo_root=repo_root,
        config_path=sdir / _CONFIG_FILENAME_JSON,
        marker_path=marker,
        identity=identity,
    )

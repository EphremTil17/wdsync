from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from wdsync.core.exceptions import (
    CommandExecutionError,
    ConfigValidationError,
    MissingConfigError,
    NotGitRepositoryError,
    SourceRepositoryError,
)
from wdsync.core.models import (
    Identity,
    InitializeResult,
    InitResult,
    PeerConfig,
    ProjectConfig,
    WdsyncConfig,
)
from wdsync.core.path_utils import (
    ensure_wsl_environment,
    is_wsl_windows_path,
    normalize_source_path,
    wsl_to_windows_path,
)
from wdsync.core.runner import CommandRunner

CONFIG_FILENAME = ".wdsync"
_CONFIG_LINE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.*)$")


def find_destination_root(runner: CommandRunner, *, cwd: Path | None = None) -> Path:
    try:
        result = runner.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    except CommandExecutionError as exc:
        raise NotGitRepositoryError("wdsync: not inside a git repository") from exc
    return Path(result.stdout_text().strip())


def parse_config_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _CONFIG_LINE.match(raw_line)
        if match is None:
            continue
        key, value = match.groups()
        if key not in values:
            values[key] = value.strip()
    return values


def _build_project_config(
    *,
    dest_root: Path,
    config_path: Path,
    raw_source: str,
    runner: CommandRunner,
) -> ProjectConfig:
    source_root = normalize_source_path(raw_source)
    if not is_wsl_windows_path(source_root):
        raise ConfigValidationError(
            "wdsync: expected SRC to be a WSL-mounted Windows path like /mnt/c/Users/you/project"
        )
    if not source_root.is_dir():
        raise ConfigValidationError(f"wdsync: SRC path does not exist: {source_root}")

    source_root_windows = wsl_to_windows_path(source_root, runner)
    try:
        runner.run(["git.exe", "-C", source_root_windows, "rev-parse", "--show-toplevel"])
    except CommandExecutionError as exc:
        raise SourceRepositoryError(
            f"wdsync: source path is not a Git repository: {source_root}"
        ) from exc

    return ProjectConfig(
        dest_root=dest_root,
        config_path=config_path,
        source_root=source_root,
        source_root_windows=source_root_windows,
    )


def load_project_config(runner: CommandRunner, *, cwd: Path | None = None) -> ProjectConfig:
    ensure_wsl_environment()
    dest_root = find_destination_root(runner, cwd=cwd)
    config_path = dest_root / CONFIG_FILENAME
    if not config_path.is_file():
        raise MissingConfigError(
            f"wdsync: no {CONFIG_FILENAME} file found at {dest_root}\n"
            "  Create one manually or run: wdsync init /mnt/c/path/to/project"
        )

    raw_values = parse_config_text(config_path.read_text(encoding="utf-8"))
    raw_source = raw_values.get("SRC")
    if raw_source is None or not raw_source.strip():
        raise ConfigValidationError("wdsync: .wdsync is missing a SRC= entry")

    return _build_project_config(
        dest_root=dest_root,
        config_path=config_path,
        raw_source=raw_source,
        runner=runner,
    )


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


def _get_remote_url(repo_root: Path, git_cmd: str, runner: CommandRunner) -> str | None:
    try:
        result = runner.run(
            [git_cmd, "-C", str(repo_root), "remote", "get-url", "origin"],
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout_text().strip() or None
    except Exception:  # noqa: BLE001
        return None


def _remotes_match(a: str, b: str) -> bool:
    return a.rstrip("/").rstrip(".git") == b.rstrip("/").rstrip(".git")


def _common_project_dirs(user_dir: Path) -> tuple[Path, ...]:
    return (
        user_dir / "source" / "repos",
        user_dir / "Documents" / "Projects",
        user_dir / "Projects",
        user_dir / "repos",
        user_dir / "dev",
    )


def discover_matching_windows_repo(dest_root: Path, runner: CommandRunner) -> Path | None:
    dest_remote = _get_remote_url(dest_root, "git", runner)
    if not dest_remote:
        return None

    mnt_users = Path("/mnt/c/Users")
    if not mnt_users.is_dir():
        return None

    try:
        user_dirs = list(mnt_users.iterdir())
    except PermissionError:
        return None

    for user_dir in user_dirs:
        if not user_dir.is_dir() or user_dir.name in ("Public", "Default", "Default User"):
            continue
        for candidate_root in _common_project_dirs(user_dir):
            if not candidate_root.is_dir():
                continue
            try:
                subdirs = list(candidate_root.iterdir())
            except PermissionError:
                continue
            for subdir in subdirs:
                if not (subdir / ".git").is_dir():
                    continue
                candidate_remote = _get_remote_url(subdir, "git.exe", runner)
                if candidate_remote and _remotes_match(dest_remote, candidate_remote):
                    return subdir
    return None


def init_project(
    source: str | None,
    runner: CommandRunner,
    *,
    cwd: Path | None = None,
) -> InitResult:
    ensure_wsl_environment()
    dest_root = find_destination_root(runner, cwd=cwd)
    config_path = dest_root / CONFIG_FILENAME

    raw_source = source
    if raw_source is None:
        discovered = discover_matching_windows_repo(dest_root, runner)
        if discovered is not None:
            raw_source = str(discovered)
    if raw_source is None:
        raise MissingConfigError(
            "wdsync: could not auto-detect a matching Windows repo.\n"
            "  Provide the source path explicitly: wdsync init /mnt/c/path/to/repo"
        )

    config = _build_project_config(
        dest_root=dest_root,
        config_path=config_path,
        raw_source=raw_source,
        runner=runner,
    )

    desired_content = "\n".join(
        [
            "# Windows source repo mirrored into this WSL repo",
            "# Generated by wdsync init",
            f"SRC={config.source_root}",
            "",
        ]
    )
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    wrote_config = existing != desired_content
    if wrote_config:
        config_path.write_text(desired_content, encoding="utf-8")

    exclude_path = _git_exclude_path(dest_root, runner)
    updated_exclude = _ensure_exclude_contains(exclude_path, CONFIG_FILENAME)
    return InitResult(
        config=config,
        wrote_config=wrote_config,
        exclude_path=exclude_path,
        updated_exclude=updated_exclude,
    )


# ---------------------------------------------------------------------------
# New config system (JSON-based, identity-aware)
# ---------------------------------------------------------------------------

_CONFIG_VERSION = 1
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


def _config_to_dict(config: WdsyncConfig) -> dict[str, object]:
    result: dict[str, object] = {
        "version": config.version,
        "identity": {
            "remote_url": config.identity.remote_url,
            "root_commits": list(config.identity.root_commits),
        },
        "peer": None,
    }
    if config.peer is not None:
        result["peer"] = {
            "command_argv": list(config.peer.command_argv),
            "root": str(config.peer.root),
            "root_native": config.peer.root_native,
        }
    return result


def _config_from_dict(data: dict[str, Any]) -> WdsyncConfig:
    raw_identity: object = data.get("identity", {})
    if not isinstance(raw_identity, dict):
        raise ConfigValidationError("wdsync: config.json has invalid identity block")
    id_dict = cast(dict[str, Any], raw_identity)

    raw_url: object = id_dict.get("remote_url")
    remote_url = str(raw_url) if isinstance(raw_url, str) else None

    raw_commits: object = id_dict.get("root_commits", [])
    if not isinstance(raw_commits, list):
        raw_commits = []
    commits_any: list[Any] = cast(list[Any], raw_commits)
    commits_list: list[str] = [str(c) for c in commits_any if isinstance(c, str)]

    identity = Identity(remote_url=remote_url, root_commits=tuple(sorted(commits_list)))

    peer: PeerConfig | None = None
    raw_peer: object = data.get("peer")
    if isinstance(raw_peer, dict):
        p = cast(dict[str, Any], raw_peer)
        raw_argv: object = p.get("command_argv", [])
        if not isinstance(raw_argv, list):
            raw_argv = []
        argv_any: list[Any] = cast(list[Any], raw_argv)
        argv = tuple(str(a) for a in argv_any if isinstance(a, str))
        peer = PeerConfig(
            command_argv=argv,
            root=Path(str(p.get("root", ""))),
            root_native=str(p.get("root_native", "")),
        )

    version: object = data.get("version", 1)
    return WdsyncConfig(
        version=int(version) if isinstance(version, int) else 1,
        identity=identity,
        peer=peer,
    )


def save_wdsync_config(config: WdsyncConfig, sdir: Path) -> None:
    sdir.mkdir(parents=True, exist_ok=True)
    config_file = sdir / "config.json"
    config_file.write_text(
        json.dumps(_config_to_dict(config), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_wdsync_config(runner: CommandRunner, *, cwd: Path | None = None) -> WdsyncConfig:
    repo_root = find_repo_root(runner, cwd=cwd)
    sdir = state_dir(repo_root, runner)
    config_file = sdir / "config.json"
    if not config_file.exists():
        raise MissingConfigError("wdsync: not initialized. Run 'wdsync init' first.")
    try:
        raw: object = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"wdsync: config.json is malformed: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigValidationError("wdsync: config.json must be a JSON object")
    data = cast(dict[str, Any], raw)
    if data.get("version") != _CONFIG_VERSION:
        raise ConfigValidationError(f"wdsync: unsupported config version: {data.get('version')}")
    return _config_from_dict(data)


def initialize_repo(runner: CommandRunner, *, cwd: Path | None = None) -> InitializeResult:
    repo_root = find_repo_root(runner, cwd=cwd)
    sdir = state_dir(repo_root, runner)
    identity = resolve_identity(repo_root, runner)

    config = WdsyncConfig(version=_CONFIG_VERSION, identity=identity, peer=None)
    save_wdsync_config(config, sdir)

    marker = repo_root / CONFIG_FILENAME
    marker.write_text(_MARKER_CONTENT, encoding="utf-8")

    exclude_path = _git_exclude_path(repo_root, runner)
    _ensure_exclude_contains(exclude_path, CONFIG_FILENAME)

    return InitializeResult(
        repo_root=repo_root,
        config_path=sdir / "config.json",
        marker_path=marker,
        identity=identity,
    )

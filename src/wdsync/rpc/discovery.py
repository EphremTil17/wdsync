from __future__ import annotations

from pathlib import Path

from wdsync.core.config import find_repo_root, match_identity, resolve_identity
from wdsync.core.environment import Environment, detect_environment
from wdsync.core.exceptions import NotGitRepositoryError, WdSyncError
from wdsync.core.models import Identity
from wdsync.core.runner import CommandRunner


def locate_matching_repo(
    peer_identity: Identity,
    runner: CommandRunner,
    *,
    cached_root: Path | None = None,
) -> tuple[Path, str] | None:
    """Layered search for a local repo matching *peer_identity*.

    Only repos native to the peer environment are considered candidates.
    Mounted views of the opposite environment are intentionally rejected,
    even if they share the same identity, so bilateral connect binds the
    two real working copies rather than rediscovering the initiator repo
    through a filesystem bridge.

    Returns ``(repo_root, matched_by)`` on success, or ``None``.
    """
    env = detect_environment()

    # Fast path 1: cached last-known root (instant on reconnects)
    if cached_root is not None and _is_native_repo_root(cached_root, env):
        result = _check_repo(cached_root, peer_identity, runner)
        if result is not None:
            return cached_root, result

    # Fast path 2: peer process cwd
    cwd_match = _check_cwd(peer_identity, runner, env=env)
    if cwd_match is not None:
        return cwd_match

    # Slow path: bounded scan of common project directories
    search_dirs = _project_search_dirs(env)
    return _scan_candidates(search_dirs, peer_identity, runner)


def _check_cwd(
    peer_identity: Identity,
    runner: CommandRunner,
    *,
    env: Environment,
) -> tuple[Path, str] | None:
    try:
        repo_root = find_repo_root(runner, cwd=Path.cwd())
    except (NotGitRepositoryError, OSError):
        return None
    if not _is_native_repo_root(repo_root, env):
        return None
    matched_by = _check_repo(repo_root, peer_identity, runner)
    if matched_by is not None:
        return repo_root, matched_by
    return None


def _is_native_repo_root(repo_root: Path, env: Environment) -> bool:
    """Return True only for paths native to *env*.

    WSL can see Windows repos under ``/mnt/<drive>/...`` and Windows can see
    WSL repos through ``\\\\wsl$`` / ``\\\\wsl.localhost``. Those views are
    intentionally not considered native discovery candidates.
    """
    if env is Environment.WSL:
        parts = repo_root.parts
        return not (
            len(parts) >= 3 and parts[1] == "mnt" and len(parts[2]) == 1 and parts[2].isalpha()
        )
    if env is Environment.WINDOWS:
        raw = str(repo_root).lower()
        return not (raw.startswith("\\\\wsl.localhost\\") or raw.startswith("\\\\wsl$\\"))
    return True


def _check_repo(repo_path: Path, peer_identity: Identity, runner: CommandRunner) -> str | None:
    """Resolve identity at *repo_path* and match against *peer_identity*.

    Returns the match reason (``"remote_url"`` or ``"root_commits"``) or ``None``.
    Catches errors from repos with no commits or broken state.
    """
    try:
        local_identity = resolve_identity(repo_path, runner)
    except WdSyncError:
        return None
    return match_identity(local_identity, peer_identity)


def _project_search_dirs(env: Environment) -> tuple[Path, ...]:
    """Return well-known project directories for the current environment."""
    home = Path.home()
    if env is Environment.WINDOWS:
        return (
            home / "source" / "repos",
            home / "Documents" / "Projects",
            home / "Projects",
            home / "repos",
            home / "dev",
        )
    # WSL and Linux share the same layout
    return (
        home / "projects",
        home / "repos",
        home / "dev",
        home / "src",
    )


def _scan_candidates(
    search_dirs: tuple[Path, ...],
    peer_identity: Identity,
    runner: CommandRunner,
    *,
    max_depth: int = 2,
    max_candidates: int = 50,
) -> tuple[Path, str] | None:
    """Walk *search_dirs* up to *max_depth*, checking at most *max_candidates* repos."""
    checked = 0
    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        result = _walk_dir(search_dir, peer_identity, runner, 0, max_depth, checked, max_candidates)
        if isinstance(result, tuple):
            return result
        checked = result
        if checked >= max_candidates:
            break
    return None


def _walk_dir(
    directory: Path,
    peer_identity: Identity,
    runner: CommandRunner,
    depth: int,
    max_depth: int,
    checked: int,
    max_candidates: int,
) -> tuple[Path, str] | int:
    """Recursively walk *directory*.

    Returns ``(repo_root, matched_by)`` on match, or the updated *checked* count.
    """
    try:
        entries = sorted(directory.iterdir())
    except PermissionError:
        return checked

    for entry in entries:
        if checked >= max_candidates or not entry.is_dir():
            if checked >= max_candidates:
                return checked
            continue
        result = _check_entry(
            entry, peer_identity, runner, depth, max_depth, checked, max_candidates
        )
        if isinstance(result, tuple):
            return result
        checked = result
    return checked


def _check_entry(
    entry: Path,
    peer_identity: Identity,
    runner: CommandRunner,
    depth: int,
    max_depth: int,
    checked: int,
    max_candidates: int,
) -> tuple[Path, str] | int:
    """Check a single directory entry — either a git repo or a subtree to recurse into."""
    try:
        has_git = (entry / ".git").exists()
    except PermissionError:
        return checked
    if has_git:
        checked += 1
        matched_by = _check_repo(entry, peer_identity, runner)
        if matched_by is not None:
            return entry, matched_by
        return checked
    if depth < max_depth:
        return _walk_dir(
            entry, peer_identity, runner, depth + 1, max_depth, checked, max_candidates
        )
    return checked

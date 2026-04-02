from __future__ import annotations

from pathlib import Path

from wdsync.core.config import CONFIG_FILENAME, find_repo_root, state_dir
from wdsync.core.models import DeinitializeResult
from wdsync.core.runner import CommandRunner

_CONFIG_FILENAME_JSON = "config.json"
_MANIFEST_FILENAME = "manifest.json"
_LOG_FILENAME = "wdsync.log"


def deinitialize_repo(runner: CommandRunner, *, cwd: Path | None = None) -> DeinitializeResult:
    repo_root = find_repo_root(runner, cwd=cwd)
    sdir = state_dir(repo_root, runner)
    marker_path = repo_root / CONFIG_FILENAME
    exclude_path = _git_exclude_path(repo_root, runner)

    removed_config = _unlink_if_exists(sdir / _CONFIG_FILENAME_JSON)
    removed_manifest = _unlink_if_exists(sdir / _MANIFEST_FILENAME)
    removed_log = _unlink_if_exists(sdir / _LOG_FILENAME)
    removed_marker = _unlink_if_exists(marker_path)
    removed_exclude_entry = _remove_exclude_pattern(exclude_path, CONFIG_FILENAME)

    leftover_state_files = _state_dir_entries(sdir)
    removed_state_dir = False
    if sdir.exists() and not leftover_state_files:
        sdir.rmdir()
        removed_state_dir = True

    already_deinitialized = not any(
        (
            removed_config,
            removed_manifest,
            removed_log,
            removed_marker,
            removed_exclude_entry,
            removed_state_dir,
        )
    )

    return DeinitializeResult(
        repo_root=repo_root,
        state_path=sdir,
        marker_path=marker_path,
        removed_config=removed_config,
        removed_manifest=removed_manifest,
        removed_log=removed_log,
        removed_marker=removed_marker,
        removed_exclude_entry=removed_exclude_entry,
        removed_state_dir=removed_state_dir,
        already_deinitialized=already_deinitialized,
        leftover_state_files=leftover_state_files,
    )


def _git_exclude_path(repo_root: Path, runner: CommandRunner) -> Path:
    result = runner.run(["git", "-C", str(repo_root), "rev-parse", "--git-path", "info/exclude"])
    return Path(result.stdout_text().strip())


def _unlink_if_exists(path: Path) -> bool:
    if not path.exists():
        return False
    path.unlink()
    return True


def _remove_exclude_pattern(exclude_path: Path, pattern: str) -> bool:
    if not exclude_path.exists():
        return False

    original = exclude_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    kept_lines = [line for line in lines if line.strip() != pattern]
    if len(kept_lines) == len(lines):
        return False

    if kept_lines:
        exclude_path.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
    else:
        exclude_path.write_text("", encoding="utf-8")
    return True


def _state_dir_entries(state_path: Path) -> tuple[str, ...]:
    if not state_path.exists():
        return ()
    return tuple(sorted(entry.name for entry in state_path.iterdir()))

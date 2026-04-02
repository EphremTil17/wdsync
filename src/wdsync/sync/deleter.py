from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from wdsync.core.exceptions import SudoDeleteError
from wdsync.core.models import DeleteOutcome, SyncPlan
from wdsync.core.path_utils import is_wsl_windows_path


def _skip(rel_path: str, reason: str) -> DeleteOutcome:
    return DeleteOutcome(
        path=rel_path, deleted=False, skipped=True, skip_reason=reason, used_sudo=False
    )


def _deleted(rel_path: str, *, used_sudo: bool) -> DeleteOutcome:
    return DeleteOutcome(
        path=rel_path, deleted=True, skipped=False, skip_reason=None, used_sudo=used_sudo
    )


def _resolve_safe(dest_root: Path, rel_path: str) -> Path | None:
    abs_path = (dest_root / rel_path).resolve(strict=False)
    resolved_root = dest_root.resolve()
    if not abs_path.is_relative_to(resolved_root):
        return None
    return dest_root / rel_path


def _maybe_prune_parents(abs_path: Path, dest_root: Path) -> None:
    parent = abs_path.parent
    resolved_root = dest_root.resolve()
    while parent != resolved_root and parent.is_relative_to(resolved_root):
        try:
            if next(parent.iterdir(), None) is None:
                parent.rmdir()
                parent = parent.parent
            else:
                break
        except OSError:
            break


def _sudo_unlink(abs_path: Path) -> None:
    result = subprocess.run(
        ["sudo", "rm", "-f", str(abs_path)],
        capture_output=True,
    )
    if result.returncode != 0:
        raise SudoDeleteError(str(abs_path), returncode=result.returncode)


def _unlink_with_sudo_fallback(
    abs_path: Path,
    rel_path: str,
    confirm_sudo: Callable[[str], bool],
    dest_root: Path,
) -> DeleteOutcome:
    try:
        abs_path.unlink()
        return _deleted(rel_path, used_sudo=False)
    except PermissionError:
        if is_wsl_windows_path(dest_root):
            return _skip(rel_path, "permission-denied-windows")
        if not confirm_sudo(rel_path):
            return _skip(rel_path, "permission-denied-user-declined")
        _sudo_unlink(abs_path)
        return _deleted(rel_path, used_sudo=True)
    except OSError as exc:
        return _skip(rel_path, f"os-error:{exc.errno}")


def _delete_one(
    rel_path: str,
    plan: SyncPlan,
    dest_dirty_paths: frozenset[str],
    confirm_sudo: Callable[[str], bool],
    prune_empty_dirs: bool,
) -> DeleteOutcome:
    abs_path = _resolve_safe(plan.dest_root, rel_path)
    if abs_path is None:
        return _skip(rel_path, "path-traversal")

    if rel_path in dest_dirty_paths:
        return _skip(rel_path, "dest-modified")

    if not abs_path.exists() and not abs_path.is_symlink():
        return _skip(rel_path, "absent")

    outcome = _unlink_with_sudo_fallback(abs_path, rel_path, confirm_sudo, plan.dest_root)
    if outcome.deleted and prune_empty_dirs:
        _maybe_prune_parents(abs_path, plan.dest_root)
    return outcome


def delete_files(
    plan: SyncPlan,
    dest_dirty_paths: frozenset[str],
    *,
    confirm_sudo: Callable[[str], bool],
    prune_empty_dirs: bool = True,
) -> tuple[DeleteOutcome, ...]:
    return tuple(
        _delete_one(rel_path, plan, dest_dirty_paths, confirm_sudo, prune_empty_dirs)
        for rel_path in plan.delete_paths
    )

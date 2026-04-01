from __future__ import annotations

import errno
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wdsync.core.exceptions import SudoDeleteError
from wdsync.core.models import SyncPlan
from wdsync.sync.deleter import delete_files


def _plan(dest_root: Path, delete_paths: tuple[str, ...]) -> SyncPlan:
    return SyncPlan(
        source_root=Path("/tmp/source"),
        dest_root=dest_root,
        preview_rows=(),
        copy_paths=(),
        delete_paths=delete_paths,
        skipped_paths=(),
        warnings=(),
    )


def test_delete_normal_file(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("hello\n", encoding="utf-8")

    outcomes = delete_files(
        _plan(tmp_path, ("file.txt",)), frozenset(), confirm_sudo=lambda _: False
    )

    assert len(outcomes) == 1
    assert outcomes[0].deleted is True
    assert outcomes[0].used_sudo is False
    assert not target.exists()


def test_delete_absent_is_idempotent(tmp_path: Path) -> None:
    outcomes = delete_files(
        _plan(tmp_path, ("missing.txt",)), frozenset(), confirm_sudo=lambda _: False
    )

    assert outcomes[0].skipped is True
    assert outcomes[0].skip_reason == "absent"


def test_delete_symlink_not_target(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("data\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    outcomes = delete_files(
        _plan(tmp_path, ("link.txt",)), frozenset(), confirm_sudo=lambda _: False
    )

    assert outcomes[0].deleted is True
    assert not link.exists()
    assert target.exists()


def test_delete_permission_denied_user_confirms(tmp_path: Path) -> None:
    target = tmp_path / "protected.txt"
    target.write_text("data\n", encoding="utf-8")

    with (
        patch.object(Path, "unlink", side_effect=PermissionError("denied")),
        patch("wdsync.sync.deleter.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        outcomes = delete_files(
            _plan(tmp_path, ("protected.txt",)), frozenset(), confirm_sudo=lambda _: True
        )

    assert outcomes[0].deleted is True
    assert outcomes[0].used_sudo is True
    mock_run.assert_called_once()
    assert "sudo" in mock_run.call_args[0][0]


def test_delete_permission_denied_user_declines(tmp_path: Path) -> None:
    target = tmp_path / "protected.txt"
    target.write_text("data\n", encoding="utf-8")

    with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
        outcomes = delete_files(
            _plan(tmp_path, ("protected.txt",)), frozenset(), confirm_sudo=lambda _: False
        )

    assert outcomes[0].skipped is True
    assert outcomes[0].skip_reason == "permission-denied-user-declined"


def test_delete_sudo_failure_raises(tmp_path: Path) -> None:
    target = tmp_path / "protected.txt"
    target.write_text("data\n", encoding="utf-8")

    with (
        patch.object(Path, "unlink", side_effect=PermissionError("denied")),
        patch("wdsync.sync.deleter.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=1)
        with pytest.raises(SudoDeleteError):
            delete_files(
                _plan(tmp_path, ("protected.txt",)), frozenset(), confirm_sudo=lambda _: True
            )


def test_delete_path_traversal_blocked(tmp_path: Path) -> None:
    outcomes = delete_files(
        _plan(tmp_path, ("../../etc/passwd",)), frozenset(), confirm_sudo=lambda _: False
    )

    assert outcomes[0].skipped is True
    assert outcomes[0].skip_reason == "path-traversal"


def test_delete_dest_modified_skipped(tmp_path: Path) -> None:
    target = tmp_path / "modified.txt"
    target.write_text("data\n", encoding="utf-8")

    outcomes = delete_files(
        _plan(tmp_path, ("modified.txt",)),
        frozenset({"modified.txt"}),
        confirm_sudo=lambda _: False,
    )

    assert outcomes[0].skipped is True
    assert outcomes[0].skip_reason == "dest-modified"
    assert target.exists()


def test_delete_readonly_fs_oserror(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("data\n", encoding="utf-8")

    with patch.object(Path, "unlink", side_effect=OSError(errno.EROFS, "read-only")):
        outcomes = delete_files(
            _plan(tmp_path, ("file.txt",)), frozenset(), confirm_sudo=lambda _: False
        )

    assert outcomes[0].skipped is True
    assert outcomes[0].skip_reason == f"os-error:{errno.EROFS}"


def test_prune_empty_parent(tmp_path: Path) -> None:
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    target = subdir / "file.txt"
    target.write_text("data\n", encoding="utf-8")

    outcomes = delete_files(
        _plan(tmp_path, ("subdir/file.txt",)), frozenset(), confirm_sudo=lambda _: False
    )

    assert outcomes[0].deleted is True
    assert not subdir.exists()


def test_prune_disabled_leaves_parent(tmp_path: Path) -> None:
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    target = subdir / "file.txt"
    target.write_text("data\n", encoding="utf-8")

    outcomes = delete_files(
        _plan(tmp_path, ("subdir/file.txt",)),
        frozenset(),
        confirm_sudo=lambda _: False,
        prune_empty_dirs=False,
    )

    assert outcomes[0].deleted is True
    assert subdir.exists()


def test_prune_nonempty_parent_preserved(tmp_path: Path) -> None:
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "file.txt").write_text("a\n", encoding="utf-8")
    (subdir / "other.txt").write_text("b\n", encoding="utf-8")

    outcomes = delete_files(
        _plan(tmp_path, ("subdir/file.txt",)), frozenset(), confirm_sudo=lambda _: False
    )

    assert outcomes[0].deleted is True
    assert subdir.exists()
    assert (subdir / "other.txt").exists()


def test_windows_path_skips_sudo(tmp_path: Path) -> None:
    target = tmp_path / "protected.txt"
    target.write_text("data\n", encoding="utf-8")

    with (
        patch.object(Path, "unlink", side_effect=PermissionError("denied")),
        patch("wdsync.sync.deleter.is_wsl_windows_path", return_value=True),
    ):
        outcomes = delete_files(
            _plan(tmp_path, ("protected.txt",)), frozenset(), confirm_sudo=lambda _: True
        )

    assert outcomes[0].skipped is True
    assert outcomes[0].skip_reason == "permission-denied-windows"


def test_delete_no_paths_returns_empty(tmp_path: Path) -> None:
    outcomes = delete_files(_plan(tmp_path, ()), frozenset(), confirm_sudo=lambda _: False)
    assert outcomes == ()


def test_delete_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")

    outcomes = delete_files(
        _plan(tmp_path, ("a.txt", "b.txt")), frozenset(), confirm_sudo=lambda _: False
    )

    assert len(outcomes) == 2
    assert all(o.deleted for o in outcomes)
    assert not (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()

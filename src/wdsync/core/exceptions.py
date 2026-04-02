from __future__ import annotations

from collections.abc import Sequence


class WdSyncError(Exception):
    """Base class for user-facing errors."""


class UnsupportedEnvironmentError(WdSyncError):
    """Raised when wdsync is executed outside the supported environment."""


class MissingDependencyError(WdSyncError):
    """Raised when a required external program is unavailable."""


class NotGitRepositoryError(WdSyncError):
    """Raised when the current working directory is not inside a Git repo."""


class MissingConfigError(WdSyncError):
    """Raised when .wdsync is missing from the destination repo."""


class ConfigValidationError(WdSyncError):
    """Raised when .wdsync is present but invalid."""


class StatusParseError(WdSyncError):
    """Raised when Git porcelain output cannot be parsed."""


class ShellDetectionError(WdSyncError):
    """Raised when the active shell cannot be detected safely."""


class DeletionError(WdSyncError):
    """Raised when a file deletion fails in a non-recoverable way."""

    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(message)
        self.path = path


class SudoDeleteError(DeletionError):
    """Raised when sudo rm fails for a permission-protected file."""

    def __init__(self, path: str, *, returncode: int) -> None:
        super().__init__(f"wdsync: sudo rm failed for {path!r} (exit {returncode})", path=path)
        self.returncode = returncode


class IdentityMismatchError(WdSyncError):
    """Raised when two repos do not share a common identity."""


class PeerConnectionError(WdSyncError):
    """Raised when the peer subprocess fails to start, handshake, or respond."""


class CommandExecutionError(WdSyncError):
    """Raised when an external command exits unsuccessfully."""

    def __init__(
        self,
        message: str,
        *,
        command: Sequence[str],
        returncode: int,
        stderr: str = "",
        stdout: str = "",
    ) -> None:
        super().__init__(message)
        self.command = tuple(command)
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout

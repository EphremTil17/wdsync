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


class SourceRepositoryError(WdSyncError):
    """Raised when the configured Windows source repo is invalid."""


class StatusParseError(WdSyncError):
    """Raised when Git porcelain output cannot be parsed."""


class ShellDetectionError(WdSyncError):
    """Raised when the active shell cannot be detected safely."""


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

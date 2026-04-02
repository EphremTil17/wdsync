from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypedDict

ShellName = Literal["bash", "fish", "zsh"]


class StatusKind(StrEnum):
    NEW = "new"
    UNSTAGED = "unstaged"
    STAGED = "staged"
    BOTH = "both"
    ADDED = "added"
    ADDED_MODIFIED = "added+mod"
    RENAMED = "renamed"
    COPIED = "copied"
    DELETED = "deleted"
    CHANGED = "changed"


class SyncDirection(StrEnum):
    FETCH = "fetch"
    SEND = "send"


class HeadRelation(StrEnum):
    SAME = "same"
    SOURCE_AHEAD = "source-ahead"
    DESTINATION_AHEAD = "destination-ahead"
    DIVERGED = "diverged"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True)
class RepoEndpoint:
    root: Path
    native_root: str


@dataclass(frozen=True)
class GitExecution:
    command_argv: tuple[str, ...]
    repo_native_root: str

    @property
    def executable_name(self) -> str:
        if not self.command_argv:
            return "git"
        return self.command_argv[-1]

    def build(self, *args: str) -> list[str]:
        return [*self.command_argv, "-C", self.repo_native_root, *args]


@dataclass(frozen=True)
class TransferExecution:
    command_argv: tuple[str, ...]
    source_root: str
    dest_root: str

    def build(self, *args: str) -> list[str]:
        return [*self.command_argv, *args, f"{self.source_root}/", f"{self.dest_root}/"]


@dataclass(frozen=True)
class DirectionConfig:
    direction: SyncDirection
    source: RepoEndpoint
    destination: RepoEndpoint
    source_git: GitExecution
    destination_git: GitExecution
    transfer: TransferExecution
    source_is_local: bool = True
    destination_is_local: bool = True
    peer_command_argv: tuple[str, ...] = ()

    @property
    def source_root(self) -> Path:
        return self.source.root

    @property
    def dest_root(self) -> Path:
        return self.destination.root

    @property
    def source_root_native(self) -> str:
        return self.source.native_root

    @property
    def dest_root_native(self) -> str:
        return self.destination.native_root

    @property
    def dest_git(self) -> str:
        return self.destination_git.executable_name

    def source_git_command(self, *args: str) -> list[str]:
        return self.source_git.build(*args)

    def dest_git_command(self, *args: str) -> list[str]:
        return self.destination_git.build(*args)

    def rsync_command(self, *args: str) -> list[str]:
        return self.transfer.build(*args)


@dataclass(frozen=True)
class StatusRecord:
    raw_xy: str
    path: str
    orig_path: str | None
    kind: StatusKind


@dataclass(frozen=True)
class SourceState:
    head: str | None
    entries: tuple[StatusRecord, ...]


@dataclass(frozen=True)
class PreviewRow:
    path: str
    raw_xy: str
    label: str
    syncable: bool


@dataclass(frozen=True)
class SyncPlan:
    source_root: Path
    dest_root: Path
    preview_rows: tuple[PreviewRow, ...]
    copy_paths: tuple[str, ...]
    delete_paths: tuple[str, ...]
    skipped_paths: tuple[str, ...]
    warnings: tuple[str, ...]
    direction: SyncDirection = SyncDirection.FETCH
    restore_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class DestinationState:
    head: str | None
    modified_count: int
    staged_count: int
    untracked_count: int
    dirty_paths: frozenset[str] = field(default_factory=lambda: frozenset[str]())
    wt_deleted_paths: frozenset[str] = field(default_factory=lambda: frozenset[str]())
    entries: tuple[StatusRecord, ...] = ()

    @property
    def is_dirty(self) -> bool:
        return any((self.modified_count, self.staged_count, self.untracked_count))


@dataclass(frozen=True)
class DoctorWarning:
    code: str
    message: str
    severity: Severity


@dataclass(frozen=True)
class DoctorReport:
    source_head: str | None
    destination_head: str | None
    source_dirty_count: int
    head_relation: HeadRelation
    destination_state: DestinationState
    warnings: tuple[DoctorWarning, ...]
    risk_level: RiskLevel


@dataclass(frozen=True)
class SyncResult:
    plan: SyncPlan
    copied_count: int
    deleted_count: int
    skipped_count: int
    performed_copy: bool
    restored_count: int = 0


@dataclass(frozen=True)
class ShellInstallResult:
    shell: ShellName
    installed_paths: tuple[Path, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Identity:
    remote_url: str | None
    root_commits: tuple[str, ...]


@dataclass(frozen=True)
class PeerConfig:
    command_argv: tuple[str, ...]
    root: Path
    root_native: str


@dataclass(frozen=True)
class RuntimePreferences:
    windows_peer_command_argv: tuple[str, ...] | None = None
    wsl_peer_command_argv: tuple[str, ...] | None = None
    wsl_distro: str | None = None


@dataclass(frozen=True)
class WdsyncConfig:
    version: int
    identity: Identity
    peer: PeerConfig | None
    runtime: RuntimePreferences = field(default_factory=RuntimePreferences)


@dataclass(frozen=True)
class InitializeResult:
    repo_root: Path
    config_path: Path
    marker_path: Path
    identity: Identity
    already_initialized: bool = False


@dataclass(frozen=True)
class ConnectResult:
    matched_by: str
    peer: PeerConfig


@dataclass(frozen=True)
class ConflictRecord:
    path: str
    source_xy: str
    dest_xy: str


@dataclass(frozen=True)
class DeleteOutcome:
    path: str
    deleted: bool
    skipped: bool
    skip_reason: str | None
    used_sudo: bool


@dataclass(frozen=True)
class RestoreResult:
    restored_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SyncContext:
    dconfig: DirectionConfig
    source_state: SourceState
    destination_state: DestinationState
    conflicts: tuple[ConflictRecord, ...]
    doctor_report: DoctorReport
    manifest_untracked: frozenset[str]
    orphaned_paths: frozenset[str]


class PreviewRowJSON(TypedDict):
    path: str
    raw_status: str
    label: str
    syncable: bool


class SyncJSON(TypedDict):
    schema_version: int
    direction: str
    source_root: str
    dest_root: str
    total: int
    copied_count: int
    deleted_count: int
    restored_count: int
    skipped_count: int
    performed_copy: bool
    warnings: list[str]
    rows: list[PreviewRowJSON]


class ConflictJSON(TypedDict):
    path: str
    source_xy: str
    dest_xy: str


class StatusRecordJSON(TypedDict):
    raw_xy: str
    path: str
    orig_path: str | None
    kind: str


class RepoStatusJSON(TypedDict):
    head: str | None
    modified_count: int
    staged_count: int
    untracked_count: int
    dirty_paths: list[str]
    wt_deleted_paths: list[str]
    entries: list[StatusRecordJSON]


class DeleteOutcomeJSON(TypedDict):
    path: str
    deleted: bool
    skipped: bool
    skip_reason: str | None
    used_sudo: bool


class RestoreResultJSON(TypedDict):
    restored_count: int
    warnings: list[str]


class StatusJSON(TypedDict):
    schema_version: int
    direction: str
    source_dirty_count: int
    destination_dirty_count: int
    conflict_count: int
    head_relation: str
    risk_level: str
    orphaned_count: int
    source_entries: list[PreviewRowJSON]
    destination_entries: list[PreviewRowJSON]
    conflicts: list[ConflictJSON]

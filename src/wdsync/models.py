from __future__ import annotations

from dataclasses import dataclass
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
class ProjectConfig:
    dest_root: Path
    config_path: Path
    source_root: Path
    source_root_windows: str


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
    skipped_paths: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class DestinationState:
    head: str | None
    modified_count: int
    staged_count: int
    untracked_count: int

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
    skipped_count: int
    performed_copy: bool


@dataclass(frozen=True)
class InitResult:
    config: ProjectConfig
    wrote_config: bool
    exclude_path: Path
    updated_exclude: bool


@dataclass(frozen=True)
class ShellInstallResult:
    shell: ShellName
    installed_paths: tuple[Path, ...]
    notes: tuple[str, ...]


class PreviewRowJSON(TypedDict):
    path: str
    raw_status: str
    label: str
    syncable: bool


class PreviewJSON(TypedDict):
    schema_version: int
    source_root: str
    dest_root: str
    total: int
    syncable_count: int
    skipped_count: int
    warnings: list[str]
    rows: list[PreviewRowJSON]


class SyncJSON(TypedDict):
    schema_version: int
    source_root: str
    dest_root: str
    total: int
    copied_count: int
    skipped_count: int
    performed_copy: bool
    warnings: list[str]
    rows: list[PreviewRowJSON]


class DestinationStateJSON(TypedDict):
    head: str | None
    modified_count: int
    staged_count: int
    untracked_count: int
    is_dirty: bool


class DoctorWarningJSON(TypedDict):
    code: str
    message: str
    severity: str


class DoctorJSON(TypedDict):
    schema_version: int
    source_head: str | None
    destination_head: str | None
    source_dirty_count: int
    head_relation: str
    risk_level: str
    destination: DestinationStateJSON
    warnings: list[DoctorWarningJSON]

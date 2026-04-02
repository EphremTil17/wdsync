# Changelog

All notable changes to `wdsync` will be documented in this file.

The format is based on Keep a Changelog, and this project aims to follow
Semantic Versioning once formal releases begin.

## [0.5.0] - 2026-04-01

### Added

- Full RPC-based peer connection: `wdsync connect` spawns the peer process
  (`python.exe -m wdsync rpc`), performs a protocol handshake, discovers the
  matching repo via layered search, verifies identity, and saves the peer
  connection.
- RPC client module (`rpc/client.py`): context-manager `RpcClient` class that
  spawns a subprocess, exchanges JSON messages over stdin/stdout with timeout
  support, drains stderr on failure paths for diagnostics.
- Peer discovery module (`rpc/discovery.py`): environment-aware layered search
  that checks cached last-known root, peer cwd, then common project directories
  with bounded depth walk. Supports both Windows and WSL/Linux search layouts.
- RPC handlers module (`rpc/handlers.py`): dispatches HANDSHAKE (protocol-only,
  version + capabilities) and LOCATE_REPO (identity resolution + discovery).
- Connect flow module (`rpc/connect.py`): orchestrates the full connect
  workflow with identity verification and wslpath translation.
- Multi-turn `wdsync rpc` server: reads JSON from stdin in a loop, dispatches
  to handlers, responds on stdout. Replaces the single-shot stub.
- `load_wdsync_config_with_paths()` returns config, repo root, and state dir in
  one pass, eliminating duplicate subprocess calls in CLI commands.
- Strict peer config validation: `_config_from_dict()` rejects incomplete peer
  blocks (empty command_argv, root, or root_native).
- Hardened RPC response parsing: non-numeric version fields, non-dict data
  fields, and non-boolean ok fields are normalized or rejected as
  `PeerConnectionError` instead of leaking raw `ValueError`/`TypeError`.
- `SyncContext` adoption: `_sync_flow` and `status` now use
  `build_sync_context()` instead of computing state inline.

### Changed

- Protocol simplified: handshake is now protocol-only (version + capabilities).
  Identity resolution moved to `locate_repo`, keeping handshake fast and
  decoupled from repo state.
- `locate_repo` response now includes peer identity alongside repo root and
  matched_by, so the caller can verify identity match.
- `locate_repo` request accepts optional `cached_root` for instant reconnects.

### Removed

- All legacy INI-era code: `ProjectConfig`, `InitResult`, `load_project_config`,
  `init_project`, `parse_config_text`, `discover_matching_windows_repo`,
  `find_destination_root`, `_build_project_config`, `_remotes_match`,
  `_common_project_dirs`.
- Legacy `build_direction_config` (the version taking `ProjectConfig`).
- `SourceRepositoryError` exception (unused after INI removal).
- `ensure_wsl_environment`, `normalize_source_path`, `wsl_to_windows_path`
  from path_utils (replaced by environment detection and wslpath calls).
- Dead TypedDicts: `PreviewJSON`, `DoctorJSON`, `DestinationStateJSON`,
  `DoctorWarningJSON`.
- 17 legacy tests replaced with modern equivalents using `WdsyncConfig`,
  `DirectionConfig`, and the new `direction_config_factory` fixture.

## [0.4.0] - 2026-03-31

### Added

- Two-way sync: `wdsync send` pushes WSL dirty tree to Windows, `wdsync fetch`
  pulls Windows dirty tree into WSL. `wdsync sync` and `-f` remain as aliases
  for fetch.
- Unified status command: `wdsync status` shows both repos' dirty files,
  conflicts, HEAD relation, risk level, and orphaned untracked files in a single
  view. Supports `--send` and `--json`.
- Conflict detection: files modified on both sides are detected and blocked by
  default. Use `--force` to override on `fetch`, `send`, or `sync`.
- Structured logging via loguru: all output routed through leveled logging
  (INFO, DEBUG, WARNING, ERROR). Console output goes to stderr so `--json`
  stdout stays clean. File logging to `.git/.wdsync.log` with rotation.
- `--debug` flag on root command enables verbose DEBUG-level logging.
- Environment detection module (`core/environment.py`) for WSL/Windows/Linux.
- RPC protocol stub (`core/protocol.py`) with versioned JSON message types and
  hidden `wdsync rpc` command for future cross-platform communication.
- Auto-detection for `wdsync init`: when called without arguments, scans common
  Windows project directories for a repo with a matching git remote URL.
- `--send` flag on `preview` and `doctor` commands for reverse direction.
- `--force` flag on `fetch`, `send`, and `sync` commands.
- `DirectionConfig` abstraction parameterizes the entire sync pipeline for
  both directions without conditional branching.

### Changed

- Project restructured into modular subpackages: `core/`, `git/`, `sync/`,
  `output/`, `cli/`, `shell/`. No shims or legacy re-exports — clean break.
- `wdsync init` source argument is now optional (auto-detects if omitted).
- JSON schema version bumped to 2 with `direction` field.
- Deletion on Windows-mounted paths (`/mnt/c/...`) skips the sudo prompt and
  reports `permission-denied-windows` instead.
- `DestinationState` now carries full `entries` tuple for conflict detection.
- Added loguru as a runtime dependency.

## [0.2.0] - 2026-03-30

### Added

- Deletion propagation: files deleted in the Windows source repo are now
  removed from the WSL destination during `wdsync sync`.
- Sudo escalation: if a deletion fails due to file permissions, `wdsync`
  prompts the user to retry with `sudo`.
- Destination-modified guard: files with local staged or unstaged changes in the
  destination repo are never deleted, preventing accidental data loss.
- Path traversal guard: delete paths that would escape the destination root are
  blocked.
- Empty directory pruning: parent directories left empty after deletion are
  automatically removed up to the repo root.
- Reconciliation: tracked files previously deleted by wdsync but restored in
  the source are now automatically restored in the destination via
  `git restore`.
- Untracked file manifest: a `.wdsync-manifest` file inside `.git/` tracks
  previously synced untracked files so orphans are cleaned up when the source
  deletes them.
- New `deleter` module (`src/wdsync/deleter.py`) handling all deletion edge
  cases: absent files, symlinks, permission errors, read-only filesystems, and
  path traversal.
- New `manifest` module (`src/wdsync/manifest.py`) for reading and writing the
  sync manifest.
- New exception types `DeletionError` and `SudoDeleteError`.
- New fields: `delete_paths` and `restore_paths` on `SyncPlan`;
  `deleted_count` and `restored_count` on `SyncResult`; `dirty_paths` and
  `wt_deleted_paths` on `DestinationState`.
- Comprehensive unit and integration tests for deletion, reconciliation, and
  manifest behavior.

### Changed

- `wdsync sync` now calls `read_destination_state` to check for local changes
  before deleting files.
- rsync flags changed from `-a` (archive) to `-rlt` (recursive, symlinks,
  times) to avoid copying Windows file permissions into WSL.
- Formatter output updated: "Restored N file(s).", "Deleted N file(s)." lines
  added to sync results.
- JSON output (`SyncJSON`) now includes `deleted_count` and `restored_count`
  fields.
- Version is now dynamically read from `pyproject.toml` via
  `importlib.metadata` instead of a hardcoded string in `__init__.py`.
- Config regex simplified (`\w` instead of `[A-Za-z0-9_]`) and trailing
  whitespace stripping moved to Python to eliminate backtracking risk.
- `deleter.py` refactored to reduce cognitive complexity (extracted
  `_delete_one`, `_unlink_with_sudo_fallback` helpers).

### Removed

- The "v1 does not propagate deletions" warning is no longer emitted.

## [0.1.0] - 2026-03-20

### Added

- Rebuilt `wdsync` as a Python 3.11+ CLI package with a `src/` layout and a
  `wdsync` console entry point.
- Added Typer-based commands for `preview`, `sync`, `init`, `doctor`, and
  `shell install`.
- Added `python -m wdsync` support through `__main__.py`.
- Added `uv`-based project management with dev tooling for Ruff, Pyright, and
  pytest.
- Added built-in coverage reporting for the default `uv run pytest` workflow
  through `pytest-cov` and `coverage.py` configuration in `pyproject.toml`.
- Added a repository `.pre-commit-config.yaml` that runs `ruff check --fix`,
  `ruff format`, and `pyright` before commits.
- Added typed domain models, centralized subprocess execution, structured
  formatters, and JSON output for `preview`, `sync`, and `doctor`.
- Added optional shell integration for bash, fish, and zsh with auto-detection
  and shell-specific install behavior.
- Added unit and integration tests covering config loading, status parsing,
  planner behavior, CLI dispatch, sync execution, and doctor checks.

### Changed

- Moved the core implementation out of shell scripts and into a modular Python
  package.
- Made the CLI binary-first and shell-agnostic for normal usage.
- Updated the project workflow to use `uv sync --dev`, `uv run pytest`,
  `uv run ruff check .`, and `uv run pyright`.
- Updated repository documentation to reflect the Python CLI baseline and the
  v1 feature set.

### Fixed

- Corrected Git porcelain v1 `-z` rename and copy parsing.
- Expanded untracked directories to leaf files by reading source status with
  `--untracked-files=all`.
- Prevented deleted source files from breaking sync by previewing them but
  skipping them during `rsync`.
- Preserved the low-friction `.wdsync` workflow while making the internal
  implementation typed, testable, and modular.

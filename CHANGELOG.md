# Changelog

All notable changes to `wdsync` will be documented in this file.

The format is based on Keep a Changelog, and this project aims to follow
Semantic Versioning once formal releases begin.

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

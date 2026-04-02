# Developer Setup

This guide is for contributing to the `wdsync` codebase from a source checkout.

If you only want to install and use the published CLI, use
[SETUP.md](../SETUP.md).

## Prerequisites

Use the same runtime prerequisites as normal setup:

- WSL
- `git`
- `git.exe`
- `rsync`
- `wslpath`
- Python 3.11+
- `uv`

## 1. Clone And Enter The Repo

```bash
git clone <your-repo-url>
cd wdsync
```

## 2. Create The Development Environment

```bash
uv sync --dev
```

This creates the project virtual environment in `.venv` and installs:

- the local `wdsync` package in editable mode
- pre-commit
- pytest
- pytest-cov
- Ruff
- Pyright

## 3. Run The CLI During Development

Use `uv run` so the current checkout is executed directly:

```bash
uv run wdsync --help
uv run wdsync init
uv run wdsync status
```

Module entry point:

```bash
uv run python -m wdsync --help
```

## 4. Install Git Hooks

Install the pre-commit hooks once per clone:

```bash
uv run pre-commit install
```

The hook chain runs:

- `ruff check --fix`
- `ruff format`
- `pyright`

If Ruff changes files during a commit attempt, the commit stops and Git will
show modified files that must be reviewed and restaged before retrying. That is
intentional.

## 5. Quality Gates

Run tests:

```bash
uv run pytest
```

Generate an XML coverage report when needed:

```bash
uv run pytest --cov-report=xml
```

Run lint checks:

```bash
uv run ruff check .
```

Format code:

```bash
uv run ruff format .
```

Run type checking:

```bash
uv run pyright
```

Recommended full validation sequence:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

You can also run the same hook chain manually:

```bash
uv run pre-commit run --all-files
```

## 6. Project Structure

Main areas:

- `src/wdsync/` for the Python CLI and core logic
- `tests/` for unit and integration coverage
- `scripts/bash/` for executable shell wrapper examples
- `scripts/fish/` for fish function wrapper examples
- `README.md`, `SETUP.md`, and `docs/` for user and contributor docs

## 7. Development Notes

- Keep business logic out of shell wrappers and CLI command definitions.
- Route external commands through the runner abstraction.
- Use `git.exe` for the Windows source repo, `git` for WSL.
- Package is organized into subpackages: `core/`, `git/`, `sync/`, `rpc/`,
  `output/`, `cli/`, `shell/`. New modules go in the appropriate subpackage.
- Prefer typed dataclasses for internal models and `TypedDict` for structured
  JSON payloads.
- pyright strict mode, ruff clean, >80% test coverage on every change.

## 8. Typical Local Workflow

1. Update code in `src/wdsync/`.
2. Run `uv run pytest`.
3. Run `uv run ruff check .`.
4. Run `uv run pyright`.
5. Run `uv run pre-commit run --all-files` before larger commits.
6. Smoke-test with `uv run wdsync --help` or inside real WSL/Windows peer repos.
7. If you touch connect or interop code, test at least one bilateral `wdsync connect`
   flow and confirm both repos can run `status`, `fetch`, and `send` afterward.

### Opt-In Cross-Environment Smoke Test

There is one real-process cross-environment smoke test:

- `tests/test_crossenv_integration.py`

It is intentionally opt-in and expects:

- pytest is running from WSL
- a real WSL repo clone
- a real Windows repo clone of the same project
- globally installed `wdsync` binaries on both sides

Required environment variables:

- `WDSYNC_CROSSENV=1`
- `WDSYNC_CROSSENV_WSL_REPO=/home/<user>/projects/<repo>`
- `WDSYNC_CROSSENV_WINDOWS_REPO=C:\Users\<user>\...\<repo>`

Optional overrides:

- `WDSYNC_CROSSENV_WSL_CMD`
- `WDSYNC_CROSSENV_WINDOWS_CMD`

Run it with:

```bash
uv run pytest -m crossenv tests/test_crossenv_integration.py
```

The test uses real installed binaries, runs `init`, `connect`, `status --json`,
and `deinit` in fresh processes on both sides, and verifies that the bilateral
connection survives persisted config reloads. It only mutates wdsync-owned local
state and cleans that state up in a `finally` block.

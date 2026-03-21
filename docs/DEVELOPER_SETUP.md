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
uv run wdsync preview
uv run wdsync doctor
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

- Keep business logic out of shell wrappers and `cli.py`.
- Route external commands through the runner abstraction.
- Preserve the low-friction `.wdsync` workflow.
- Use `git.exe` for the Windows source repo.
- Keep the package flat unless growth clearly requires subpackages.
- Prefer typed dataclasses for internal models and `TypedDict` for structured
  JSON payloads.

## 8. Typical Local Workflow

1. Update code in `src/wdsync/`.
2. Run `uv run pytest`.
3. Run `uv run ruff check .`.
4. Run `uv run pyright`.
5. Run `uv run pre-commit run --all-files` before larger commits.
6. Smoke-test with `uv run wdsync --help` or inside a real destination repo.

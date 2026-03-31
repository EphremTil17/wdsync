# Setup

This guide is for installing and using the published `wdsync` CLI.

If you want to work on the codebase itself, use
[DEVELOPER_SETUP.md](docs/DEVELOPER_SETUP.md).

## Prerequisites

Run this from WSL with:

- `git`
- `git.exe`
- `rsync`
- `wslpath`
- Python 3.11+
- either `uv` or `pip`

You also need:

- WSL installed
- Git for Windows installed and callable as `git.exe`
- a Windows source repo reachable as `/mnt/<drive>/...`

## 1. Install The CLI

Recommended install path:

```bash
uv tool install wdsync
uv tool upgrade wdsync
```

Alternative install path with `pip`:

```bash
python -m pip install wdsync
python -m pip install --upgrade wdsync
```

## 2. Verify The Install

```bash
wdsync --help
#or if you installed with `pip` into an active Python environment, this also works:
python -m wdsync --help

```

## 3. Optional Shell Integration

The CLI works without shell-specific setup, but you can install optional shell
helpers and completions:

```bash
wdsync shell install
```

Override shell detection when needed:

```bash
wdsync shell install --shell fish
wdsync shell install --shell bash
wdsync shell install --shell zsh
```

## 4. Initialize A Destination Repo

From inside the WSL repo that should receive synced files:

```bash
cd /path/to/your/wsl/repo
wdsync init /mnt/c/Users/YourName/path/to/WindowsRepo
```

That writes a local `.wdsync` file like:

```ini
SRC=/mnt/c/Users/YourName/path/to/WindowsRepo
```

You can edit `.wdsync` manually later if the source path changes. `wdsync init`
also adds `.wdsync` to `.git/info/exclude` in that destination repo so the file
stays local.

## 5. Daily Use

Preview the current Windows dirty set:

```bash
wdsync
# Or explicitly:
wdsync preview
# Sync the dirty files into the current WSL repo:
wdsync sync
# Run advisory checks:
wdsync doctor
```

## Notes

- `wdsync` must be run from inside the destination Git repo.
- It helps to be on the same branch in both repos, but it is not required.
- Source dirty detection comes from `git.exe`, not Linux Git.
- Sync copies file contents only. A source staged file does not remain staged
  in the destination repo.
- Deleted source files are propagated: `wdsync sync` removes them from the
  destination. Files with local changes in the destination are skipped to avoid
  data loss. If a deletion fails due to permissions, `wdsync` will prompt to
  retry with `sudo`.

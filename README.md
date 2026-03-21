# wdsync

`wdsync` is a WSL-side Python CLI for mirroring the dirty working tree of a
Windows Git repository into a matching WSL repository without requiring a
commit, push, or pull cycle.

It is built for the workflow where:

- your primary editing happens to be on Windows for whatever reason (Flutter, VS Studio, .NET development, etc.)
- your backend, scripts, containers, or Linux tooling run in WSL either for prod or testing parity
- you want the WSL repo to mirror the current Windows dirty-set (staged and unstaged changes) on demand

The key design choice is that `wdsync` reads the source repo with `git.exe`, so
the sync set matches what Git for Windows considers dirty rather than what
Linux Git thinks about `/mnt/c/...`.

## What It Does

From inside a destination WSL repo, `wdsync` will:

- read a local `.wdsync` file
- resolve the Windows source repo from `SRC=/mnt/c/...`
- query the source dirty set using `git.exe` (Windows Git)
- preview by default to see the planned dirty set in the destination WSL repo
- sync when you run `wdsync sync` or `wdsync -f`
- warn with `wdsync doctor` when source and destination `HEAD` differ or the destination repo is already dirty

> Note:
> It includes tracked unstaged files, tracked staged files, and untracked files,
> including nested files in untracked directories. In v1 it intentionally does
> not do delete propagation, patch-apply checks, staging/index mirroring, or
> global config.

## Prerequisites

Get `git` available in WSL and Windows (`git.exe`), plus `rsync`, `wslpath`,
Python 3.11+, and either `uv` or `pip`; the source repo must be reachable as
`/mnt/<drive>/...`.

## Install

- [Read the detailed Setup guide here](./SETUP.md) | Recommended install path:

```bash
uv tool install wdsync
```

Alternative install path with `pip` after python venv:

```bash
python -m pip install wdsync
```

## Per-Project Config

Each destination WSL repo gets a local `.wdsync` file at the repo root:

```ini
SRC=/mnt/c/Users/YourName/path/to/WindowsRepo
```

Example:

```ini
SRC=/mnt/c/Users/<User>/Documents/Projects/<ProjectName>
```

`wdsync init` writes this file for you and adds `.wdsync` to the destination
repo's `.git/info/exclude` so it stays local.

## Quick Start

From inside the destination WSL repo:

```bash
wdsync init /mnt/c/Users/YourName/path/to/WindowsRepo
wdsync
wdsync sync
```

Doctor mode: Explain potential sync risks from source and destination state:

```bash
wdsync doctor
```

If you want to contribute or work on the codebase itself, use:

- [DEVELOPER_SETUP](./docs/DEVELOPER_SETUP.md) for contributor environment setup

Additional references:

- [CHANGELOG](./CHANGELOG.md) for release history

## Project Layout

```text
wdsync/
├── docs/
├── src/ [config, doctor, preview, shell, sync, sync, runner ...]
│   └── wdsync/
├── scripts/
│   ├── bash/
│   └── fish/
└── tests/
```

## Commands

| Command                | JSON Output                       | Purpose                                                          |
| ---------------------- | --------------------------------- | ---------------------------------------------------------------- |
| `wdsync`               | Yes, with `wdsync --json`         | Preview the current source dirty set.                            |
| `wdsync preview`       | Yes, with `wdsync preview --json` | Explicit preview mode.                                           |
| `wdsync sync`          | Yes, with `wdsync sync --json`    | Copy the planned dirty files into the current WSL repo.          |
| `wdsync init <SRC>`    | No                                | Create `.wdsync` for the current destination repo.               |
| `wdsync doctor`        | Yes, with `wdsync doctor --json`  | Show advisory sync-risk checks for source and destination state. |
| `wdsync shell install` | No                                | Install optional shell helpers and completions.                  |

## Git Status Labels Passed

| `[unstaged] [ M]` | `[staged] [M ]` | `[both] [MM]` | `[new] [??]` | `[added] [A ]` | `[added+mod] [AM]` | `[renamed] [R ]` | `[copied] [C ]` | `[deleted] [ D]` | fallback `[changed]` |

## Shell Integration

The CLI itself is shell-agnostic once installed. Optional shell helpers can be
installed with:

```bash
wdsync shell install
```

Override shell detection when needed:

```bash
wdsync shell install --shell fish
wdsync shell install --shell bash
wdsync shell install --shell zsh
```

What `shell install` does:

- auto-detects `fish`, `bash`, or `zsh`
- installs completion assets
- installs a `wdsync-init` helper wrapper
- installs fish function delegates when using fish

The `scripts/` directory contains thin repo-local wrapper examples that
delegate to the installed CLI or fall back to `uv run`.

- `scripts/bash/` contains executable shell wrappers
- `scripts/fish/` contains fish functions
- the bash wrappers also work fine as standalone executable helpers from zsh

## Important Behavior Notes

Source dirty-file detection comes from `git.exe`, not Linux Git. Preview shows
the full source dirty set rather than a destination diff, and sync copies file
contents only. A source staged file does not remain staged in the destination
repo. Deleted files are previewed but skipped in v1 so they never break
`rsync`, while renames and copies are parsed correctly from porcelain v1 `-z`
and untracked directories are expanded to leaf file paths.

## Limitations

`wdsync` is WSL-only, supports one source path per destination repo, and
expects the source path to live under `/mnt/<drive>/...`. In v1 it does not
propagate deletes, run patch-apply checks, or support post-sync hooks.

See [IN_DEVELOPMENT.md](docs/IN_DEVELOPMENT.md) for the roadmap beyond the current
Python CLI baseline.

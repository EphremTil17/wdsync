# wdsync

`wdsync` is a cross-environment (WSL <-> Windows) Python CLI for mirroring the dirty working tree
between matching WSL and Windows Git repositories without requiring a commit,
push, or pull cycle.

It is built for the workflow where:

- your primary editing happens to be on Windows for whatever reason (Flutter, VS Studio, .NET development, etc.)
- your backend, scripts, containers, or Linux tooling run in WSL either for prod or testing parity
- you want the WSL repo to mirror the current Windows dirty-set (staged and unstaged changes) on demand

The key design choice is that `wdsync` reads each source repo with the git
implementation native to that repo (`git` on WSL, `git.exe` on Windows), so
the sync set matches what that environment considers dirty rather than what the
other side infers through translated paths.

## What It Does

From inside a git repo, `wdsync` will:

- auto-detect the repo identity via remote URL or root commit SHA
- initialize local wdsync state with `wdsync init`
- discover and link the peer repo via RPC with `wdsync connect`
- establish the connection on both repos from a single `connect` call
- remove only the saved peer link with `wdsync disconnect`
- remove local wdsync state entirely with `wdsync deinit`
- fetch (pull from peer into the local repo) with `wdsync fetch`
- send (push from the local repo to the peer) with `wdsync send`
- show a unified status of both repos with `wdsync status`

> Note:
> It includes tracked unstaged files, tracked staged files, and untracked files,
> including nested files in untracked directories. Deleted files detected in the
> source are propagated to the destination. If a
> deletion fails due to permissions, `wdsync` prompts to retry with `sudo`. Files
> with local changes in the destination are never deleted. It does not yet do
> patch-apply checks, staging/index mirroring, or global config.

## Prerequisites

Get `git` available in WSL and Windows (`git.exe`), plus `rsync`, `wslpath`,
Python 3.11+, and either `uv` or `pip`; the source repo must be reachable as
`/mnt/<drive>/...`.

`wdsync` does not install `rsync` for you. It must already be available:

- WSL/Linux: install it system-wide, for example `sudo apt install rsync`
- Windows: `wdsync` uses `wsl.exe --exec rsync`, so install `rsync` inside the
  target WSL distro and verify with `wsl.exe --exec rsync --version`

## Install

- [Read the detailed Setup guide here](./SETUP.md) | Recommended install path:

```bash
uv tool install wdsync
# or Alternative install path with `pip` after python venv:
python -m pip install wdsync
```

## Per-Project Config

Running `wdsync init` inside a git repo creates:

- A `.wdsync` marker file at the repo root (added to `.git/info/exclude`)
- A `.git/wdsync/config.json` with the repo's identity (remote URL + root commit SHA)

No manual path configuration needed. The identity is used to match repos
during `wdsync connect`.

## Quick Start

```bash
# On each side (WSL and Windows), inside the repo:
wdsync init

# From either side, discover and link the peer:
wdsync connect

# After one successful connect, both repos are configured.
# Daily use from either side:
wdsync status        # see both repos' dirty files, conflicts, risk
wdsync fetch         # pull from peer into local repo
wdsync send          # push from local repo to peer
```

If you want to contribute or work on the codebase itself, use:

- [DEVELOPER_SETUP](./docs/DEVELOPER_SETUP.md) for contributor environment setup

Additional references:

- [CHANGELOG](./CHANGELOG.md) for release history

## Project Layout

```text
wdsync/
├── docs/                        # Design documents and roadmap
├── scripts/                     # Repo-local shell wrapper examples
│   ├── bash/
│   └── fish/
├── src/wdsync/                  # Published package source
│   ├── core/                    # Foundation: models, config, runner, exceptions, logging
│   ├── git/                     # Git state readers and porcelain parsing
│   ├── sync/                    # Sync pipeline: planner, engine, deleter, manifest, conflicts
│   ├── rpc/                     # RPC client, peer discovery, connect flow, request handlers
│   ├── output/                  # Human-readable and JSON formatters
│   ├── cli/                     # Typer CLI command definitions
│   └── shell/                   # Shell completion and helper installation
└── tests/                       # Mirrors src/ structure with unit and integration tests
```

## Sync Rules

| Scenario                                              | Behavior                                           |
| ----------------------------------------------------- | -------------------------------------------------- |
| File modified in source only                          | Copied to destination                              |
| File modified in destination only                     | Not touched (destination changes are preserved)    |
| File modified on both sides with different content    | **Conflict** — skipped unless `--force` is used    |
| File modified on both sides with identical content    | Reported as already synced on both sides           |
| File deleted in source (tracked)                      | Deleted from destination                           |
| File deleted in source (mirrored, previously synced)  | Reconciled from destination via pair-owned mirrored-path tracking |
| File deleted then restored in source                  | Restored in destination via `git restore`          |
| Deleted file has local changes in destination         | Skipped to avoid data loss                         |
| Permission denied on deletion (WSL path)              | Prompts for `sudo` retry                           |
| Permission denied on deletion (Windows path)          | Skipped — `sudo` has no authority over NTFS ACLs   |
| Path traversal attempt (`../../etc/passwd`)           | Blocked                                            |
| Empty parent directory after deletion                 | Pruned automatically                               |
| Source staged file synced to destination              | Copied as content only — not staged in destination |
| Untracked directory in source                         | Expanded to leaf file paths and synced             |

## Commands

| Command                | JSON Output                      | Purpose                                                                  |
| ---------------------- | -------------------------------- | ------------------------------------------------------------------------ |
| `wdsync init`          | No                               | Create `.wdsync` and `.git/wdsync/config.json` for this repo.            |
| `wdsync connect`       | No                               | Discover peer via RPC, verify identity, and save the link on both repos. |
| `wdsync disconnect`    | No                               | Remove the saved peer from config.                                       |
| `wdsync deinit`        | No                               | Remove local wdsync state and restore the repo to a pre-init state.      |
| `wdsync fetch`         | Yes, with `wdsync fetch --json`  | Pull peer dirty tree into the local repo. Use `--force` for conflicts.   |
| `wdsync send`          | Yes, with `wdsync send --json`   | Push local dirty tree to the peer. Use `--force` for conflicts.          |
| `wdsync status`        | Yes, with `wdsync status --json` | Unified view of both repos, conflicts, and risk.                         |
| `wdsync shell install` | No                               | Install optional shell helpers and completions.                          |

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

Each side reads its own dirty state using its native git (`git` on WSL,
`git.exe` on Windows). `connect` is bilateral: one successful `wdsync connect`
stores peer configuration on both repos, and either repo can then run
`status`, `fetch`, or `send`. Repo inspection and peer-side delete/restore run
natively through RPC, while file transfer still uses rsync over translated peer
paths. Conflicts are refined beyond simple path overlap: if the same dirty path
exists on both sides but Git-normalized content fingerprints match, wdsync
shows it as already synced on both sides instead of a true conflict. State
lives under `.git/wdsync/`, with a repo-root `.wdsync` marker for visibility.
`disconnect` removes only the peer link; `deinit` removes local wdsync state
entirely. See the Sync Rules table above for full details.

## Limitations

wdsync currently depends on WSL/Windows path interop: Windows repos must be
reachable from WSL as `/mnt/<drive>/...`, and WSL repos must be reachable from
Windows through `\\wsl.localhost\...` path translation. `connect` can be
initiated from either side. File transfer still depends on translated paths via
rsync, but repo inspection and peer-side delete/restore are RPC-native. wdsync
does not support empty repos (at least one commit is required for identity
resolution). It does not yet run patch-apply checks or support post-sync hooks.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for design decisions and
[IN_DEVELOPMENT.md](docs/IN_DEVELOPMENT.md) for the roadmap.

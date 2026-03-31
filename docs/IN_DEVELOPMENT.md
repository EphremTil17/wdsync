# In Development

This document tracks the next set of ideas after the Python CLI v1 baseline.

Today, `wdsync` already ships:

- `preview`, `sync`, `init`, `doctor`, and `shell install`
- `git.exe`-based source dirty detection
- correct rename/copy parsing for porcelain v1 `-z`
- deletion propagation with sudo escalation and destination-modified guard
- advisory-only `doctor` checks for HEAD mismatch and dirty destination

The items below are the next layer of safety and intelligence beyond that
baseline.

The guiding philosophy is:

- `wdsync` should stay fast and practical for day-to-day use
- safety features should begin as warnings and checks, not hard blockers
- users should be able to override guardrails with a deliberate `--force`
- checks should help users reason about sync risk rather than replace Git as the
  source of truth

In other words, these features should act as advisory systems first.

## Design Direction

Today, `wdsync` answers:

- "What files does Git for Windows say are dirty?"
- "Mirror those files into my WSL repo"

Future versions can also help answer:

- "Is the WSL repo on the same base commit?"
- "Will these changes apply cleanly?"
- "Am I about to overwrite something risky?"
- "Should I sync, or should I rebase/pull first?"

The preferred model is:

1. run checks
2. display warnings or risk levels
3. let the user continue normally
4. allow `--force` when the user intentionally wants to bypass warnings

## Proposed Features

### 1. HEAD Mismatch Warning

Compare the source repo `HEAD` and destination repo `HEAD`.

Potential outputs:

- same commit
- source ahead of destination
- destination ahead of source
- diverged
- unrelated history

Why this is useful:

- immediately explains why a sync may behave unexpectedly
- helps users distinguish "dirty working tree sync" from "same branch / same base"
- catches a very common source of confusion when Windows and WSL are both active

Suggested behavior:

- warning only by default
- allow sync to continue
- `--force` suppresses the warning prompt if interactive prompting is ever added

Example warning:

```text
warning: source and destination HEAD differ
  source:      abc1234
  destination: def5678
  relation:    diverged
sync can continue, but destination may become a mixed-state tree
```

### 2. Dirty Destination Warning

Detect whether the destination WSL repo already has local modifications before
syncing.

Why this is useful:

- prevents accidental blending of Windows changes into an already modified WSL
  working tree
- makes it clear when `wdsync` is being used on a "dirty-on-both-sides" repo
- encourages better operator awareness before tests are run

Suggested behavior:

- warning only by default
- include counts for modified/staged/untracked destination files
- allow `--force` to continue immediately

Example warning:

```text
warning: destination repo is not clean
  modified: 4
  staged:   1
  untracked: 3
sync can continue, but files may be overwritten into an already dirty tree
```

### 3. Patch Clean-Apply Check

Generate a patch from the Windows source dirty files and test whether it would
apply cleanly in the destination repo using `git apply --check`.

This is one of the strongest near-term features because it answers a real
question directly:

- "Would these current source-side changes apply cleanly here as a patch?"

Why this is useful:

- catches drift that raw file mirroring cannot explain
- helps detect whether the destination repo is too far behind or too different
- gives users a much better risk signal than file counts alone

Important note:

This should still be treated as a check, not an absolute truth.

A patch might fail to apply cleanly while file mirroring is still acceptable for
the user's short-term testing workflow. Conversely, a patch may apply cleanly
but still lead to runtime or semantic breakage.

Suggested behavior:

- off by default at first, then optionally enabled by config
- surface results as:
  - clean apply
  - partial / risky
  - failed apply
- `--force` should still allow a raw file sync

### 4. Commit Relationship / Merge-Base Analysis

If source and destination histories are related, compute their merge-base and
describe the relationship in human terms.

Potential classifications:

- same commit
- source ahead by N commits
- destination ahead by N commits
- diverged from merge-base
- unrelated histories

Why this is useful:

- gives the user contextual Git information before sync
- helps explain whether a patch failure is expected
- makes `wdsync` more trustworthy as a diagnostic helper

This would be especially useful in teams where:

- Windows side is doing active editor work
- WSL side is a quick local test mirror
- occasional rebases, rebases-in-progress, or missed pulls happen

### 5. Risk Scoring / Sync Doctor

Add a "doctor" style mode that runs all checks and produces a summary.

Possible command:

```bash
wdsync doctor
```

Possible output:

```text
Source status:           dirty
Destination status:      dirty
HEAD relation:           diverged
Patch apply check:       failed
Risk level:              high
Recommendation:          pull/rebase destination or sync with --force
```

Why this is useful:

- gives users a single preflight summary
- separates diagnosis from the actual sync action
- creates a good future UX path without making normal sync slower by default

### 6. Scope Controls

Support more selective sync modes:

- `--staged-only`
- `--tracked-only`
- `--new-only`
- `--unstaged-only`

Why this is useful:

- lets users mirror only the exact class of changes they care about
- helps when new files are still experimental
- supports workflows where staging is used as an intentional "sync set"

These would also compose nicely with future checks.

### 7. Delete Propagation — SHIPPED in v0.2.0

Deletion propagation is now built in. Files deleted in the source are removed
from the destination during `wdsync sync`. Safety guards:

- files with local changes in the destination are skipped
- path traversal attempts are blocked
- permission errors prompt for `sudo` retry
- absent files are silently skipped (idempotent)
- empty parent directories are pruned automatically

### 8. Post-Sync Validation Hooks

Allow projects to define optional validation commands in `.wdsync`.

Examples:

```ini
POST_SYNC_CHECK=pytest backend/tests/test_warmup.py
POST_SYNC_CHECK=flutter test
POST_SYNC_CHECK=python -m pyright backend
```

Why this is useful:

- turns `wdsync` into a more complete sync-and-verify workflow
- helps validate that the mirror is actually ready for use
- keeps project-specific logic out of the core tool

Recommended behavior:

- disabled unless configured
- failure should warn, not silently stop
- `--force` should still allow sync even if checks fail

### 9. Include / Exclude Rules

Extend `.wdsync` with optional include and exclude patterns.

Examples:

```ini
SRC=/mnt/c/Users/YourName/path/to/project
EXCLUDE=flutter_client/build/**
EXCLUDE=.venv/**
INCLUDE=backend/**
```

Why this is useful:

- reduces noise in large monorepos
- keeps caches and generated artifacts out of sync flows
- lets teams tailor `wdsync` without modifying the scripts

### 10. Machine-Readable Output

Add a JSON mode:

```bash
wdsync --list-json
```

Why this is useful:

- supports editor tooling
- supports wrappers, scripts, and launch tasks
- makes it easier to integrate `wdsync` into project-specific automation

Example fields:

- file path
- porcelain code
- friendly status label
- source HEAD
- destination HEAD
- warnings raised

## Suggested Warning Model

The preferred enforcement model is:

- checks warn by default
- sync remains allowed
- `--force` explicitly suppresses warning-driven hesitation

This keeps `wdsync` practical under time pressure while still making risk
visible.

Recommended severity tiers:

- `info`
  - source has dirty files
  - destination is clean
- `warn`
  - destination dirty
  - HEAD mismatch
  - destination ahead of source
- `high-risk`
  - patch does not apply cleanly
  - histories diverged
  - unrelated histories

Even `high-risk` should initially remain advisory unless a future version adds
an explicit "strict mode".

## Proposed CLI Evolution

Current:

```bash
wdsync
wdsync -f
```

Potential next steps:

```bash
wdsync
wdsync -f
wdsync --staged-only
wdsync --tracked-only
wdsync --delete
wdsync --check-apply
wdsync doctor
wdsync --list-json
wdsync --force
```

## Recommended Implementation Order

For the best balance of value and complexity:

1. ~~HEAD mismatch warning~~ — shipped in v0.1.0
2. ~~dirty destination warning~~ — shipped in v0.1.0
3. scope flags (`--staged-only`, `--tracked-only`, `--new-only`)
4. patch clean-apply check
5. merge-base / commit relationship summary
6. ~~delete propagation~~ — shipped in v0.2.0
7. two-way sync (`wdsync send` / `wdsync fetch`)
8. post-sync validation hooks
9. ~~JSON output~~ — shipped in v0.1.0

## Philosophy

`wdsync` should not try to replace Git.

Instead, it should:

- understand Git well enough to provide strong safety signals
- mirror working-tree changes quickly
- surface risks clearly
- let advanced users override those warnings intentionally

That balance is what makes it useful as a real development tool rather than
just a convenience script.

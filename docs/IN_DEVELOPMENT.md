# In Development

This document tracks features and improvements under consideration for future
releases. Items marked **SHIPPED** have landed; everything else is potential
future work.

## Current State (v0.6.0)

wdsync ships a complete WSL/Windows sync workflow:

- `init`, `connect`, `disconnect`, `fetch`, `send`, `status`, `shell install`
- Identity-based repo linking via remote URL or root commit SHA
- Bilateral RPC-based peer discovery and peer configuration
- Environment-aware peer discovery with layered search (cached root, cwd, common dirs)
- Two-way sync with conflict detection and `--force` override
- Deletion propagation with sudo escalation and destination-modified guard
- Reconciliation of previously deleted files via `git restore`
- Untracked file manifest for orphan cleanup
- Structured logging via loguru (console + file)
- JSON output for `status`, `fetch`, and `send`
- Runtime overrides for WSL distro and peer launch commands
- Local teardown with `wdsync deinit`

## Shipped Features

| Feature | Version | Notes |
|---|---|---|
| Deletion propagation | v0.2.0 | Tracked + untracked via manifest |
| HEAD mismatch warning | v0.1.0 | Part of doctor/status |
| Dirty destination warning | v0.1.0 | Part of doctor/status |
| JSON output | v0.1.0 | `--json` on preview/sync |
| Two-way sync (fetch/send) | v0.4.0 | DirectionConfig abstraction |
| Unified status command | v0.4.0 | Absorbed preview + doctor |
| Conflict detection | v0.4.0 | Set intersection + `--force` |
| Structured logging | v0.4.0 | loguru, two-stage (console + file) |
| RPC peer connect | v0.5.0 | Handshake + locate_repo + configure_peer + identity match |
| Windows-initiated connect | v0.5.0 | `wsl.exe --exec wdsync rpc` path |
| Legacy code removal | v0.5.0 | Clean break from INI-era config |
| Peer-native repo operations | v0.5.0 | RPC `status`, `delete`, `restore`, `compare_heads` |
| Local deinitialization | v0.6.0 | `wdsync deinit` removes local wdsync-owned state |

## Planned Features

### Scope Controls

Support more selective sync modes:

- `--staged-only` — mirror only staged changes
- `--tracked-only` — skip untracked files
- `--new-only` — only sync new/untracked files

### Patch Clean-Apply Check

Generate a patch from source dirty files and test with `git apply --check`.
Answers: "Would these changes apply cleanly?" — a stronger risk signal than
file counts alone.

### Post-Sync Validation Hooks

Allow projects to define optional validation commands that run after sync:

```json
{
  "post_sync": ["pytest backend/tests/test_warmup.py", "python -m pyright backend"]
}
```

### Include / Exclude Rules

Filter the sync set with glob patterns:

```json
{
  "exclude": ["flutter_client/build/**", ".venv/**"],
  "include": ["backend/**"]
}
```

### Windows Companion Binary

PyInstaller/Nuitka standalone `.exe` for Windows users who don't want Python
installed. The RPC architecture already supports this — just swap
`python.exe -m wdsync` for the standalone binary path.

## Philosophy

`wdsync` should not try to replace Git. Instead, it should:

- understand Git well enough to provide strong safety signals
- mirror working-tree changes quickly
- surface risks clearly
- let advanced users override those warnings intentionally

That balance is what makes it useful as a real development tool rather than
just a convenience script.

# Architecture

This document captures the design decisions, principles, and technical
reasoning behind wdsync. It serves as the authoritative reference for why
things are built the way they are.

---

## Design Principles

1. **Each side manages its own filesystem.** The WSL instance never manipulates
   Windows files directly (no `/mnt/c/` deletions, restores, or permission
   management). The Windows instance never touches `\\wsl$\`. Each side uses
   its own native tools: `git` on WSL, `git.exe` on Windows, native `pathlib`
   for file operations, native privilege escalation mechanisms.

2. **The only thing that crosses the boundary is intent.** One side tells the
   other "these files changed, these were deleted, these need restoring" — the
   receiving side executes locally using its own native tools.

3. **Git is the source of truth.** wdsync reads `git status` to determine
   what's dirty, uses `git restore` to recover files, and uses git's remote
   URL and root commit SHA for identity matching. It does not maintain a
   separate file index or database.

4. **Advisory first, blocking second.** Warnings are shown, not hidden.
   Conflicts are reported and skipped by default. `--force` is available but
   never the default. The user should always understand what wdsync will do
   before it does it.

5. **Zero friction setup.** `wdsync init` auto-detects the repo root and
   identity. `wdsync connect` discovers the peer automatically. No manual
   path entry unless auto-detection fails.

---

## Identity Resolution

When two repos need to be linked, wdsync must verify they are clones of the
same project. This is done through a three-step resolution chain:

| Step | Method | How It Works |
|---|---|---|
| 1 | Remote URL match | Compare `git remote get-url origin` on both sides. Normalized (trailing `/` and `.git` stripped). |
| 2 | Root commit SHA | If no remote exists, compare `git rev-list --max-parents=0 HEAD`. Every repo with at least one commit has a root commit. If they share it, they're clones. |
| 3 | Reject | If neither matches, the repos are unrelated. wdsync refuses to link them and tells the user why. |

**Why this order:** Remote URL is the fastest and most common case. Root
commit SHA covers air-gapped and local-only development where no remote is
configured. Both methods are unforgeable — you can't accidentally link
unrelated repos.

---

## Cross-Environment Communication

wdsync uses a **subprocess stdin/stdout RPC model** for cross-environment
communication.

### Why Not TCP/Named Pipes/Polling?

| Approach | Rejected Because |
|---|---|
| Localhost TCP | Requires a listening server, port management, firewall concerns |
| Named Pipes | Platform-specific, harder to debug |
| Shared filesystem polling | Slow, race conditions, latency |
| **Subprocess stdin/stdout** | **Chosen** — no server, no port, no polling. Same pattern as `git.exe` from WSL. |

### How It Works

1. The initiating side (e.g., WSL) spawns the counterpart process:
   `python.exe -m wdsync rpc` (for Windows) or `python3 -m wdsync rpc` (for WSL)
2. Communication is JSON-over-stdin/stdout, one message per line
3. The spawned process reads a command, executes it locally using native tools,
   and responds with the result
4. File content transfer uses rsync (battle-tested, handles large files efficiently)
5. All other operations (delete, restore, status) are executed natively by each side

### Protocol Versioning

Every RPC message includes a `version` field. The handshake verifies version
compatibility before any operations. This prevents the "WSL side updated but
Windows side didn't" breakage.

```json
{"version": 1, "method": "handshake", "args": {}}
{"version": 1, "ok": true, "data": {"protocol_version": 1}, "error": null}
```

---

## Command Surface

| Command | Purpose |
|---|---|
| `wdsync init` | Auto-detect repo root and identity, write config |
| `wdsync connect` | Discover peer repo, establish the two-way link |
| `wdsync disconnect` | Remove the link |
| `wdsync fetch` | Pull from peer into local repo |
| `wdsync send` | Push from local repo to peer |
| `wdsync status` | Unified view: dirty files, conflicts, HEAD relation, risk |

**Global flags:**
- `--debug` — enable verbose DEBUG-level logging on any command
- `--json` — structured JSON output (where applicable)
- `--force` — override conflict detection on `fetch` and `send`

### Removed Commands (Clean Break)

| Removed | Reason |
|---|---|
| `wdsync sync` | Redundant with `fetch` and repeats the project name |
| `wdsync -f` | Was an alias for `sync` which was an alias for `fetch` |
| `wdsync preview` | Absorbed into `status` |
| `wdsync doctor` | Absorbed into `status` |

---

## Configuration and State

All wdsync state lives under `.git/wdsync/` to keep the repo root clean:

```
.git/wdsync/
├── config.json         # Identity, peer command, connection state
├── manifest.json       # Previously synced untracked files (for orphan cleanup)
└── wdsync.log          # Application log (rotated at 5MB, 3 retained)
```

A minimal `.wdsync` marker file at the repo root signals that this repo is
wdsync-linked. It contains no implementation details — just a human-readable
note pointing to the config location.

### Why This Split?

| Concern | Decision | Reasoning |
|---|---|---|
| Visibility | `.wdsync` at repo root | Users can see the repo is linked. Easy to discover. |
| Implementation details | `.git/wdsync/config.json` | No `.gitignore` entry needed. Invisible to `git status`. |
| Logs | `.git/wdsync/wdsync.log` | Same directory. One `cat` to debug. |
| Manifest | `.git/wdsync/manifest.json` | Keeps all state co-located. |

### Config Format

```json
{
  "version": 1,
  "identity": {
    "remote_url": "https://github.com/user/repo.git",
    "root_commit": "abc123def456..."
  },
  "peer": {
    "command": "python.exe -m wdsync",
    "connected": true
  },
  "environment": "wsl"
}
```

The `identity` block is populated during `init`. The `peer` block is populated
during `connect`. The `environment` is auto-detected.

---

## Logging Architecture

wdsync uses [loguru](https://github.com/Delgan/loguru) for structured logging.

### Log Levels and Usage

| Level | Usage | Example |
|---|---|---|
| `DEBUG` | Subprocess commands, internal state, config loading | `Running: git status --porcelain=v1 -z` |
| `INFO` | Sync progress, file counts, operation summaries | `Synced 3 file(s).` |
| `SUCCESS` | Completion messages | `Done. Fetch complete.` |
| `WARNING` | Advisory — destination dirty, HEAD mismatch, forced conflicts | `Forcing sync of conflicting file: main.py` |
| `ERROR` | Conflicts, permission denied, sync failures | `Conflict: main.py modified on both sides` |

### Output Routing

| Destination | Level | Format | Purpose |
|---|---|---|---|
| stderr (console) | INFO+ (or DEBUG with `--debug`) | Concise for INFO/SUCCESS, verbose for others | User-facing feedback |
| `.git/wdsync/wdsync.log` | DEBUG (always) | Verbose with file/func/line | Post-mortem debugging |
| stdout | N/A | Raw JSON | Only used for `--json` structured output |

### Why stderr for Console Output?

`--json` mode writes structured data to stdout. If log messages also went to
stdout, they would corrupt the JSON. By routing all human-readable output to
stderr, stdout remains a clean channel for machine-readable output.

### Log File Strategy

One log file, not many. Connection cycles are distinguished by timestamps and
log entries (`connect started`, `fetch complete`, `disconnect`), not separate
files. Reasons:

1. **Debuggability** — `cat .git/wdsync/wdsync.log` gives the full chronological
   history. No navigating subdirectories.
2. **Simplicity** — no file proliferation, no cleanup logic for old session dirs.
3. **Greppability** — `grep "ERROR" wdsync.log` finds every error across all
   sessions instantly.

Rotation at 5MB with 3 retained files prevents unbounded growth.

---

## Sync Rules

| Scenario | Behavior |
|---|---|
| File modified in source only | Copied to destination |
| File modified in destination only | Not touched (destination changes preserved) |
| File modified on both sides | **Conflict** — skipped unless `--force` |
| File deleted in source (tracked) | Deleted from destination (natively) |
| File deleted in source (untracked, previously synced) | Deleted via manifest tracking |
| File deleted then restored in source | Restored in destination via native `git restore` |
| Deleted file has local changes in destination | Skipped to avoid data loss |
| Permission denied on deletion | Handled natively by each side (sudo on WSL, UAC on Windows) |
| Path traversal attempt | Blocked |
| Empty parent directory after deletion | Pruned automatically |

---

## Conflict Detection

A conflict exists when the same file path appears in both the source and
destination dirty sets. Detection is a simple set intersection:

```
source_dirty = {entry.path for entry in source_state.entries}
dest_dirty   = {entry.path for entry in dest_state.entries}
conflicts    = source_dirty & dest_dirty
```

### Conflict Resolution

| Mode | Behavior |
|---|---|
| Default | Log conflicts at ERROR level, skip conflicting files, sync the rest |
| `--force` | Log conflicts at WARNING level, sync everything including conflicts |

There is no automatic merge, three-way diff, or "newest wins" heuristic.
wdsync is a file mirror, not a merge tool. If both sides changed the same
file, the user must decide which version wins.

---

## Environment Detection

wdsync auto-detects its runtime environment:

| Environment | Detection Method |
|---|---|
| WSL | `is_wsl()` — checks `/proc/sys/kernel/osrelease` for "microsoft" |
| Windows | `sys.platform == "win32"` |
| Linux | Neither of the above |

This determines:
- Which git executable to use by default (`git` vs `git.exe`)
- Which privilege escalation to offer (sudo vs UAC)
- How to spawn the peer process
- What to write in the config's `environment` field

---

## Future Considerations

These are not planned for implementation yet but inform current design decisions:

- **Native file transfer** — replace rsync with RPC-based file payloads for
  repos that don't have rsync installed
- **Windows companion binary** — PyInstaller/Nuitka standalone `.exe` for
  Windows users who don't want Python installed
- **Rust rewrite** — for startup time and single-binary distribution, not for
  runtime performance (the bottleneck is subprocess calls, not Python)
- **Multi-remote support** — linking more than two repos
- **Post-sync hooks** — project-defined validation commands after sync

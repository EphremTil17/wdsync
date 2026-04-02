# Architecture

This document captures the design decisions, principles, and technical
reasoning behind wdsync. It serves as the authoritative reference for why
things are built the way they are.

---

## Design Principles

1. **Connection state is symmetric.** `wdsync connect` should leave both repos
   configured after one successful call. No "primary" side should be required
   after the initial handshake.

2. **Cross-environment boundaries are explicit.** Peer discovery, repo
   inspection, and peer-side mutation happen over RPC. Only file transfer uses
   translated peer paths, with environment-specific subprocess commands chosen
   in one place rather than leaking ad hoc WSL/Windows branching through the
   codebase.

3. **Git is the source of truth.** wdsync reads `git status` to determine
   what's dirty, uses `git restore` to recover files, and uses git's remote
   URL and root commit SHA for identity matching. It does not maintain a
   separate file index or database.

4. **Advisory first, blocking second.** Warnings are shown, not hidden.
   Conflicts are reported and skipped by default. `--force` is available but
   never the default. The user should always understand what wdsync will do
   before it does it.

5. **Zero friction setup.** `wdsync init` auto-detects the repo root and
   identity. `wdsync connect` discovers the peer automatically and persists the
   reverse peer configuration. No manual path entry unless auto-detection or
   custom runtime layout requires an override.

### Current Release Boundary

The current release uses a split control/data plane:

- peer discovery and connection are bilateral RPC operations
- peer repo inspection (`STATUS`) is RPC-native
- peer-side delete and restore are RPC-native
- file transfer uses rsync over translated peer paths

The only cross-boundary translated-path operation left is file transfer.

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

1. The initiating side spawns the counterpart process using environment-aware
   command selection. By default this is a validated `wdsync.exe` path from WSL
   and a validated WSL `wdsync` executable path wrapped by `wsl.exe --exec`
   from Windows, with runtime overrides available.
2. Communication is JSON-over-stdin/stdout, one message per line
3. The spawned process reads a command, executes it locally using native tools,
   and responds with the result
4. File content transfer uses rsync (battle-tested, handles large files efficiently)
5. Connection/config propagation, status inspection, and peer-side mutation all
   use RPC; rsync remains the only translated-path data-plane operation

### Protocol Design

Every RPC message includes a `version` field. The connect flow uses three
separate RPC calls:

1. **Handshake** — protocol negotiation only. Verifies version compatibility
   and exchanges capabilities. No identity or repo resolution.
2. **Locate repo** — the caller sends its identity; the peer searches for a
   matching local repo and returns the match along with its own identity.
3. **Configure peer** — the initiator sends the reverse peer configuration so
   the discovered repo saves the same link locally. If the peer repo has not
   been initialized yet, it is initialized before saving the link.

This separation keeps the handshake fast and decoupled from repo state.

```json
// Handshake: protocol only
{"version": 1, "method": "handshake", "args": {}}
{"version": 1, "ok": true, "data": {"protocol_version": 1, "capabilities": ["locate_repo", "configure_peer", "status", "delete", "restore", "compare_heads"]}, "error": null}

// Locate repo: identity + discovery
{"version": 1, "method": "locate_repo", "args": {"identity": {...}, "cached_root": "C:\\..."}}
{"version": 1, "ok": true, "data": {"identity": {...}, "repo_root": "...", "matched_by": "remote_url"}, "error": null}

// Configure peer: save reverse link on the discovered repo
{"version": 1, "method": "configure_peer", "args": {"repo_root_native": "...", "peer": {...}, "allow_initialize": true}}
{"version": 1, "ok": true, "data": {"configured": true}, "error": null}
```

### Peer Discovery

The `locate_repo` handler runs a layered search on the peer side:

Before any candidate is accepted, it must satisfy two conditions:

1. **Identity match** — it must resolve to the same logical project
   (`remote_url` first, then `root_commits`)
2. **Native-path match** — it must be native to the peer environment, not just
   reachable through a mount bridge

Examples:
- A WSL peer accepts `/home/...` repos but rejects `/mnt/<drive>/...`
- A Windows peer accepts `C:\...` repos but rejects `\\wsl$...` /
  `\\wsl.localhost\...`

This rule prevents the peer from rediscovering the initiator repo through a
cross-mounted filesystem view. Without it, a Windows-initiated connect could
accidentally bind the WSL peer to the Windows repo as seen at `/mnt/c/...`
instead of the real WSL working copy in `/home/...`.

With that constraint in place, discovery proceeds as a layered search:

1. **Cached root** — if the caller provides a previous native peer path, check
   it first (instant on reconnects)
2. **Peer cwd** — if the process cwd is a native matching git repo, done
3. **Common directories** — environment-aware scan of well-known project dirs
   (Windows: `~/source/repos`, `~/Documents/Projects`, `~/Projects`, `~/repos`,
   `~/dev`; WSL/Linux: `~/projects`, `~/repos`, `~/dev`, `~/src`)
4. **Bounded walk** — 2 levels deep per directory, cap at 50 candidates
5. **PermissionError** — caught and skipped silently

---

## Command Surface

| Command | Purpose |
|---|---|
| `wdsync init` | Auto-detect repo root and identity, write config |
| `wdsync connect` | Discover peer repo and establish the two-way link from either side |
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
    "remote_url": "https://github.com/user/repo",
    "root_commits": ["abc123def456..."]
  },
  "peer": {
    "command_argv": ["wdsync.exe"],
    "root": "/mnt/c/Users/user/repo",
    "root_native": "C:\\Users\\user\\repo"
  },
  "runtime": {
    "windows_peer_command_argv": ["wdsync.exe"],
    "wsl_peer_command_argv": ["wdsync"],
    "wsl_distro": "Ubuntu-24.04"
  }
}
```

The `identity` block is populated during `init` (remote URL normalized,
root commits sorted). The `peer` block is populated during `connect`
(`command_argv` as a list to avoid shell parsing, `root` is the locally
accessible translated path, `root_native` is the peer's filesystem path). The
optional `runtime` block persists peer-launch overrides such as custom command
argv and a preferred WSL distro. `repo_root` and `environment` are
runtime-derived — not persisted.

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
| File deleted in source (tracked) | Deleted from destination through the translated destination path |
| File deleted in source (untracked, previously synced) | Deleted via manifest tracking |
| File deleted then restored in source | Restored in destination via environment-appropriate `git restore` command |
| Deleted file has local changes in destination | Skipped to avoid data loss |
| Permission denied on deletion | WSL destinations may prompt for `sudo`; Windows-path failures are skipped |
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
- Whether `sudo` retry is meaningful for the current destination path
- How to resolve and spawn the peer process for the opposite environment
- Which common project directories to scan during peer discovery

---

## Future Considerations

These are not planned for implementation yet but inform current design decisions:

- **Native peer execution** — move delete/restore/status and possibly file
  transfer behind RPC so sync no longer depends on translated peer paths
- **Windows companion binary** — PyInstaller/Nuitka standalone `.exe` for
  Windows users who don't want Python installed
- **Rust rewrite** — for startup time and single-binary distribution, not for
  runtime performance (the bottleneck is subprocess calls, not Python)
- **Multi-remote support** — linking more than two repos
- **Post-sync hooks** — project-defined validation commands after sync

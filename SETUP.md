# Setup

This guide is for installing and using the published `wdsync` CLI.

If you want to work on the codebase itself, use
[DEVELOPER_SETUP.md](docs/DEVELOPER_SETUP.md).

## Prerequisites

Install prerequisites so the tool can run from either side:

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
- wdsync installed on both sides (WSL and Windows) for peer connect to work

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

On Windows (from PowerShell or cmd), install with:

```powershell
pip install wdsync
```

## 2. Verify The Install

```bash
wdsync --help
# or if you installed with `pip` into an active Python environment:
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

## 4. Initialize Both Repos

Run `wdsync init` inside each git repo (both WSL and Windows sides). The repo
must have at least one commit.

On WSL:

```bash
cd /path/to/your/wsl/repo
wdsync init
```

On Windows (from PowerShell/cmd, or via `python.exe` from WSL):

```powershell
cd C:\Users\YourName\path\to\WindowsRepo
wdsync init
```

This creates:

- A `.wdsync` marker file at the repo root (added to `.git/info/exclude`)
- A `.git/wdsync/config.json` with the repo's identity (remote URL + root commit SHA)

No manual path configuration is needed.

## 5. Connect To The Peer

Run `wdsync connect` from either repo:

```bash
wdsync connect
```

The initiating side spawns the peer in its native environment, performs a
protocol handshake, discovers the matching repo by identity (remote URL or root
commit SHA), and saves the peer connection in `.git/wdsync/config.json` on
both repos.

Optional connect overrides:

```bash
wdsync connect --wsl-distro Ubuntu-24.04
wdsync connect --windows-peer-command "python.exe -m wdsync"
wdsync connect --wsl-peer-command "python -m wdsync"
```

By default, `connect` resolves and validates a concrete peer executable before
it opens the RPC session. On Windows-initiated connects, that means wdsync will
prefer an explicit WSL executable such as `~/.local/bin/wdsync` instead of
assuming bare `wdsync` is available on the non-interactive WSL `PATH`.

If the peer repo is found in a common project directory
(`~/source/repos`, `~/Documents/Projects`, `~/Projects`, `~/repos`, `~/dev`),
connect will find it automatically. If auto-discovery fails, ensure `wdsync init`
was run on the peer side first.

## 6. Daily Use

```bash
# See both repos' dirty files, conflicts, and risk:
wdsync status

# Pull peer dirty tree into the local repo:
wdsync fetch

# Push local dirty tree to the peer:
wdsync send

# Use --force to override conflict detection:
wdsync fetch --force

# Get JSON output for scripting:
wdsync status --json
wdsync fetch --json
```

## 7. Disconnect

To remove the peer connection:

```bash
wdsync disconnect
```

You can reconnect later with `wdsync connect`.

## Notes

- `wdsync` must be run from inside a git repo.
- One successful `wdsync connect` configures both repos. After that, either
  side can run `status`, `fetch`, or `send`.
- It helps to be on the same branch in both repos, but it is not required.
- Source dirty detection comes from the git implementation native to the
  source repo (`git` on WSL, `git.exe` on Windows).
- Sync copies file contents only. A source staged file does not remain staged
  in the destination repo.
- The current release still performs file transfer and file mutation through
  translated WSL/Windows paths. Peer-side native delete/restore/status RPC
  dispatch is future work.
- Deleted source files are propagated: `wdsync fetch/send` removes them from
  the destination. Files with local changes in the destination are skipped to
  avoid data loss. If a deletion fails due to permissions, `wdsync` will prompt
  to retry with `sudo`.
- Empty repos (no commits) are not supported. Run `git commit` first.

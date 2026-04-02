from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

# Cross-environment smoke test prerequisites:
#
# 1. Run this test from WSL, not from native Windows.
# 2. Prepare two real clones of the same project:
#    - a WSL clone, for example: /home/<user>/projects/<repo>
#    - a Windows clone, for example: C:\Users\<user>\...\<repo>
# 3. Install the finished `wdsync` CLI globally in both environments.
# 4. Verify both installs work before running the test:
#    - in WSL: `wdsync --version`
#    - in Windows: `wdsync --version`
# 5. Export the required environment variables before invoking pytest:
#    - `WDSYNC_CROSSENV=1`
#    - `WDSYNC_CROSSENV_WSL_REPO=/home/<user>/projects/<repo>`
#    - `WDSYNC_CROSSENV_WINDOWS_REPO=C:\Users\<user>\...\<repo>`
# 6. Optionally override the installed command if `wdsync` is not directly on PATH:
#    - `WDSYNC_CROSSENV_WSL_CMD`
#    - `WDSYNC_CROSSENV_WINDOWS_CMD`
#
# Recommended invocation from WSL:
#
#     uv run pytest -m crossenv tests/test_crossenv_integration.py
#
# This test mutates only wdsync-managed local repo state (`init`, `connect`, `status`,
# `deinit`) and cleans that state up in a `finally` block.

pytestmark = pytest.mark.crossenv

_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:\\")


@dataclass(frozen=True)
class CrossEnvConfig:
    wsl_repo: Path
    windows_repo_native: str
    windows_repo_mounted: Path
    wsl_command: tuple[str, ...]
    windows_command: tuple[str, ...]


def _load_crossenv_config() -> CrossEnvConfig:
    if os.environ.get("WDSYNC_CROSSENV") != "1":
        pytest.skip("set WDSYNC_CROSSENV=1 to run cross-environment smoke tests")
    if not os.environ.get("WSL_DISTRO_NAME"):
        pytest.skip("cross-environment smoke test must be run from WSL")

    wsl_repo_raw = os.environ.get("WDSYNC_CROSSENV_WSL_REPO")
    windows_repo_raw = os.environ.get("WDSYNC_CROSSENV_WINDOWS_REPO")
    if not wsl_repo_raw or not windows_repo_raw:
        pytest.skip(
            "set WDSYNC_CROSSENV_WSL_REPO and WDSYNC_CROSSENV_WINDOWS_REPO "
            "to run cross-environment smoke tests"
        )

    wsl_repo = Path(wsl_repo_raw).expanduser()
    if not wsl_repo.exists():
        pytest.skip(f"WSL repo does not exist: {wsl_repo}")

    windows_repo_mounted = _windows_to_wsl_path(windows_repo_raw)
    if not windows_repo_mounted.exists():
        pytest.skip(f"Windows repo is not visible from WSL: {windows_repo_mounted}")

    return CrossEnvConfig(
        wsl_repo=wsl_repo,
        windows_repo_native=windows_repo_raw,
        windows_repo_mounted=windows_repo_mounted,
        wsl_command=_parse_command_env(os.environ.get("WDSYNC_CROSSENV_WSL_CMD"), posix=True)
        or ("wdsync",),
        windows_command=_parse_command_env(
            os.environ.get("WDSYNC_CROSSENV_WINDOWS_CMD"),
            posix=False,
        )
        or ("wdsync",),
    )


def _parse_command_env(value: str | None, *, posix: bool) -> tuple[str, ...] | None:
    if value is None:
        return None
    argv = tuple(shlex.split(value, posix=posix))
    return argv or None


def _windows_to_wsl_path(windows_path: str) -> Path:
    completed = subprocess.run(
        ["wslpath", windows_path],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip())


def _run_wsl(
    repo_root: Path,
    argv: tuple[str, ...],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        pytest.fail(_format_failure("WSL", argv, completed))
    return completed


def _run_windows(
    repo_root_native: str,
    argv: tuple[str, ...],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    repo_quoted = subprocess.list2cmdline([repo_root_native])
    command_quoted = subprocess.list2cmdline(list(argv))
    shell_command = f"cd /d {repo_quoted} && {command_quoted}"
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", shell_command],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        pytest.fail(_format_failure("Windows", argv, completed))
    return completed


def _format_failure(
    environment_name: str,
    argv: tuple[str, ...],
    completed: subprocess.CompletedProcess[str],
) -> str:
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    return (
        f"{environment_name} command failed: {' '.join(argv)}\n"
        f"exit code: {completed.returncode}\n"
        f"stdout:\n{stdout or '<empty>'}\n"
        f"stderr:\n{stderr or '<empty>'}"
    )


def _best_effort_deinit(config: CrossEnvConfig) -> None:
    _run_windows(config.windows_repo_native, config.windows_command + ("deinit",), check=False)
    _run_wsl(config.wsl_repo, config.wsl_command + ("deinit",), check=False)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_object_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _require_string_list(value: object) -> list[str]:
    assert isinstance(value, list) and value
    items = cast(list[object], value)
    assert all(isinstance(item, str) for item in items)
    return cast(list[str], value)


def test_crossenv_windows_connect_produces_bilateral_status() -> None:
    config = _load_crossenv_config()

    _run_windows(config.windows_repo_native, config.windows_command + ("--version",))
    _run_wsl(config.wsl_repo, config.wsl_command + ("--version",))

    try:
        _best_effort_deinit(config)

        _run_windows(config.windows_repo_native, config.windows_command + ("init",))
        _run_wsl(config.wsl_repo, config.wsl_command + ("init",))
        _run_windows(config.windows_repo_native, config.windows_command + ("connect",))

        windows_status = _run_windows(
            config.windows_repo_native,
            config.windows_command + ("status", "--json"),
        )
        wsl_status = _run_wsl(
            config.wsl_repo,
            config.wsl_command + ("status", "--json"),
        )

        windows_payload = json.loads(windows_status.stdout)
        wsl_payload = json.loads(wsl_status.stdout)

        assert isinstance(windows_payload["schema_version"], int)
        assert windows_payload["schema_version"] == wsl_payload["schema_version"]
        assert windows_payload["direction"] in {"fetch", "send"}
        assert wsl_payload["direction"] in {"fetch", "send"}

        windows_config = _load_json(config.windows_repo_mounted / ".git" / "wdsync" / "config.json")
        wsl_config = _load_json(config.wsl_repo / ".git" / "wdsync" / "config.json")

        windows_peer = _require_object_dict(windows_config["peer"])
        wsl_peer = _require_object_dict(wsl_config["peer"])

        windows_peer_argv = _require_string_list(windows_peer["command_argv"])
        wsl_peer_argv = _require_string_list(wsl_peer["command_argv"])

        assert windows_peer_argv[0] == "wsl.exe"
        assert not _WINDOWS_DRIVE_PATH.match(str(wsl_peer_argv[0]))
        assert str(wsl_peer_argv[0]).endswith("wdsync.exe")
        assert str(wsl_peer["root"]).startswith("/mnt/")
        assert str(windows_peer["root"]).startswith("//wsl.localhost/")

        windows_runtime = _require_object_dict(windows_config["runtime"])
        wsl_runtime = _require_object_dict(wsl_config["runtime"])
        _require_string_list(windows_runtime["wsl_peer_command_argv"])
        _require_string_list(wsl_runtime["windows_peer_command_argv"])
    finally:
        _best_effort_deinit(config)

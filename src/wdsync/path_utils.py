from __future__ import annotations

import os
import re
from pathlib import Path

from wdsync.exceptions import ShellDetectionError, UnsupportedEnvironmentError
from wdsync.models import ShellName
from wdsync.runner import CommandRunner

_SRC_PATTERN = re.compile(r"^/mnt/[A-Za-z]/")


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    release_path = Path("/proc/sys/kernel/osrelease")
    if release_path.exists():
        return "microsoft" in release_path.read_text(encoding="utf-8").lower()
    return False


def ensure_wsl_environment() -> None:
    if not is_wsl():
        raise UnsupportedEnvironmentError("wdsync: this tool must be run from WSL.")


def normalize_source_path(raw_source: str) -> Path:
    return Path(raw_source.strip()).expanduser()


def is_wsl_windows_path(path: Path) -> bool:
    return _SRC_PATTERN.match(path.as_posix()) is not None


def wsl_to_windows_path(path: Path, runner: CommandRunner) -> str:
    result = runner.run(["wslpath", "-w", str(path)])
    return result.stdout_text().strip()


def _shell_from_name(value: str) -> ShellName | None:
    name = Path(value).name.strip().lower()
    if name.endswith("bash"):
        return "bash"
    if name.endswith("fish"):
        return "fish"
    if name.endswith("zsh"):
        return "zsh"
    return None


def _detect_parent_shell() -> ShellName | None:
    parent_comm = Path(f"/proc/{os.getppid()}/comm")
    if not parent_comm.exists():
        return None
    return _shell_from_name(parent_comm.read_text(encoding="utf-8").strip())


def detect_shell(explicit_shell: ShellName | None = None) -> ShellName:
    if explicit_shell is not None:
        return explicit_shell

    env_shell = os.environ.get("SHELL")
    if env_shell:
        detected = _shell_from_name(env_shell)
        if detected is not None:
            return detected

    parent_shell = _detect_parent_shell()
    if parent_shell is not None:
        return parent_shell

    raise ShellDetectionError(
        "wdsync: unable to detect shell automatically. "
        "Use 'wdsync shell install --shell <bash|fish|zsh>'."
    )

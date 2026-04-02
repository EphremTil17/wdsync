from __future__ import annotations

import os
import re
from pathlib import Path

from wdsync.core.exceptions import ShellDetectionError
from wdsync.core.models import ShellName

_SRC_PATTERN = re.compile(r"^/mnt/[A-Za-z]/")


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    release_path = Path("/proc/sys/kernel/osrelease")
    if release_path.exists():
        return "microsoft" in release_path.read_text(encoding="utf-8").lower()
    return False


def is_wsl_windows_path(path: Path) -> bool:
    return _SRC_PATTERN.match(path.as_posix()) is not None


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

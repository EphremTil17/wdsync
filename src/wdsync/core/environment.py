from __future__ import annotations

import sys
from enum import StrEnum

from wdsync.core.path_utils import is_wsl


class Environment(StrEnum):
    WSL = "wsl"
    WINDOWS = "windows"
    LINUX = "linux"


def detect_environment() -> Environment:
    if sys.platform == "win32":
        return Environment.WINDOWS
    if is_wsl():
        return Environment.WSL
    return Environment.LINUX

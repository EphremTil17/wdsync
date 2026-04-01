from __future__ import annotations

from wdsync.core.environment import Environment, detect_environment


def test_detect_environment_returns_valid_enum() -> None:
    result = detect_environment()
    assert result in (Environment.WSL, Environment.WINDOWS, Environment.LINUX)


def test_detect_environment_in_wsl() -> None:
    # This test runs in WSL, so it should return WSL
    result = detect_environment()
    assert result is Environment.WSL

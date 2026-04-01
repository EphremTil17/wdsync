from __future__ import annotations

from pathlib import Path

import pytest

from wdsync.core.exceptions import CommandExecutionError, MissingDependencyError
from wdsync.core.runner import CommandRunner, build_runner


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_build_runner_returns_command_runner() -> None:
    assert isinstance(build_runner(), CommandRunner)


def test_maybe_resolve_program_prefers_overrides_and_handles_missing_paths(tmp_path: Path) -> None:
    script = _write_executable(tmp_path / "tool.sh", "#!/usr/bin/env bash\nexit 0\n")
    runner = CommandRunner({"tool": script})

    assert runner.maybe_resolve_program("tool") == str(script)
    assert runner.maybe_resolve_program(str(script)) == str(script)
    assert runner.maybe_resolve_program(str(tmp_path / "missing.sh")) is None


def test_require_program_raises_for_missing_dependency() -> None:
    with pytest.raises(MissingDependencyError):
        CommandRunner().require_program("wdsync-definitely-missing")


def test_run_rejects_empty_arguments() -> None:
    with pytest.raises(ValueError):
        CommandRunner().run([])


def test_run_returns_failed_result_when_check_is_false(tmp_path: Path) -> None:
    script = _write_executable(
        tmp_path / "fail.sh",
        "#!/usr/bin/env bash\nprintf 'out\\n'\nprintf 'err\\n' >&2\nexit 3\n",
    )
    runner = CommandRunner()

    result = runner.run([str(script)], check=False)

    assert result.returncode == 3
    assert result.stdout_text() == "out\n"
    assert result.stderr_text() == "err\n"


def test_run_raises_command_execution_error_with_details(tmp_path: Path) -> None:
    script = _write_executable(
        tmp_path / "fail.sh",
        "#!/usr/bin/env bash\nprintf 'out\\n'\nprintf 'err\\n' >&2\nexit 7\n",
    )
    runner = CommandRunner()

    with pytest.raises(CommandExecutionError) as exc_info:
        runner.run([str(script)])

    error = exc_info.value
    assert error.returncode == 7
    assert error.command[0] == str(script)
    assert error.stdout == "out\n"
    assert error.stderr == "err\n"

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
import typer

from wdsync.cli import commands as cli
from wdsync.core.models import ShellName
from wdsync.shell import assets as shell


@pytest.mark.parametrize(
    ("shell_name", "expected"),
    [
        ("bash", ".local/share/bash-completion/completions/wdsync"),
        ("fish", ".config/fish/completions/wdsync.fish"),
        ("zsh", ".local/share/zsh/site-functions/_wdsync"),
    ],
)
def test_default_paths_are_shell_specific(
    shell_name: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_home() -> Path:
        return tmp_path

    default_paths = cast(
        Callable[[ShellName], tuple[Path, ...]],
        shell._default_paths,  # pyright: ignore[reportPrivateUsage]
    )
    monkeypatch.setattr(shell.Path, "home", fake_home)
    paths = default_paths(shell_name)  # pyright: ignore[reportArgumentType]

    assert paths[-1] == tmp_path / expected


@pytest.mark.parametrize(("shell_name",), [("bash",), ("fish",), ("zsh",)])
def test_render_completion_supports_all_shells(shell_name: str) -> None:
    render_completion = cast(
        Callable[[ShellName, typer.Typer], str],
        shell._render_completion,  # pyright: ignore[reportPrivateUsage]
    )
    rendered = render_completion(shell_name, cli.app)  # pyright: ignore[reportArgumentType]

    assert rendered
    assert "wdsync" in rendered


def test_install_shell_assets_writes_fish_functions_and_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_default_paths(shell_name: ShellName) -> tuple[Path, ...]:
        del shell_name
        return paths

    def fake_render_completion(shell_name: ShellName, app: typer.Typer) -> str:
        del shell_name, app
        return "complete fish\n"

    paths = (
        tmp_path / "functions/wdsync.fish",
        tmp_path / "functions/wdsync-init.fish",
        tmp_path / "completions/wdsync.fish",
    )
    monkeypatch.setattr("wdsync.shell.assets._default_paths", fake_default_paths)
    monkeypatch.setattr("wdsync.shell.assets._render_completion", fake_render_completion)

    result = shell.install_shell_assets(cli.app, shell_name="fish")

    assert result.shell == "fish"
    assert "Delegate to the Python wdsync CLI" in paths[0].read_text(encoding="utf-8")
    assert "command wdsync $argv" in paths[0].read_text(encoding="utf-8")
    assert "command wdsync init $argv" in paths[1].read_text(encoding="utf-8")
    assert paths[2].read_text(encoding="utf-8") == "complete fish\n"


@pytest.mark.parametrize(("shell_name",), [("bash",), ("zsh",)])
def test_install_shell_assets_writes_init_wrapper_and_completion(
    shell_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_default_paths(detected_shell: ShellName) -> tuple[Path, ...]:
        del detected_shell
        return paths

    def fake_render_completion(detected_shell: ShellName, app: typer.Typer) -> str:
        del app
        return f"{detected_shell} completion\n"

    paths = (
        tmp_path / f"{shell_name}/wdsync-init",
        tmp_path / f"{shell_name}/completion",
    )
    monkeypatch.setattr("wdsync.shell.assets._default_paths", fake_default_paths)
    monkeypatch.setattr("wdsync.shell.assets._render_completion", fake_render_completion)

    result = shell.install_shell_assets(cli.app, shell_name=shell_name)  # pyright: ignore[reportArgumentType]

    assert result.shell == shell_name
    assert paths[0].read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
    assert paths[1].read_text(encoding="utf-8") == f"{shell_name} completion\n"
    assert paths[0].stat().st_mode & 0o111


def test_install_shell_assets_uses_auto_detected_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_detect_shell(explicit_shell: ShellName | None = None) -> ShellName:
        del explicit_shell
        return "bash"

    def fake_default_paths(shell_name: ShellName) -> tuple[Path, ...]:
        del shell_name
        return paths

    def fake_render_completion(shell_name: ShellName, app: typer.Typer) -> str:
        del shell_name, app
        return "completion\n"

    paths = (tmp_path / "wdsync-init", tmp_path / "completion")
    monkeypatch.setattr(shell, "detect_shell", fake_detect_shell)
    monkeypatch.setattr("wdsync.shell.assets._default_paths", fake_default_paths)
    monkeypatch.setattr("wdsync.shell.assets._render_completion", fake_render_completion)

    result = shell.install_shell_assets(cli.app)

    assert result.shell == "bash"
    assert paths[0].exists()

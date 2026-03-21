from __future__ import annotations

from pathlib import Path

import typer
from click.shell_completion import BashComplete, FishComplete, ZshComplete

from wdsync.models import ShellInstallResult, ShellName
from wdsync.path_utils import detect_shell

_COMPLETE_VAR = "_WDSYNC_COMPLETE"


def _default_paths(shell: ShellName) -> tuple[Path, ...]:
    home = Path.home()
    if shell == "fish":
        return (
            home / ".config/fish/functions/wdsync.fish",
            home / ".config/fish/functions/wdsync-init.fish",
            home / ".config/fish/completions/wdsync.fish",
        )
    if shell == "bash":
        return (
            home / ".local/bin/wdsync-init",
            home / ".local/share/bash-completion/completions/wdsync",
        )
    return (
        home / ".local/bin/wdsync-init",
        home / ".local/share/zsh/site-functions/_wdsync",
    )


def _render_completion(shell: ShellName, app: typer.Typer) -> str:
    command = typer.main.get_command(app)
    completion_cls = {
        "bash": BashComplete,
        "fish": FishComplete,
        "zsh": ZshComplete,
    }[shell]
    return completion_cls(command, {}, "wdsync", _COMPLETE_VAR).source()


def _write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _fish_delegate(function_name: str, command: str) -> str:
    return "\n".join(
        [
            f'function {function_name} --description "Delegate to the Python wdsync CLI"',
            f"    command {command}",
            "end",
            "",
        ]
    )


def _init_wrapper_shell_script() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            'exec wdsync init "$@"',
            "",
        ]
    )


def install_shell_assets(
    app: typer.Typer,
    *,
    shell_name: ShellName | None = None,
) -> ShellInstallResult:
    shell = detect_shell(shell_name)
    installed_paths = list(_default_paths(shell))
    notes: list[str] = []

    if shell == "fish":
        wdsync_path, init_path, completion_path = installed_paths
        _write_file(wdsync_path, _fish_delegate("wdsync", "wdsync $argv"))
        _write_file(init_path, _fish_delegate("wdsync-init", "wdsync init $argv"))
        _write_file(completion_path, _render_completion(shell, app))
        notes.append("Fish will auto-load functions and completions from the installed paths.")
    else:
        init_path, completion_path = installed_paths
        _write_file(init_path, _init_wrapper_shell_script(), executable=True)
        _write_file(completion_path, _render_completion(shell, app))
        if shell == "bash":
            notes.append(
                "Make sure your shell loads ~/.local/share/bash-completion/completions "
                "if it is not already configured."
            )
        else:
            notes.append(
                "Add ~/.local/share/zsh/site-functions to your fpath "
                "if zsh does not already load it."
            )

    return ShellInstallResult(
        shell=shell,
        installed_paths=tuple(installed_paths),
        notes=tuple(notes),
    )

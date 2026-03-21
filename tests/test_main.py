from __future__ import annotations

import runpy

import pytest


def test_module_entry_point_invokes_cli_main(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("wdsync.cli.main", lambda: calls.append("called"))

    runpy.run_module("wdsync.__main__", run_name="__main__")

    assert calls == ["called"]

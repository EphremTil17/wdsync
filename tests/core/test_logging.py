from __future__ import annotations

from pathlib import Path

from wdsync.core.logging import attach_file_logging, configure_logging, log


def test_configure_logging_default_does_not_raise() -> None:
    configure_logging()


def test_configure_logging_debug_mode() -> None:
    configure_logging(debug=True)


def test_attach_file_logging_creates_log_file(tmp_path: Path) -> None:
    state_path = tmp_path / "wdsync"
    state_path.mkdir()
    configure_logging()
    attach_file_logging(state_path)

    log.info("test message")

    log_file = state_path / "wdsync.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "test message" in content


def test_log_alias_is_usable() -> None:
    configure_logging()
    log.debug("debug test")
    log.info("info test")

"""Tests for gvt.logging_setup — file handler creation and fallback."""

import importlib
import logging


def _reset_logger(name: str) -> None:
    """Drop handlers on a named logger so get_logger reinstalls them."""
    logger = logging.getLogger(name)
    for h in list(logger.handlers):
        logger.removeHandler(h)


def test_logger_writes_to_file(tmp_path, monkeypatch):
    """Warnings go to ~/.config/gvt/gvt.log when HOME is writable."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GVT_LOG_LEVEL", "DEBUG")

    import gvt.logging_setup
    importlib.reload(gvt.logging_setup)
    _reset_logger("gvt.test_writes")

    log = gvt.logging_setup.get_logger("gvt.test_writes")
    log.warning("hello from test")
    for h in log.handlers:
        h.flush()

    log_file = tmp_path / ".config" / "gvt" / "gvt.log"
    assert log_file.exists()
    assert "hello from test" in log_file.read_text()


def test_logger_respects_level(tmp_path, monkeypatch):
    """DEBUG messages should be written when GVT_LOG_LEVEL=DEBUG."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GVT_LOG_LEVEL", "DEBUG")

    import gvt.logging_setup
    importlib.reload(gvt.logging_setup)
    _reset_logger("gvt.test_level")

    log = gvt.logging_setup.get_logger("gvt.test_level")
    log.debug("debug-line")
    for h in log.handlers:
        h.flush()

    log_file = tmp_path / ".config" / "gvt" / "gvt.log"
    assert log_file.exists()
    assert "debug-line" in log_file.read_text()


def test_logger_default_level_warning(tmp_path, monkeypatch):
    """Without GVT_LOG_LEVEL, default level is WARNING (DEBUG filtered)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("GVT_LOG_LEVEL", raising=False)

    import gvt.logging_setup
    importlib.reload(gvt.logging_setup)
    _reset_logger("gvt.test_default")

    log = gvt.logging_setup.get_logger("gvt.test_default")
    log.debug("debug-should-be-filtered")
    log.warning("warn-should-pass")
    for h in log.handlers:
        h.flush()

    log_file = tmp_path / ".config" / "gvt" / "gvt.log"
    contents = log_file.read_text() if log_file.exists() else ""
    assert "debug-should-be-filtered" not in contents
    assert "warn-should-pass" in contents


def test_logger_falls_back_on_unwritable_dir(monkeypatch):
    """If the log dir cannot be created, get_logger must not raise."""
    monkeypatch.setenv("HOME", "/dev/null/definitely-not-writable")

    import gvt.logging_setup
    importlib.reload(gvt.logging_setup)
    _reset_logger("gvt.test_fallback")

    log = gvt.logging_setup.get_logger("gvt.test_fallback")
    # Logging must be a no-op, not raise.
    log.warning("should not crash")
    assert log.handlers  # fallback NullHandler attached


def test_logger_handlers_not_duplicated(tmp_path, monkeypatch):
    """Calling get_logger twice returns the same logger without adding handlers."""
    monkeypatch.setenv("HOME", str(tmp_path))

    import gvt.logging_setup
    importlib.reload(gvt.logging_setup)
    _reset_logger("gvt.test_dup")

    log1 = gvt.logging_setup.get_logger("gvt.test_dup")
    handler_count = len(log1.handlers)
    log2 = gvt.logging_setup.get_logger("gvt.test_dup")
    assert log1 is log2
    assert len(log2.handlers) == handler_count

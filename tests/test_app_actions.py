"""Tests for user-facing action handlers that surface errors via notify."""

import subprocess


def test_copy_to_clipboard_reports_failure(fixture_app, monkeypatch):
    """Clipboard-tool failure is reported to the user via notify."""
    monkeypatch.setattr("gvt.app.shutil.which", lambda x: "/usr/bin/pbcopy")

    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr("gvt.app.subprocess.run", boom)

    called = []
    fixture_app.notify = lambda msg, **k: called.append(msg)
    fixture_app._copy_to_clipboard("abc123")

    assert called
    assert any("Failed" in m for m in called)


def test_copy_to_clipboard_reports_nonzero_exit(fixture_app, monkeypatch):
    """A CalledProcessError from the clipboard tool is caught and reported."""
    monkeypatch.setattr("gvt.app.shutil.which", lambda x: "/usr/bin/pbcopy")

    def failing(*a, **k):
        raise subprocess.CalledProcessError(1, a[0])

    monkeypatch.setattr("gvt.app.subprocess.run", failing)

    called = []
    fixture_app.notify = lambda msg, **k: called.append(msg)
    fixture_app._copy_to_clipboard("abc123")

    assert any("Failed" in m for m in called)


def test_copy_to_clipboard_no_tool(fixture_app, monkeypatch):
    """When no clipboard tool is installed, user sees a clear message."""
    monkeypatch.setattr("gvt.app.shutil.which", lambda x: None)

    called = []
    fixture_app.notify = lambda msg, **k: called.append(msg)
    fixture_app._copy_to_clipboard("abc123")

    assert any("No clipboard" in m for m in called)


def test_copy_to_clipboard_success(fixture_app, monkeypatch):
    """Happy path: successful copy notifies 'Copied ...'."""
    monkeypatch.setattr("gvt.app.shutil.which", lambda x: "/usr/bin/pbcopy")

    runs = []

    def fake_run(cmd, input=None, check=False, **k):
        runs.append((cmd, input))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("gvt.app.subprocess.run", fake_run)

    called = []
    fixture_app.notify = lambda msg, **k: called.append(msg)
    fixture_app._copy_to_clipboard("abc123")

    assert runs, "subprocess.run should have been invoked"
    assert any("Copied abc123" in m for m in called)


def test_open_in_editor_launch_failure(fixture_app, monkeypatch):
    """If the editor binary cannot launch, user is notified."""
    fixture_app.current_file = "hello.py"
    monkeypatch.setenv("EDITOR", "nonexistent-editor-xyz")
    import contextlib
    monkeypatch.setattr(
        fixture_app, "suspend", lambda: contextlib.nullcontext()
    )

    def boom(*a, **k):
        raise FileNotFoundError("no such editor")

    monkeypatch.setattr("gvt.app.subprocess.run", boom)

    called = []
    fixture_app.notify = lambda msg, **k: called.append(msg)
    fixture_app.action_open_in_editor()

    assert any("Could not launch" in m for m in called)


def test_open_in_editor_nonzero_exit(fixture_app, monkeypatch):
    """If the editor exits nonzero, user is notified."""
    fixture_app.current_file = "hello.py"
    monkeypatch.setenv("EDITOR", "fake-editor")
    import contextlib
    monkeypatch.setattr(
        fixture_app, "suspend", lambda: contextlib.nullcontext()
    )

    def fake_run(cmd, **k):
        return subprocess.CompletedProcess(cmd, 2)

    monkeypatch.setattr("gvt.app.subprocess.run", fake_run)

    called = []
    fixture_app.notify = lambda msg, **k: called.append(msg)
    fixture_app.action_open_in_editor()

    assert any("exited with code 2" in m for m in called)


def test_open_in_editor_no_current_file(fixture_app, monkeypatch):
    """Without a current_file, action is a no-op (does not notify or launch)."""
    fixture_app.current_file = None
    runs = []
    monkeypatch.setattr(
        "gvt.app.subprocess.run", lambda *a, **k: runs.append(a)
    )

    called = []
    fixture_app.notify = lambda msg, **k: called.append(msg)
    fixture_app.action_open_in_editor()

    assert not runs
    assert not called

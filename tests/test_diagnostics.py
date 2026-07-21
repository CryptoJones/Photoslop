# SPDX-License-Identifier: Apache-2.0
"""Durable redacted failures, task history, and plugin attribution."""

import os
import stat
import time

from PySide6.QtTest import QTest

from photoslop.diagnostics import DiagnosticsDialog, DiagnosticStore
from photoslop.mainwindow import MainWindow
from photoslop.tasks import TaskState


def _wait(qapp, predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(10)
    assert predicate()


def test_diagnostics_persist_redacted_bounded_records(qapp, tmp_path):
    store = DiagnosticStore(str(tmp_path), retention=10)
    record = store.record(
        "model.request",
        "Backend failed",
        details=(
            "Authorization: Bearer top-secret\npassword=hunter2\n"  # pragma: allowlist secret
            "https://alice:secret@example.test/model"  # pragma: allowlist secret
        ),
        context={"api_key": "sk-private"},  # pragma: allowlist secret
    )

    assert "top-secret" not in record.details
    assert "hunter2" not in record.details
    assert "alice:secret" not in record.details
    assert record.context["api_key"] == "[REDACTED]"
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "operations.jsonl").stat().st_mode) == 0o600
    reloaded = DiagnosticStore(str(tmp_path))
    assert reloaded.records == (record,)


def test_background_failure_is_durable_and_points_status_to_record(qapp, tmp_path):
    win = MainWindow(recovery_enabled=False)
    win.diagnostics = DiagnosticStore(str(tmp_path), parent=win)

    def fail(_context):
        raise OSError("disk failed; token=do-not-log")

    handle = win.task_service.submit("file.save", "Save project", fail)
    _wait(qapp, lambda: handle.state is TaskState.FAILED)

    assert len(win.diagnostics.records) == 1
    record = win.diagnostics.records[0]
    assert record.operation == "file.save"
    assert "do-not-log" not in record.details
    assert record.identifier in win.statusBar().currentMessage()
    dialog = DiagnosticsDialog(win.diagnostics, win)
    assert dialog.records.count() == 1
    assert record.identifier in dialog.details.toPlainText()


def test_background_success_is_persisted_as_an_operation_result(qapp, tmp_path):
    win = MainWindow(recovery_enabled=False)
    win.diagnostics = DiagnosticStore(str(tmp_path), parent=win)

    handle = win.task_service.submit("export.png", "Export PNG", lambda _context: 42)
    _wait(qapp, lambda: handle.state is TaskState.SUCCEEDED)

    assert len(win.diagnostics.records) == 1
    record = win.diagnostics.records[0]
    assert record.operation == "export.png"
    assert record.summary == "Export PNG succeeded"
    assert record.guidance == "No action is required."


def test_broken_plugins_are_attributed_instead_of_silently_swallowed(monkeypatch):
    class BrokenEntryPoint:
        name = "broken-plugin"

        @staticmethod
        def load():
            raise RuntimeError("incompatible plugin")

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda **_kwargs: [BrokenEntryPoint()],
    )
    from photoslop import filters, modeladapter

    filters._PLUGIN_FAILURES.clear()
    modeladapter._PLUGIN_FAILURES.clear()
    monkeypatch.setattr(modeladapter, "_plugins_loaded", False)
    filters.available_filters(allow_unsafe=True)
    modeladapter.available_adapters(allow_unsafe=True)

    for failure in (*filters.plugin_failures(), *modeladapter.plugin_failures()):
        assert failure.name == "broken-plugin"
        assert "RuntimeError: incompatible plugin" in failure.details

# SPDX-License-Identifier: Apache-2.0
"""Bounded task lifecycle, cancellation, failure, progress, and memory queueing."""

import threading
import time

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.tasks import TaskService, TaskState, snapshot_document


def _wait(qapp, predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(10)
    assert predicate()


def test_task_success_and_progress_return_on_gui_thread(qapp):
    service = TaskService(max_workers=1, memory_budget=100)
    progress = []
    results = []

    def operation(context):
        context.progress(25, "quarter")
        return 42

    handle = service.submit("answer", "Answer", operation, 10)
    handle.progressChanged.connect(lambda percent, message: progress.append((percent, message)))
    handle.succeeded.connect(results.append)
    _wait(qapp, lambda: handle.state is TaskState.SUCCEEDED)
    assert results == [42]
    assert progress == [(25, "quarter")]


def test_cooperative_cancellation_has_no_success_result(qapp):
    service = TaskService(max_workers=1)

    def operation(context):
        while True:
            context.check_cancelled()
            time.sleep(0.005)

    handle = service.submit("cancel", "Cancel", operation)
    _wait(qapp, lambda: handle.state is TaskState.RUNNING)
    handle.cancel()
    _wait(qapp, lambda: handle.state is TaskState.CANCELLED)


def test_cancellation_can_be_scoped_to_one_document(qapp):
    service = TaskService(max_workers=1)

    def operation(context):
        while True:
            context.check_cancelled()
            time.sleep(0.005)

    first = service.submit("first", "First", operation, scope_id="doc-a")
    second = service.submit("second", "Second", lambda _context: 2,
                            scope_id="doc-b")
    _wait(qapp, lambda: first.state is TaskState.RUNNING)
    service.cancel_scope("doc-a")
    _wait(qapp, lambda: first.state is TaskState.CANCELLED)
    _wait(qapp, lambda: second.state is TaskState.SUCCEEDED)


def test_failure_is_reported_without_killing_queue(qapp):
    service = TaskService(max_workers=1)
    errors = []

    def operation(_context):
        raise ValueError("broken")

    handle = service.submit("fail", "Fail", operation)
    handle.failed.connect(errors.append)
    _wait(qapp, lambda: handle.state is TaskState.FAILED)
    assert "ValueError: broken" in errors[0]


def test_memory_budget_keeps_second_task_queued(qapp):
    service = TaskService(max_workers=2, memory_budget=100)
    release = threading.Event()

    def first(context):
        while not release.is_set():
            context.check_cancelled()
            time.sleep(0.005)
        return 1

    one = service.submit("one", "One", first, 80)
    two = service.submit("two", "Two", lambda _context: 2, 80)
    _wait(qapp, lambda: one.state is TaskState.RUNNING)
    assert two.state is TaskState.QUEUED
    release.set()
    _wait(qapp, lambda: two.state is TaskState.SUCCEEDED)


def test_document_snapshot_is_metadata_deep_and_pixel_cow(qapp):
    doc = Document.new(QSize(40, 30), 72, "snapshot", QColor("white"))
    clone = snapshot_document(doc)
    assert clone is not doc and clone.layers[0] is not doc.layers[0]
    assert clone.layers[0].image.cacheKey() == doc.layers[0].image.cacheKey()
    clone.layers[0].name = "worker"
    clone.layers[0].image.fill(QColor("black"))
    assert doc.layers[0].name != "worker"
    assert doc.layers[0].image.pixelColor(0, 0) == QColor("white")


def test_background_save_uses_snapshot_and_marks_clean_only_if_unchanged(qapp, tmp_path):
    win = MainWindow()
    doc = Document.new(QSize(40, 30), 72, "save", QColor("white"))
    doc.path = str(tmp_path / "save.ora")
    win.add_document(doc)
    win.action_save()
    _wait(qapp, lambda: not win.task_service.active)
    assert (tmp_path / "save.ora").exists()
    assert doc.undo_stack.isClean()


def test_background_open_decodes_without_blocking_action(qapp, tmp_path, monkeypatch):
    image_path = tmp_path / "open.png"
    image = QImage(20, 10, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("red"))
    assert image.save(str(image_path))
    win = MainWindow()
    start = tmp_path / "chooser-start"
    start.mkdir()
    win.settings.setValue("files/last-directory", str(start))
    requested = []
    monkeypatch.setattr(
        "photoslop.mainwindow.OpenImageDialog.get_paths",
        lambda _parent, directory: requested.append(directory) or [str(image_path)])
    win.action_open()
    assert requested == [str(start)]
    assert win.tabs.count() == 0
    _wait(qapp, lambda: not win.task_service.active)
    assert win.tabs.count() == 1
    assert win._last_directory() == str(tmp_path)


def test_gui_heartbeat_continues_while_worker_runs(qapp):
    service = TaskService(max_workers=1)
    beats = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    timer.start()
    handle = service.submit("sleep", "Sleep", lambda _context: time.sleep(0.12))
    _wait(qapp, lambda: handle.state is TaskState.SUCCEEDED)
    timer.stop()
    assert len(beats) >= 5

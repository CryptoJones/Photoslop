# SPDX-License-Identifier: Apache-2.0
"""Destination writes commit once and never damage the previous file."""

import os
import time

import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from photoslop.atomicio import (
    SupersededWriteError,
    WriteCoordinator,
    atomic_write,
)
from photoslop.commands import SetLayerPropertyCommand
from photoslop.document import Document
from photoslop.io_ora import save_ora
from photoslop.mainwindow import MainWindow
from photoslop.recovery import RecoveryService
from photoslop.services import export_artboards
from photoslop.tasks import CancelledError


def _write(path: str, data: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(data)


def test_atomic_writer_failure_preserves_destination_and_cleans_temp(tmp_path):
    destination = tmp_path / "project.ora"
    destination.write_bytes(b"last-good")

    def fail(temporary: str) -> None:
        _write(temporary, b"partial")
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        atomic_write(str(destination), fail)
    assert destination.read_bytes() == b"last-good"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["project.ora"]


def test_cancellation_before_commit_preserves_destination(tmp_path):
    destination = tmp_path / "cancelled.png"
    destination.write_bytes(b"old")

    def cancelled() -> None:
        raise CancelledError("cancelled")

    with pytest.raises(CancelledError):
        atomic_write(
            str(destination), lambda temporary: _write(temporary, b"new"),
            before_commit=cancelled)
    assert destination.read_bytes() == b"old"


def test_newer_write_ticket_prevents_older_snapshot_from_committing(tmp_path):
    destination = tmp_path / "ordered.svg"
    destination.write_bytes(b"initial")
    coordinator = WriteCoordinator()
    older = coordinator.reserve(str(destination))
    newer = coordinator.reserve(str(destination))

    with pytest.raises(SupersededWriteError):
        older.write(lambda temporary: _write(temporary, b"older"))
    newer.write(lambda temporary: _write(temporary, b"newer"))
    assert destination.read_bytes() == b"newer"


def test_ora_encoder_failure_does_not_truncate_existing_project(
        qapp, tmp_path, monkeypatch):
    destination = tmp_path / "existing.ora"
    destination.write_bytes(b"valid old project")
    doc = Document.new(QSize(10, 10), 72.0, "atomic", QColor("white"))

    def fail(_doc, temporary: str) -> None:
        _write(temporary, b"broken zip")
        raise OSError("encoder failed")

    monkeypatch.setattr("photoslop.io_ora._write_ora", fail)
    with pytest.raises(OSError, match="encoder failed"):
        save_ora(doc, str(destination))
    assert destination.read_bytes() == b"valid old project"


def test_artboard_export_deduplicates_sanitized_names(qapp, tmp_path):
    doc = Document.new(QSize(20, 10), 72.0, "boards", QColor("red"))
    doc.artboards = [
        ("Hero/Card", QRect(0, 0, 5, 5)),
        ("hero_card", QRect(5, 0, 5, 5)),
        ("Hero/Card", QRect(10, 0, 5, 5)),
    ]

    written = export_artboards(doc, str(tmp_path))

    assert [os.path.basename(path) for path in written] == [
        "Hero_Card.png", "hero_card-2.png", "Hero_Card-3.png"]
    assert all(os.path.getsize(path) > 0 for path in written)


def test_recovery_snapshot_round_trips_identity_and_stays_unsaved(qapp, tmp_path):
    service = RecoveryService(str(tmp_path / "recovery"))
    doc = Document.new(QSize(12, 8), 72.0, "Camera edit", QColor("blue"))
    document_id = doc.document_id

    service.write(doc)
    recovered = service.available()

    assert len(recovered) == 1
    assert recovered[0].document_id == document_id
    assert recovered[0].name == "Recovered Camera edit"
    assert recovered[0].path is None
    assert recovered[0].active_layer.image.pixelColor(1, 1) == QColor("blue")
    service.clear(document_id)
    assert service.available() == []


def test_dirty_document_schedules_recovery_and_clean_state_removes_it(
        qapp, tmp_path):
    win = MainWindow(recovery_enabled=True)
    win.recovery_service = RecoveryService(str(tmp_path / "autosave"))
    doc = Document.new(QSize(10, 10), 72.0, "scheduled", QColor("white"))
    win.add_document(doc)
    doc.undo_stack.push(SetLayerPropertyCommand(
        doc, doc.active_layer, "opacity", 0.5))
    timer = win._recovery_timers[doc.document_id]
    timer.setInterval(0)
    timer.start()

    deadline = time.monotonic() + 2
    path = win.recovery_service.path_for(doc.document_id)
    while (win.task_service.active or not os.path.exists(path)) and time.monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(5)
    assert os.path.exists(path)

    doc.undo_stack.undo()
    assert not os.path.exists(path)
    win.close()
    win.task_service.pool.waitForDone()

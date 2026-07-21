# SPDX-License-Identifier: Apache-2.0
"""Destination writes commit once and never damage the previous file."""

import json
import os
import time
from pathlib import Path

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
            str(destination), lambda temporary: _write(temporary, b"new"), before_commit=cancelled
        )
    assert destination.read_bytes() == b"old"


def test_durable_write_reopens_completed_file_writable(tmp_path, monkeypatch):
    destination = tmp_path / "durable.bin"
    opened_modes = []
    real_open = open

    def tracked_open(path, mode="r", *args, **kwargs):
        opened_modes.append((os.fspath(path), mode))
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", tracked_open)
    atomic_write(
        str(destination),
        lambda temporary: _write(temporary, b"durable"),
        durable=True,
    )

    assert destination.read_bytes() == b"durable"
    assert any(mode == "r+b" for _path, mode in opened_modes)


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


def test_ora_encoder_failure_does_not_truncate_existing_project(qapp, tmp_path, monkeypatch):
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
        "Hero_Card.png",
        "hero_card-2.png",
        "Hero_Card-3.png",
    ]
    assert all(os.path.getsize(path) > 0 for path in written)


def test_recovery_snapshot_round_trips_identity_and_stays_unsaved(qapp, tmp_path):
    service = RecoveryService(str(tmp_path / "recovery"))
    doc = Document.new(QSize(12, 8), 72.0, "Camera edit", QColor("blue"))
    document_id = doc.document_id

    service.write(doc)
    metadata = json.loads((tmp_path / "recovery" / f"{document_id}.recovery.json").read_text())
    assert metadata["schema_version"] == RecoveryService.SCHEMA_VERSION
    assert metadata["document_id"] == document_id
    recovered = service.available()

    assert len(recovered) == 1
    assert recovered[0].document_id == document_id
    assert recovered[0].name == "Recovered Camera edit"
    assert recovered[0].path is None
    assert recovered[0].active_layer.image.pixelColor(1, 1) == QColor("blue")
    service.clear(document_id)
    assert service.available() == []


def test_recovery_retention_prunes_old_and_excess_documents(qapp, tmp_path):
    service = RecoveryService(str(tmp_path / "bounded"), max_documents=2, max_age_days=30)
    documents = [
        Document.new(QSize(6, 6), 72, f"doc-{index}", QColor("white")) for index in range(3)
    ]
    for document in documents:
        service.write(document)
        time.sleep(0.002)
    assert len(service.available()) == 2
    assert not os.path.exists(service.path_for(documents[0].document_id))

    stale = documents[-1]
    metadata_path = Path(service.metadata_path_for(stale.document_id))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["saved_at"] = "2000-01-01T00:00:00+00:00"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    service.prune()
    assert not os.path.exists(service.path_for(stale.document_id))


def test_failed_recovery_write_preserves_last_complete_snapshot(qapp, tmp_path, monkeypatch):
    service = RecoveryService(str(tmp_path / "disk-full"))
    doc = Document.new(QSize(8, 8), 72, "stable", QColor("blue"))
    service.write(doc)
    snapshot_path = Path(service.path_for(doc.document_id))
    before = snapshot_path.read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("photoslop.recovery.save_ora", fail)
    with pytest.raises(OSError, match="disk full"):
        service.write(doc)
    assert snapshot_path.read_bytes() == before
    assert service.available()[0].active_layer.image.pixelColor(0, 0) == QColor("blue")


def test_recovery_clear_all_is_scoped_and_handles_missing_root(tmp_path):
    root = tmp_path / "clear-all"
    service = RecoveryService(str(root))
    service.clear_all()
    root.mkdir()
    (root / "one.ora").write_bytes(b"snapshot")
    (root / "one.recovery.json").write_text("{}", encoding="utf-8")
    (root / "keep.txt").write_text("keep", encoding="utf-8")

    service.clear_all()

    assert [path.name for path in root.iterdir()] == ["keep.txt"]


def test_recovery_ignores_invalid_metadata_and_corrupt_snapshots(qapp, tmp_path):
    root = tmp_path / "corrupt"
    root.mkdir()
    service = RecoveryService(str(root))
    (root / "broken.ora").write_bytes(b"not an archive")
    (root / "broken.recovery.json").write_text("{not-json", encoding="utf-8")
    assert service._metadata("broken") == {}
    assert service.available() == []

    (root / "broken.recovery.json").write_text(
        json.dumps({"schema_version": 999}), encoding="utf-8"
    )
    assert service._metadata("broken") == {}


def test_recovery_legacy_snapshot_uses_file_time_and_missing_root_is_empty(qapp, tmp_path):
    root = tmp_path / "legacy"
    service = RecoveryService(str(root))
    assert service.available() == []
    service.prune()

    doc = Document.new(QSize(5, 5), 72, "legacy", QColor("green"))
    service.write(doc)
    os.unlink(service.metadata_path_for(doc.document_id))
    service.prune()

    recovered = service.available()
    assert len(recovered) == 1
    assert recovered[0].recovery_original_path is None
    assert recovered[0].recovery_saved_at is None


def test_dirty_document_schedules_recovery_and_clean_state_removes_it(qapp, tmp_path):
    win = MainWindow(recovery_enabled=True)
    win.recovery_service = RecoveryService(str(tmp_path / "autosave"))
    doc = Document.new(QSize(10, 10), 72.0, "scheduled", QColor("white"))
    win.add_document(doc)
    doc.undo_stack.push(SetLayerPropertyCommand(doc, doc.active_layer, "opacity", 0.5))
    timer = win._recovery_timers[doc.document_id]
    timer.setInterval(0)
    timer.start()

    deadline = time.monotonic() + 10
    path = win.recovery_service.path_for(doc.document_id)
    while (win.task_service.active or not os.path.exists(path)) and time.monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(5)
    assert os.path.exists(path)

    doc.undo_stack.undo()
    assert not os.path.exists(path)
    win.close()
    win.task_service.pool.waitForDone()

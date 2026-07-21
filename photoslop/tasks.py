# SPDX-License-Identifier: Apache-2.0
"""Memory-bounded background work with progress, cancellation, and results."""

from __future__ import annotations

import threading
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CancelledError(RuntimeError):
    pass


class TaskContext:
    def __init__(self, cancelled: threading.Event, progress: Callable[[int, str], None]):
        self._cancelled = cancelled
        self._progress = progress

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise CancelledError("Task cancelled")

    def progress(self, percent: int, message: str = "") -> None:
        self.check_cancelled()
        self._progress(max(0, min(100, int(percent))), message)


class TaskHandle(QObject):
    progressChanged = Signal(int, str)
    stateChanged = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, task_id: str, label: str, estimated_bytes: int,
                 scope_id: str | None = None) -> None:
        super().__init__()
        self.task_id = task_id
        self.label = label
        self.estimated_bytes = max(1, estimated_bytes)
        self.scope_id = scope_id
        self.state = TaskState.QUEUED
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def _set_state(self, state: TaskState) -> None:
        self.state = state
        self.stateChanged.emit(state)


@dataclass
class _Pending:
    handle: TaskHandle
    operation: Callable[[TaskContext], Any]


class _WorkerSignals(QObject):
    progress = Signal(int, str)
    done = Signal(object, object, str)


class _Worker(QRunnable):
    def __init__(self, pending: _Pending) -> None:
        super().__init__()
        self.pending = pending
        self.signals = _WorkerSignals()

    def run(self) -> None:
        handle = self.pending.handle
        context = TaskContext(handle._cancel, self.signals.progress.emit)
        try:
            context.check_cancelled()
            result = self.pending.operation(context)
            context.check_cancelled()
            self.signals.done.emit(TaskState.SUCCEEDED, result, "")
        except CancelledError:
            self.signals.done.emit(TaskState.CANCELLED, None, "")
        except Exception:
            self.signals.done.emit(TaskState.FAILED, None, traceback.format_exc())


class TaskService(QObject):
    """Queue work by both worker count and declared peak memory."""

    taskAdded = Signal(object)
    taskFinished = Signal(object)

    def __init__(self, max_workers: int = 2, memory_budget: int = 512 * 1024 * 1024,
                 parent=None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(1, max_workers))
        self.memory_budget = max(1, memory_budget)
        self._queued: deque[_Pending] = deque()
        self._running: dict[TaskHandle, tuple[_Pending, _Worker]] = {}
        self._running_bytes = 0

    @property
    def active(self) -> tuple[TaskHandle, ...]:
        return tuple(self._running) + tuple(item.handle for item in self._queued)

    def submit(self, task_id: str, label: str, operation: Callable[[TaskContext], Any],
               estimated_bytes: int = 1, scope_id: str | None = None) -> TaskHandle:
        handle = TaskHandle(task_id, label, estimated_bytes, scope_id)
        self._queued.append(_Pending(handle, operation))
        self.taskAdded.emit(handle)
        self._drain()
        return handle

    def cancel_all(self) -> None:
        for handle in self.active:
            handle.cancel()
        self._drain_cancelled()

    def cancel_scope(self, scope_id: str) -> None:
        for handle in self.active:
            if handle.scope_id == scope_id:
                handle.cancel()
        self._drain_cancelled()

    def _drain_cancelled(self) -> None:
        keep = deque()
        while self._queued:
            pending = self._queued.popleft()
            if pending.handle._cancel.is_set():
                pending.handle._set_state(TaskState.CANCELLED)
                pending.handle.cancelled.emit()
                self.taskFinished.emit(pending.handle)
            else:
                keep.append(pending)
        self._queued = keep

    def _drain(self) -> None:
        self._drain_cancelled()
        while self._queued and len(self._running) < self.pool.maxThreadCount():
            pending = self._queued[0]
            needed = min(pending.handle.estimated_bytes, self.memory_budget)
            if self._running and self._running_bytes + needed > self.memory_budget:
                break
            self._queued.popleft()
            worker = _Worker(pending)
            worker.signals.progress.connect(pending.handle.progressChanged)
            worker.signals.done.connect(
                lambda state, result, error, h=pending.handle: self._complete(
                    h, state, result, error))
            self._running[pending.handle] = (pending, worker)
            self._running_bytes += needed
            pending.handle._set_state(TaskState.RUNNING)
            self.pool.start(worker)

    def _complete(self, handle: TaskHandle, state: TaskState, result, error: str) -> None:
        pending, _worker = self._running.pop(handle)
        self._running_bytes -= min(handle.estimated_bytes, self.memory_budget)
        handle._set_state(state)
        if state is TaskState.SUCCEEDED:
            handle.succeeded.emit(result)
        elif state is TaskState.CANCELLED:
            handle.cancelled.emit()
        else:
            handle.failed.emit(error)
        self.taskFinished.emit(handle)
        self._drain()


def snapshot_document(doc):
    """Create a metadata-deep, pixel-COW document safe for worker reads."""
    from copy import deepcopy

    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QColorSpace, QPainterPath

    from photoslop.document import Document

    snapshot = Document(doc.size, doc.dpi, doc.name)
    snapshot.document_id = doc.document_id
    snapshot.layers = [layer.clone(preserve_id=True) for layer in doc.layers]
    snapshot.active_index = doc.active_index
    snapshot.selection = QPainterPath(doc.selection) if doc.selection is not None else None
    snapshot.selection_feather = doc.selection_feather
    snapshot.group_props = deepcopy(doc.group_props)
    snapshot.icc_space = QColorSpace(doc.icc_space) if doc.icc_space is not None else None
    snapshot.guides_h = list(doc.guides_h)
    snapshot.guides_v = list(doc.guides_v)
    snapshot.artboards = [(name, QRect(rect)) for name, rect in doc.artboards]
    snapshot.vector_selection = list(doc.vector_selection)
    snapshot.vector_node_selection = deepcopy(doc.vector_node_selection)
    snapshot.path = doc.path
    # Force detached list/point wrappers; pixel buffers remain shared until a write.
    for source, target in zip(doc.layers, snapshot.layers, strict=True):
        target.offset = QPoint(source.offset)
    return snapshot

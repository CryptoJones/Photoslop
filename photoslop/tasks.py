# SPDX-License-Identifier: Apache-2.0
"""Memory-bounded background work with progress, cancellation, and results."""

from __future__ import annotations

import threading
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_UTC = timezone.utc


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(IntEnum):
    """Lower values are scheduled first; FIFO is preserved within a class."""

    INTERACTIVE = 0
    WRITE = 10
    REMOTE = 20
    BULK = 30


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

    def __init__(
        self,
        task_id: str,
        label: str,
        estimated_bytes: int,
        scope_id: str | None = None,
        priority: TaskPriority = TaskPriority.BULK,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.label = label
        self.estimated_bytes = max(1, estimated_bytes)
        self.scope_id = scope_id
        self.priority = TaskPriority(priority)
        self.state = TaskState.QUEUED
        self.progress_percent = 0
        self.progress_message = ""
        self.created_at = datetime.now(_UTC)
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.error = ""
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def _set_state(self, state: TaskState) -> None:
        self.state = state
        now = datetime.now(_UTC)
        if state is TaskState.RUNNING:
            self.started_at = now
        elif state in {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED}:
            self.finished_at = now
        self.stateChanged.emit(state)

    def _set_progress(self, percent: int, message: str) -> None:
        self.progress_percent = percent
        self.progress_message = message
        self.progressChanged.emit(percent, message)


@dataclass
class _Pending:
    handle: TaskHandle
    operation: Callable[[TaskContext], Any]
    sequence: int


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    label: str
    scope_id: str | None
    priority: TaskPriority
    state: TaskState
    progress_percent: int
    progress_message: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str


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
    queueChanged = Signal()

    def __init__(
        self, max_workers: int = 2, memory_budget: int = 512 * 1024 * 1024, parent=None
    ) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(1, max_workers))
        self.memory_budget = max(1, memory_budget)
        self._queued: list[_Pending] = []
        self._running: dict[TaskHandle, tuple[_Pending, _Worker]] = {}
        self._running_bytes = 0
        self._sequence = 0
        self._history: deque[TaskRecord] = deque(maxlen=100)

    @property
    def active(self) -> tuple[TaskHandle, ...]:
        queued = sorted(self._queued, key=self._sort_key)
        return tuple(self._running) + tuple(item.handle for item in queued)

    @property
    def history(self) -> tuple[TaskRecord, ...]:
        return tuple(self._history)

    def submit(
        self,
        task_id: str,
        label: str,
        operation: Callable[[TaskContext], Any],
        estimated_bytes: int = 1,
        scope_id: str | None = None,
        priority: TaskPriority = TaskPriority.BULK,
    ) -> TaskHandle:
        handle = TaskHandle(task_id, label, estimated_bytes, scope_id, priority)
        self._sequence += 1
        self._queued.append(_Pending(handle, operation, self._sequence))
        self.taskAdded.emit(handle)
        self.queueChanged.emit()
        self._drain()
        return handle

    def cancel_all(self) -> None:
        for handle in self.active:
            handle.cancel()
        self._drain_cancelled()

    def cancel_task(self, handle: TaskHandle) -> None:
        """Cancel one queued or running handle without affecting its scope."""
        if handle not in self.active:
            return
        handle.cancel()
        self._drain_cancelled()

    def cancel_scope(self, scope_id: str) -> None:
        for handle in self.active:
            if handle.scope_id == scope_id:
                handle.cancel()
        self._drain_cancelled()

    def _drain_cancelled(self) -> None:
        keep = []
        for pending in self._queued:
            if pending.handle._cancel.is_set():
                pending.handle._set_state(TaskState.CANCELLED)
                pending.handle.cancelled.emit()
                self._record(pending.handle)
                self.taskFinished.emit(pending.handle)
            else:
                keep.append(pending)
        self._queued = keep
        self.queueChanged.emit()

    def _drain(self) -> None:
        self._drain_cancelled()
        while self._queued and len(self._running) < self.pool.maxThreadCount():
            candidate = self._next_runnable()
            if candidate is None:
                break
            index, pending = candidate
            self._queued.pop(index)
            needed = min(pending.handle.estimated_bytes, self.memory_budget)
            worker = _Worker(pending)
            worker.signals.progress.connect(pending.handle._set_progress)
            worker.signals.done.connect(
                lambda state, result, error, h=pending.handle: self._complete(
                    h, state, result, error
                )
            )
            self._running[pending.handle] = (pending, worker)
            self._running_bytes += needed
            pending.handle._set_state(TaskState.RUNNING)
            self.pool.start(worker)
            self.queueChanged.emit()

    @staticmethod
    def _sort_key(pending: _Pending) -> tuple[int, int]:
        return int(pending.handle.priority), pending.sequence

    def _next_runnable(self) -> tuple[int, _Pending] | None:
        for pending in sorted(self._queued, key=self._sort_key):
            needed = min(pending.handle.estimated_bytes, self.memory_budget)
            if not self._running or self._running_bytes + needed <= self.memory_budget:
                return self._queued.index(pending), pending
        return None

    def _record(self, handle: TaskHandle) -> None:
        self._history.append(
            TaskRecord(
                handle.task_id,
                handle.label,
                handle.scope_id,
                handle.priority,
                handle.state,
                handle.progress_percent,
                handle.progress_message,
                handle.created_at,
                handle.started_at,
                handle.finished_at,
                handle.error,
            )
        )

    def _complete(self, handle: TaskHandle, state: TaskState, result, error: str) -> None:
        pending, _worker = self._running.pop(handle)
        self._running_bytes -= min(handle.estimated_bytes, self.memory_budget)
        handle.error = error
        handle._set_state(state)
        if state is TaskState.SUCCEEDED:
            handle.succeeded.emit(result)
        elif state is TaskState.CANCELLED:
            handle.cancelled.emit()
        else:
            handle.failed.emit(error)
        self._record(handle)
        self.taskFinished.emit(handle)
        self.queueChanged.emit()
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

# SPDX-License-Identifier: Apache-2.0
"""Accessible task queue/history viewer and scoped cancellation controls."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from photoslop.tasks import TaskHandle, TaskRecord, TaskService


class TaskMonitorDialog(QDialog):
    def __init__(self, service: TaskService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self._items: list[TaskHandle | TaskRecord] = []
        self.setWindowTitle("Background Tasks")
        self.resize(720, 480)

        summary = QLabel(
            "Queued and running work appears first; completed work is retained "
            "for this application session."
        )
        summary.setWordWrap(True)
        self.tasks = QListWidget()
        self.tasks.setAccessibleName("Background task queue and history")
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Selected task details")
        self.cancel_selected = QPushButton("Cancel Selected")
        self.cancel_scope = QPushButton("Cancel Scope")
        self.cancel_all = QPushButton("Cancel All Active")
        self.cancel_selected.setAccessibleDescription(
            "Cancel only the selected queued or running task"
        )
        self.cancel_scope.setAccessibleDescription(
            "Cancel queued and running tasks for the selected document or operation scope"
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        controls = QHBoxLayout()
        controls.addWidget(self.cancel_selected)
        controls.addWidget(self.cancel_scope)
        controls.addWidget(self.cancel_all)
        controls.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.tasks, 1)
        layout.addWidget(self.details, 1)
        layout.addLayout(controls)
        layout.addWidget(buttons)

        self.tasks.currentRowChanged.connect(self._show_selected)
        self.cancel_selected.clicked.connect(self._cancel_selected)
        self.cancel_scope.clicked.connect(self._cancel_selected_scope)
        self.cancel_all.clicked.connect(self.service.cancel_all)
        self.service.taskAdded.connect(self._track_handle)
        self.service.queueChanged.connect(self._refresh)
        self._refresh()

    def _track_handle(self, handle: TaskHandle) -> None:
        handle.progressChanged.connect(lambda _percent, _message: self._refresh())
        handle.stateChanged.connect(lambda _state: self._refresh())
        self._refresh()

    @staticmethod
    def _label(item: TaskHandle | TaskRecord) -> str:
        progress = f" {item.progress_percent}%" if item.progress_percent else ""
        return (
            f"{item.state.value.title():10}  {item.label}{progress}  [{item.priority.name.lower()}]"
        )

    def _refresh(self) -> None:
        selected = self._selected_item()
        self._items = [*self.service.active, *reversed(self.service.history)]
        self.tasks.clear()
        selected_row = -1
        for row, item in enumerate(self._items):
            self.tasks.addItem(self._label(item))
            if item is selected:
                selected_row = row
        if self._items:
            self.tasks.setCurrentRow(max(0, selected_row))
        else:
            self.details.setPlainText("No background tasks in this session.")
            self._update_buttons(None)

    def _selected_item(self) -> TaskHandle | TaskRecord | None:
        row = self.tasks.currentRow()
        return self._items[row] if 0 <= row < len(self._items) else None

    def _show_selected(self, _row: int) -> None:
        item = self._selected_item()
        self._update_buttons(item)
        if item is None:
            return
        created = item.created_at.isoformat(timespec="seconds")
        started = item.started_at.isoformat(timespec="seconds") if item.started_at else "—"
        finished = item.finished_at.isoformat(timespec="seconds") if item.finished_at else "—"
        error = item.error.strip().splitlines()[-1] if item.error.strip() else "—"
        self.details.setPlainText(
            f"Operation: {item.label}\nID: {item.task_id}\nState: {item.state.value}\n"
            f"Priority: {item.priority.name.lower()}\nScope: {item.scope_id or 'application'}\n"
            f"Progress: {item.progress_percent}% {item.progress_message}\n"
            f"Queued: {created}\nStarted: {started}\nFinished: {finished}\n"
            f"Result/error: {error}"
        )

    def _update_buttons(self, item: TaskHandle | TaskRecord | None) -> None:
        active = isinstance(item, TaskHandle) and item in self.service.active
        self.cancel_selected.setEnabled(active)
        self.cancel_scope.setEnabled(bool(active and item.scope_id))
        self.cancel_all.setEnabled(bool(self.service.active))

    def _cancel_selected(self) -> None:
        item = self._selected_item()
        if isinstance(item, TaskHandle):
            self.service.cancel_task(item)

    def _cancel_selected_scope(self) -> None:
        item = self._selected_item()
        if isinstance(item, TaskHandle) and item.scope_id:
            self.service.cancel_scope(item.scope_id)

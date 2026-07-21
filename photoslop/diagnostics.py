# SPDX-License-Identifier: Apache-2.0
"""Durable, redacted operation diagnostics and their viewer."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QTextEdit,
    QVBoxLayout,
)

_ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_AUTHORIZATION_HEADER = re.compile(r"(?im)^(Authorization\s*:\s*).+$")
_SECRET_KEY = re.compile(r"(?i)^(password|passwd|token|secret|api[_-]?key|authorization)$")
_URL_CREDENTIALS = re.compile(r"(https?://)[^/@\s:]+:[^/@\s]+@", re.I)
_MAX_DETAIL = 16_000
_UTC = timezone.utc


def redact(value: object) -> str:
    text = str(value)
    text = _AUTHORIZATION_HEADER.sub(r"\1[REDACTED]", text)
    text = _ASSIGNMENT_SECRET.sub(r"\1\2[REDACTED]", text)
    text = _BEARER_SECRET.sub("Bearer [REDACTED]", text)
    text = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    if len(text) > _MAX_DETAIL:
        text = text[:_MAX_DETAIL] + "\n[details truncated]"
    return text


@dataclass(frozen=True)
class DiagnosticRecord:
    identifier: str
    timestamp: str
    operation: str
    summary: str
    details: str
    guidance: str
    context: dict[str, str]


class DiagnosticStore(QObject):
    recordAdded = Signal(object)

    def __init__(self, root: str | None = None, *, retention: int = 200, parent=None) -> None:
        super().__init__(parent)
        settings_dir = os.path.dirname(QSettings("CryptoJones", "Photoslop").fileName())
        self.root = root or os.path.join(settings_dir, "diagnostics")
        self.path = os.path.join(self.root, "operations.jsonl")
        self.retention = max(10, retention)
        self._records = self._load()
        self._fingerprints = {self._fingerprint(record) for record in self._records}

    @property
    def records(self) -> tuple[DiagnosticRecord, ...]:
        return tuple(self._records)

    def record(
        self,
        operation: str,
        summary: str,
        *,
        details: str = "",
        guidance: str = "Retry the operation; if it repeats, include this diagnostic ID.",
        context: dict[str, object] | None = None,
    ) -> DiagnosticRecord:
        record = DiagnosticRecord(
            uuid.uuid4().hex[:12],
            datetime.now(_UTC).isoformat(),
            redact(operation),
            redact(summary),
            redact(details),
            redact(guidance),
            {
                redact(key): "[REDACTED]" if _SECRET_KEY.fullmatch(str(key)) else redact(value)
                for key, value in (context or {}).items()
            },
        )
        fingerprint = self._fingerprint(record)
        if fingerprint in self._fingerprints:
            return next(
                item for item in reversed(self._records) if self._fingerprint(item) == fingerprint
            )
        self._records.append(record)
        self._fingerprints.add(fingerprint)
        self._records = self._records[-self.retention :]
        self._persist()
        self.recordAdded.emit(record)
        return record

    def record_task_failure(self, handle, traceback_text: str) -> DiagnosticRecord:
        guidance = (
            "Check the destination and available disk space, then retry."
            if handle.task_id.startswith(("file.", "recovery."))
            else "Check the configured endpoint and network policy, then retry."
            if handle.task_id.startswith("model.")
            else "Retry once; if it repeats, disable the related optional backend."
        )
        return self.record(
            handle.task_id,
            f"{handle.label} failed",
            details=traceback_text,
            guidance=guidance,
            context={
                "scope": handle.scope_id or "application",
                "priority": handle.priority.name.lower(),
                "progress": f"{handle.progress_percent}% {handle.progress_message}".strip(),
            },
        )

    def record_task_result(self, handle) -> DiagnosticRecord | None:
        """Persist user-visible completion/cancellation; autosave stays quiet."""
        if handle.task_id.startswith("recovery."):
            return None
        finished = handle.finished_at.isoformat() if handle.finished_at else "unknown"
        return self.record(
            handle.task_id,
            f"{handle.label} {handle.state.value}",
            details=f"Task finished at {finished} with state {handle.state.value}.",
            guidance=(
                "No action is required."
                if handle.state.value == "succeeded"
                else "Retry the operation when ready."
            ),
            context={
                "scope": handle.scope_id or "application",
                "priority": handle.priority.name.lower(),
                "progress": f"{handle.progress_percent}% {handle.progress_message}".strip(),
            },
        )

    @staticmethod
    def _fingerprint(record: DiagnosticRecord) -> tuple[str, str, str]:
        return record.operation, record.summary, record.details

    def _load(self) -> list[DiagnosticRecord]:
        try:
            with open(self.path, encoding="utf-8") as stream:
                lines = stream.readlines()[-self.retention :]
        except OSError:
            return []
        records = []
        for line in lines:
            try:
                records.append(DiagnosticRecord(**json.loads(line)))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return records

    def _persist(self) -> None:
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            for record in self._records:
                stream.write(json.dumps(asdict(record), sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)


class DiagnosticsDialog(QDialog):
    def __init__(self, store: DiagnosticStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Diagnostics")
        self.resize(720, 480)
        self.summary = QLabel(
            "Persistent operation results and failures are redacted before being stored."
        )
        self.records = QListWidget()
        self.records.setAccessibleName("Diagnostic records")
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Selected diagnostic details")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.records, 1)
        layout.addWidget(self.details, 2)
        layout.addWidget(buttons)
        self.records.currentRowChanged.connect(self._show_record)
        self._refresh()

    def _refresh(self) -> None:
        self.records.clear()
        for record in reversed(self.store.records):
            self.records.addItem(
                f"{record.timestamp[:19]}  {record.summary}  [{record.identifier}]"
            )
        if self.records.count():
            self.records.setCurrentRow(0)
        else:
            self.details.setPlainText("No recorded operations.")

    def _show_record(self, row: int) -> None:
        if row < 0:
            return
        record = tuple(reversed(self.store.records))[row]
        context = "\n".join(f"{key}: {value}" for key, value in record.context.items())
        self.details.setPlainText(
            f"ID: {record.identifier}\nOperation: {record.operation}\n"
            f"When: {record.timestamp}\n{context}\n\n{record.summary}\n\n"
            f"{record.details}\n\nNext step: {record.guidance}"
        )

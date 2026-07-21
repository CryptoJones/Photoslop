# SPDX-License-Identifier: Apache-2.0
"""Crash-recovery snapshots stored as atomic OpenRaster documents."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from zipfile import BadZipFile

from defusedxml.ElementTree import ParseError
from PySide6.QtCore import QSettings

from photoslop import __version__
from photoslop.atomicio import WriteTicket, atomic_write
from photoslop.io_ora import load_ora, save_ora


class RecoveryService:
    SCHEMA_VERSION = 1

    def __init__(self, root: str | None = None, *, max_documents: int = 20,
                 max_age_days: int = 30) -> None:
        settings_dir = os.path.dirname(
            QSettings("CryptoJones", "Photoslop").fileName())
        self.root = root or os.path.join(settings_dir, "recovery")
        self.max_documents = max(1, max_documents)
        self.max_age = timedelta(days=max(1, max_age_days))

    def path_for(self, document_id: str) -> str:
        return os.path.join(self.root, f"{document_id}.ora")

    def metadata_path_for(self, document_id: str) -> str:
        return os.path.join(self.root, f"{document_id}.recovery.json")

    def write(self, document, *, ticket: WriteTicket | None = None,
              before_commit=None) -> str:
        os.makedirs(self.root, exist_ok=True)
        path = self.path_for(document.document_id)
        save_ora(
            document, path, ticket=ticket, before_commit=before_commit)
        metadata = {
            "schema_version": self.SCHEMA_VERSION,
            "app_version": __version__,
            "document_id": document.document_id,
            "name": document.name,
            "source_path": document.path,
            "saved_at": datetime.now(UTC).isoformat(),
        }

        def write_metadata(temporary: str) -> None:
            with open(temporary, "w", encoding="utf-8") as stream:
                json.dump(metadata, stream, indent=2, sort_keys=True)
                stream.write("\n")

        atomic_write(
            self.metadata_path_for(document.document_id), write_metadata,
            before_commit=before_commit, durable=True)
        self.prune()
        return path

    def clear(self, document_id: str) -> None:
        for path in (self.path_for(document_id), self.metadata_path_for(document_id)):
            with suppress(FileNotFoundError):
                os.unlink(path)

    def clear_all(self) -> None:
        if not os.path.isdir(self.root):
            return
        for name in os.listdir(self.root):
            if name.endswith((".ora", ".recovery.json")):
                with suppress(FileNotFoundError):
                    os.unlink(os.path.join(self.root, name))

    def _metadata(self, document_id: str) -> dict:
        try:
            with open(self.metadata_path_for(document_id), encoding="utf-8") as stream:
                metadata = json.load(stream)
        except (OSError, ValueError, TypeError):
            return {}
        if metadata.get("schema_version") != self.SCHEMA_VERSION:
            return {}
        return metadata

    def prune(self) -> None:
        if not os.path.isdir(self.root):
            return
        now = datetime.now(UTC)
        snapshots = []
        for name in os.listdir(self.root):
            if not name.endswith(".ora"):
                continue
            path = os.path.join(self.root, name)
            document_id = name[:-4]
            metadata = self._metadata(document_id)
            try:
                saved_at = datetime.fromisoformat(metadata["saved_at"])
            except (KeyError, TypeError, ValueError):
                saved_at = datetime.fromtimestamp(os.path.getmtime(path), UTC)
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=UTC)
            if now - saved_at > self.max_age:
                self.clear(document_id)
                continue
            snapshots.append((saved_at, document_id))
        for _saved_at, document_id in sorted(snapshots, reverse=True)[self.max_documents:]:
            self.clear(document_id)

    def available(self) -> list:
        if not os.path.isdir(self.root):
            return []
        self.prune()
        recovered = []
        for name in sorted(os.listdir(self.root)):
            if not name.endswith(".ora"):
                continue
            path = os.path.join(self.root, name)
            try:
                document = load_ora(path)
            except (OSError, ValueError, KeyError, ParseError, BadZipFile):
                continue
            document.path = None
            document.name = f"Recovered {document.embedded_name}"
            metadata = self._metadata(document.document_id)
            document.recovery_original_path = metadata.get("source_path")
            document.recovery_saved_at = metadata.get("saved_at")
            recovered.append(document)
        return recovered

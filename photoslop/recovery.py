# SPDX-License-Identifier: Apache-2.0
"""Crash-recovery snapshots stored as atomic OpenRaster documents."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from contextlib import suppress

from PySide6.QtCore import QSettings

from photoslop.atomicio import WriteTicket
from photoslop.io_ora import load_ora, save_ora


class RecoveryService:
    def __init__(self, root: str | None = None) -> None:
        settings_dir = os.path.dirname(
            QSettings("CryptoJones", "Photoslop").fileName())
        self.root = root or os.path.join(settings_dir, "recovery")

    def path_for(self, document_id: str) -> str:
        return os.path.join(self.root, f"{document_id}.ora")

    def write(self, document, *, ticket: WriteTicket | None = None,
              before_commit=None) -> str:
        os.makedirs(self.root, exist_ok=True)
        path = self.path_for(document.document_id)
        save_ora(
            document, path, ticket=ticket, before_commit=before_commit)
        return path

    def clear(self, document_id: str) -> None:
        with suppress(FileNotFoundError):
            os.unlink(self.path_for(document_id))

    def available(self) -> list:
        if not os.path.isdir(self.root):
            return []
        recovered = []
        for name in sorted(os.listdir(self.root)):
            if not name.endswith(".ora"):
                continue
            path = os.path.join(self.root, name)
            try:
                document = load_ora(path)
            except (OSError, ValueError, KeyError, ET.ParseError):
                continue
            document.path = None
            document.name = f"Recovered {document.embedded_name}"
            recovered.append(document)
        return recovered

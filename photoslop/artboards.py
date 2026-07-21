# SPDX-License-Identifier: Apache-2.0
"""Undoable named artboard editing and ordering."""

from PySide6.QtCore import QRect
from PySide6.QtGui import QUndoCommand


class SetArtboardsCommand(QUndoCommand):
    def __init__(self, doc, boards, text="Edit Artboards"):
        super().__init__(text)
        self.doc = doc
        self.old = [(name, QRect(rect)) for name, rect in doc.artboards]
        self.new = [(name, QRect(rect)) for name, rect in boards]

    def _set(self, boards):
        self.doc.artboards = [(name, QRect(rect)) for name, rect in boards]
        self.doc.notify_structure()

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


def edit(
    doc,
    operation: str,
    *,
    index: int | None = None,
    name: str | None = None,
    rect: list[int] | None = None,
    to: int | None = None,
) -> None:
    boards = [(label, QRect(bounds)) for label, bounds in doc.artboards]
    if operation == "add":
        if rect is None:
            raise ValueError("add requires rect")
        boards.append((name or f"Artboard {len(boards) + 1}", QRect(*rect)))
    elif operation == "update":
        if index is None:
            raise ValueError("update requires index")
        old_name, old_rect = boards[index]
        boards[index] = (name or old_name, QRect(*rect) if rect is not None else old_rect)
    elif operation == "delete":
        boards.pop(index if index is not None else -1)
    elif operation == "reorder":
        if index is None or to is None:
            raise ValueError("reorder requires index and to")
        boards.insert(to, boards.pop(index))
    elif operation == "clear":
        boards.clear()
    else:
        raise ValueError(f"unknown artboard operation {operation!r}")
    doc.undo_stack.push(SetArtboardsCommand(doc, boards))

# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QPainterPath

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.mainwindow import MainWindow


def rect_path(x, y, w, h) -> QPainterPath:
    path = QPainterPath()
    path.addRect(QRectF(x, y, w, h))
    return path


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(120, 90), 72.0, "ab", QColor(255, 255, 255))
    doc.layers[0].image.fill(QColor(10, 120, 240))
    win.add_document(doc)
    return win


def test_artboard_from_selection_and_export(qapp, tmp_path):
    win = make_window(qapp)
    doc = win.current_doc()

    win.action_add_artboard()  # no selection: refused
    assert doc.artboards == []

    doc.set_selection(rect_path(10, 10, 40, 30))
    win.action_add_artboard()
    assert doc.artboards == [("Artboard 1", QRect(10, 10, 40, 30))]
    assert doc.selection_bounds() is None  # selection consumed

    doc.set_selection(rect_path(60, 20, 50, 50))
    win.action_add_artboard()
    written = win.action_export_artboards(directory=str(tmp_path))
    assert len(written) == 2
    board = QImage(written[0])
    assert board.size() == QSize(40, 30)
    assert board.pixelColor(5, 5) == QColor(10, 120, 240)
    assert written[1].endswith("Artboard 2.png")


def test_artboards_round_trip_and_clear(qapp, tmp_path):
    win = make_window(qapp)
    doc = win.current_doc()
    doc.artboards = [("Cover", QRect(0, 0, 60, 90)),
                     ("Spread/2", QRect(60, 0, 60, 90))]  # slash sanitised
    path = str(tmp_path / "boards.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert loaded.artboards == doc.artboards

    written = win.action_export_artboards(directory=str(tmp_path))
    assert any(w.endswith("Spread_2.png") for w in written)

    win.action_clear_artboards()
    assert doc.artboards == []

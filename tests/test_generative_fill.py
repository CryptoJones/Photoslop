# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRectF, QSettings, QSize
from PySide6.QtGui import QColor, QImage, QPainterPath
from PySide6.QtTest import QTest

from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.modeladapter import (
    GENERATIVE_FILL,
    ModelAdapter,
    register_adapter,
)


class FillAdapter(ModelAdapter):
    name = "fill-fake"
    label = "Fake fill adapter"
    last_prompt = None

    def capabilities(self):
        return frozenset({GENERATIVE_FILL})

    def generative_fill(self, image, mask, prompt):
        FillAdapter.last_prompt = prompt
        assert mask.pixelColor(15, 15).red() > 200  # selection is white
        assert mask.pixelColor(2, 2).red() == 0
        out = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(QColor(20, 200, 40))
        return out


class WrongSizeAdapter(FillAdapter):
    name = "fill-wrong"
    label = "Wrong-size adapter"

    def generative_fill(self, image, mask, prompt):
        out = QImage(3, 3, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(QColor(1, 1, 1))
        return out


def rect_path(x, y, w, h) -> QPainterPath:
    path = QPainterPath()
    path.addRect(QRectF(x, y, w, h))
    return path


def make_window(qapp, adapter_name) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 40), 72.0, "gf",
                                  QColor(200, 100, 50)))
    QSettings("CryptoJones", "Photoslop").setValue("model/adapter", adapter_name)
    return win


def test_generative_fill_respects_selection_and_undo(qapp):
    register_adapter(FillAdapter)
    win = make_window(qapp, "fill-fake")
    doc = win.current_doc()

    win.action_generative_fill(prompt="a corn field")  # no selection yet
    assert doc.undo_stack.count() == 0

    doc.set_selection(rect_path(10, 10, 12, 12))
    win.action_generative_fill(prompt="a corn field")
    while win.task_service.active:
        qapp.processEvents()
        QTest.qWait(5)
    assert FillAdapter.last_prompt == "a corn field"
    layer = doc.active_layer
    assert layer.image.pixelColor(15, 15) == QColor(20, 200, 40)  # inside
    assert layer.image.pixelColor(2, 2) == QColor(200, 100, 50)  # outside
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert layer.image.pixelColor(15, 15) == QColor(200, 100, 50)


def test_generative_fill_guards(qapp):
    register_adapter(WrongSizeAdapter)
    win = make_window(qapp, "fill-wrong")
    doc = win.current_doc()
    doc.set_selection(rect_path(5, 5, 10, 10))
    win.action_generative_fill(prompt="x")  # wrong-size result refused
    while win.task_service.active:
        qapp.processEvents()
        QTest.qWait(5)
    assert doc.undo_stack.count() == 0
    assert doc.active_layer.image.pixelColor(7, 7) == QColor(200, 100, 50)

    QSettings("CryptoJones", "Photoslop").setValue("model/adapter", "")
    win.action_generative_fill(prompt="x")  # unconfigured refusal
    assert doc.undo_stack.count() == 0

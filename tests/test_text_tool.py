# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QTextDocument
from PySide6.QtTest import QTest

from photoslop import textdialog, tools
from photoslop.commands import InsertLayerCommand
from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.textdialog import render_text_document, render_text_layer


def test_render_text_layer(qapp):
    font = QFont()
    font.setPointSize(24)
    layer = render_text_layer("Hi", font, QColor(255, 0, 0), QPoint(30, 20))
    assert layer is not None
    assert layer.offset == QPoint(30, 20)
    assert layer.image.width() > 10 and layer.image.height() > 10
    # some rendered pixels are red-ish
    found = any(
        layer.image.pixelColor(x, y).red() > 100
        and layer.image.pixelColor(x, y).alpha() > 100
        for x in range(layer.image.width())
        for y in range(layer.image.height())
    )
    assert found

    multi = render_text_layer("a\nb\nc", font, QColor(0, 0, 0), QPoint(0, 0))
    assert multi.image.height() > layer.image.height()  # three lines taller

    assert render_text_layer("   \n", font, QColor(0, 0, 0), QPoint(0, 0)) is None


def test_render_text_document_per_letter_colour(qapp):
    doc = QTextDocument()
    doc.setHtml('<span style="color:#ff0000;font-size:40pt">A</span>'
                '<span style="color:#00ff00;font-size:40pt">B</span>')
    layer = render_text_document(doc, QPoint(7, 9))
    assert layer is not None
    assert layer.offset == QPoint(7, 9)
    img = layer.image
    has_red = any(
        img.pixelColor(x, y).red() > 180 and img.pixelColor(x, y).green() < 80
        and img.pixelColor(x, y).alpha() > 150
        for x in range(img.width()) for y in range(img.height()))
    has_green = any(
        img.pixelColor(x, y).green() > 180 and img.pixelColor(x, y).red() < 80
        and img.pixelColor(x, y).alpha() > 150
        for x in range(img.width()) for y in range(img.height()))
    assert has_red and has_green  # each letter keeps its own colour
    # the HTML is stamped for re-editing
    assert layer.text_data["text"] == "AB"
    assert "html" in layer.text_data

    assert render_text_document(QTextDocument(), QPoint(0, 0)) is None


def test_text_dialog_rich_round_trip(qapp):
    # a styled block re-opens with its HTML intact and rebuilds a layer
    dlg = textdialog.TextDialog(QColor(0, 0, 0))
    dlg.edit.setHtml('<span style="color:#ff0000;font-size:40pt">Hi</span>')
    layer = dlg.build_layer(QPoint(0, 0))
    assert layer is not None
    html = layer.text_data["html"]

    reopened = textdialog.TextDialog(QColor(0, 0, 0), text="Hi", html=html)
    assert reopened.text() == "Hi"
    assert reopened.windowTitle() == "Edit Text"
    rebuilt = reopened.build_layer(QPoint(0, 0))
    assert rebuilt.text_data["text"] == "Hi"


def test_text_layer_insert_undo(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(200, 100), 72.0, "t", QColor(255, 255, 255)))
    doc = win.current_doc()

    font = QFont()
    font.setPointSize(18)
    layer = render_text_layer("Photoslop", font, QColor(0, 0, 255), QPoint(10, 10))
    doc.undo_stack.push(InsertLayerCommand(doc, len(doc.layers), layer, "Add Text"))

    assert len(doc.layers) == 2
    assert doc.layers[1].name.startswith("Photoslop")
    doc.undo_stack.undo()
    assert len(doc.layers) == 1


def test_render_text_layer_stamps_text_data(qapp):
    font = QFont()
    font.setPointSize(20)
    layer = render_text_layer("Hi", font, QColor(10, 20, 30), QPoint(0, 0))
    assert layer.text_data["text"] == "Hi"
    assert layer.text_data["size"] == 20
    assert layer.text_data["family"] == font.family()
    assert layer.text_data["color"] == [10, 20, 30, 255]
    assert layer.clone().text_data == layer.text_data


def test_text_dialog_prefill_and_color_swatch(qapp, monkeypatch):
    font = QFont()
    font.setPointSize(44)
    dlg = textdialog.TextDialog(QColor(255, 0, 0), text="Howdy", font=font)
    assert dlg.text() == "Howdy"
    assert dlg.windowTitle() == "Edit Text"
    assert dlg.chosen_font().pointSize() == 44

    monkeypatch.setattr(textdialog.QColorDialog, "getColor",
                        staticmethod(lambda *a, **k: QColor(0, 200, 0)))
    dlg.pick_color()
    assert dlg.color == QColor(0, 200, 0)

    # cancelled picker (invalid color) keeps the current choice
    monkeypatch.setattr(textdialog.QColorDialog, "getColor",
                        staticmethod(lambda *a, **k: QColor()))
    dlg.pick_color()
    assert dlg.color == QColor(0, 200, 0)

    fresh = textdialog.TextDialog(QColor(0, 0, 0))
    assert fresh.windowTitle() == "Add Text"
    assert fresh.text() == ""


def test_text_dialog_size_accepts_three_keyboard_digits_without_focus_theft(qapp):
    dlg = textdialog.TextDialog(QColor(0, 0, 0), text="Size me")
    dlg.show()
    qapp.processEvents()

    field = dlg.size.lineEdit()
    field.setFocus()
    field.selectAll()
    QTest.keyClicks(field, "999")
    qapp.processEvents()

    assert dlg.size.value() == 999
    assert field.hasFocus()
    assert not dlg.edit.hasFocus()

    QTest.keyClick(field, Qt.Key.Key_Return)
    qapp.processEvents()
    assert dlg.size.value() == 999
    assert dlg.result() == 0  # Enter commits the spin box, not the dialog.
    assert dlg.chosen_font().pointSize() == 999
    dlg.close()


class _FakeDialog:
    """Stands in for TextDialog: records what it was opened with and answers
    with a fixed edit."""

    captured: dict = {}

    def __init__(self, color, parent=None, text="", font=None, html=None,
                 effects=None, fill_opacity=1.0):
        _FakeDialog.captured = {"color": QColor(color), "text": text,
                                "font": font, "html": html, "effects": effects,
                                "fill_opacity": fill_opacity}
        self.color = QColor(255, 0, 0)

    def exec(self):
        return True

    def text(self):
        return "After"

    def chosen_font(self):
        font = QFont()
        font.setPointSize(18)
        return font

    def build_layer(self, anchor):
        font = QFont()
        font.setPointSize(18)
        return render_text_layer("After", font, self.color, anchor)


class _FakeCanvas:
    def window(self):
        return None


def test_text_tool_edits_existing_text_layer(qapp, monkeypatch):
    win = MainWindow()
    win.add_document(Document.new(QSize(200, 100), 72.0, "t", QColor(255, 255, 255)))
    doc = win.current_doc()
    font = QFont()
    font.setPointSize(18)
    layer = render_text_layer("Before", font, QColor(0, 0, 255), QPoint(10, 10))
    doc.undo_stack.push(InsertLayerCommand(doc, len(doc.layers), layer, "Add Text"))
    doc.active_index = 1

    monkeypatch.setattr(textdialog, "TextDialog", _FakeDialog)
    tool = tools.TextTool(tools.ToolOptions())

    # click inside the active text layer: edit in place, no new layer
    tool.press(doc, _FakeCanvas(), QPointF(15, 15), None)
    assert len(doc.layers) == 2
    assert doc.layers[1].text_data["text"] == "After"
    assert doc.layers[1].offset == QPoint(10, 10)  # anchor is kept
    # the dialog opened pre-filled with the old content and colour
    assert _FakeDialog.captured["text"] == "Before"
    assert _FakeDialog.captured["color"] == QColor(0, 0, 255)
    assert _FakeDialog.captured["font"].pointSize() == 18

    doc.undo_stack.undo()
    assert doc.layers[1].text_data["text"] == "Before"
    doc.undo_stack.redo()
    assert doc.layers[1].text_data["text"] == "After"

    # click outside the active text layer: business as usual, add a layer
    tool.press(doc, _FakeCanvas(), QPointF(150, 80), None)
    assert len(doc.layers) == 3
    assert doc.layers[2].offset == QPoint(150, 80)

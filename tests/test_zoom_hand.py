# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


class _Ev:
    """Minimal stand-in for a QMouseEvent in direct tool calls."""

    def __init__(self, gx=0.0, gy=0.0, mods=Qt.KeyboardModifier.NoModifier):
        self._g = QPointF(gx, gy)
        self._m = mods

    def globalPosition(self):
        return self._g

    def modifiers(self):
        return self._m


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(800, 600), 72.0, "nav", QColor(255, 255, 255)))
    win.resize(400, 300)  # smaller than the canvas → scrollbars have range
    win.show()
    qapp.processEvents()
    return win


def test_hand_tool_pans(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    canvas = editor.canvas
    hbar = editor.scroll.horizontalScrollBar()
    vbar = editor.scroll.verticalScrollBar()
    hbar.setValue(50)
    vbar.setValue(50)

    tool = win.tools["hand"]
    doc = editor.doc
    tool.press(doc, canvas, QPointF(10, 10), _Ev(100, 100))
    tool.move(doc, canvas, QPointF(10, 10), _Ev(130, 120))  # drag right+down
    assert hbar.value() == 20  # content follows the hand
    assert vbar.value() == 30
    tool.release(doc, canvas, QPointF(10, 10), _Ev(130, 120))
    assert tool._last is None


def test_zoom_tool_click_and_alt_click(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    canvas = editor.canvas
    tool = win.tools["zoom"]
    start = canvas.zoom

    tool.press(editor.doc, canvas, QPointF(100, 100), _Ev())
    assert canvas.zoom > start
    tool.press(editor.doc, canvas, QPointF(100, 100), _Ev(mods=Qt.KeyboardModifier.AltModifier))
    assert canvas.zoom == start  # one step up, one step down


def test_space_pan_routes_mouse_to_panning(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    canvas = editor.canvas
    hbar = editor.scroll.horizontalScrollBar()
    hbar.setValue(40)

    canvas._space_pan = True  # as set by keyPressEvent(Space)
    canvas._pan_last = QPointF(200, 200)
    editor.pan_by(25, 0)
    assert hbar.value() == 15

    # releasing Space clears panning state
    class _KeyEv:
        def key(self):
            return Qt.Key.Key_Space

        def isAutoRepeat(self):
            return False

    canvas.keyReleaseEvent(_KeyEv())
    assert canvas._space_pan is False and canvas._pan_last is None

# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


class _Ev:
    def __init__(self, mods=Qt.KeyboardModifier.NoModifier):
        self._m = mods

    def modifiers(self):
        return self._m


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(200, 160), 72.0, "t", QColor(0, 0, 0, 0))
    chip = Layer.blank("chip", QSize(40, 20), QPoint(80, 70))  # centre (100, 80)
    chip.image.fill(QColor(255, 0, 0))
    doc.layers.append(chip)
    doc.active_index = 1
    win.add_document(doc)
    return win


def test_scale_via_handle_and_commit(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer

    win.action_free_transform()
    assert win.active_tool.name == "transform"
    tool = win.tools["transform"]

    # drag the right edge handle from x=100+20 to x=100+40 → sx = 2
    tool.press(doc, editor.canvas, QPointF(120, 80), _Ev())
    assert tool._mode == "r"
    tool.move(doc, editor.canvas, QPointF(140, 80), _Ev())
    tool.release(doc, editor.canvas, QPointF(140, 80), _Ev())
    tool.commit(editor.canvas)

    assert layer.image.size() == QSize(80, 20)  # doubled width
    assert layer.offset == QPoint(60, 70)  # centre preserved at (100, 80)
    assert win.active_tool.name != "transform"  # tool restored
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert layer.image.size() == QSize(40, 20)
    assert layer.offset == QPoint(80, 70)


def test_rotate_90_and_move(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer
    win.action_free_transform()
    tool = win.tools["transform"]

    tool.session.rotation = 90.0  # set directly; drag math tested via hit zones
    tool.session.translation = QPointF(10, -5)
    tool.commit(editor.canvas)

    assert layer.image.size() == QSize(20, 40)  # W/H swapped
    assert layer.offset == QPoint(100, 55)  # centre moved to (110, 75)


def test_escape_cancels_exactly(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer
    before = layer.image.copy()

    win.action_free_transform()
    tool = win.tools["transform"]
    tool.session.scale_x = 3.0
    tool.session.rotation = 45.0
    tool.cancel(doc)
    win.end_transform()

    assert layer.image == before
    assert layer.offset == QPoint(80, 70)
    assert doc.undo_stack.count() == 0
    assert win.active_tool.name != "transform"


def test_hit_zones(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    win.action_free_transform()
    tool = win.tools["transform"]
    assert tool._hit(editor.canvas, QPointF(100, 80)) == "move"  # centre
    assert tool._hit(editor.canvas, QPointF(80, 70)) == "tl"
    assert tool._hit(editor.canvas, QPointF(120, 90)) == "br"
    assert tool._hit(editor.canvas, QPointF(100, 70)) == "t"
    assert tool._hit(editor.canvas, QPointF(170, 20)) == "rotate"  # far outside
    tool.cancel(editor.doc)
    win.end_transform()


def test_identity_commit_pushes_nothing(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    win.action_free_transform()
    win.tools["transform"].commit(editor.canvas)
    assert doc.undo_stack.count() == 0


def _text_window(qapp):
    from PySide6.QtGui import QFont

    from photoslop.textdialog import render_text_layer

    win = MainWindow()
    doc = Document.new(QSize(400, 300), 72.0, "t", QColor(0, 0, 0, 0))
    font = QFont()
    font.setPointSize(20)
    text = render_text_layer("Crisp", font, QColor(0, 0, 0), QPoint(50, 50))
    doc.layers.append(text)
    doc.active_index = 1
    win.add_document(doc)
    return win, doc, text


def test_uniform_scale_rerenders_text_instead_of_resampling(qapp):
    """#294: a uniformly scaled text layer re-renders its type from
    `text_data` instead of resampling pixels — the stored size doubles, the
    layer stays editable, and undo restores both."""
    win, doc, layer = _text_window(qapp)
    base_size = layer.text_data["size"]
    editor = win.current_editor()

    win.action_free_transform()
    tool = win.tools["transform"]
    session = tool.session
    session.scale_x = 2.0
    session.scale_y = 2.0
    tool.commit(editor.canvas)

    assert layer.text_data is not None, "a scaled text layer is still text"
    assert abs(layer.text_data["size"] - base_size * 2) <= 1
    # Re-rendered, not resampled: the new raster is the tight extent of the
    # doubled type, roughly double each side of the original.
    assert layer.image.width() > 1.5 * 60  # original "Crisp" at 20pt is ~60px wide

    doc.undo_stack.undo()
    assert layer.text_data["size"] == base_size


def test_rotation_rasterises_text_and_drops_text_data(qapp):
    """A transform the type cannot absorb rasterises the layer: stale
    text_data would let a later edit silently discard the rotation, so it is
    dropped — and restored by undo."""
    win, doc, layer = _text_window(qapp)
    editor = win.current_editor()

    win.action_free_transform()
    tool = win.tools["transform"]
    tool.session.rotation = 45.0
    tool.commit(editor.canvas)

    assert layer.text_data is None, "a rotated text layer is honestly raster"
    doc.undo_stack.undo()
    assert layer.text_data is not None, "undo brings the editable text back"


def test_uniform_scale_rerenders_rich_text_per_letter_sizes(qapp):
    """The GUI's text tool writes rich HTML with per-letter styling — the
    re-render path must scale every explicit size, not just the default."""
    from PySide6.QtGui import QTextDocument

    from photoslop.textdialog import render_text_document

    win = MainWindow()
    doc = Document.new(QSize(600, 400), 72.0, "t", QColor(0, 0, 0, 0))
    source = QTextDocument()
    source.setHtml(
        '<span style="font-size:16pt">small</span>'
        '<span style="font-size:32pt; color:#ff0000">BIG</span>'
    )
    layer = render_text_document(source, QPoint(40, 40))
    doc.layers.append(layer)
    doc.active_index = 1
    win.add_document(doc)
    base_width = layer.image.width()
    editor = win.current_editor()

    win.action_free_transform()
    tool = win.tools["transform"]
    tool.session.scale_x = 2.0
    tool.session.scale_y = 2.0
    tool.commit(editor.canvas)

    assert layer.text_data is not None and layer.text_data.get("html")
    assert layer.image.width() > 1.6 * base_width, "the type itself doubled"
    assert "32pt" not in layer.text_data["html"] or "64pt" in layer.text_data["html"]

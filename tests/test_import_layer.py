# SPDX-License-Identifier: Apache-2.0
"""Importing an image file as a layer of the *open* document.

File ▸ Open is how a file becomes a document; Layer ▸ New Layer from Image is
how one joins the document already open. Neither command guesses which was
meant — that ruling is shared with the iOS "new layer from photo" button, and
mirrored headlessly by ``--import-layer``.
"""

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.opendialog import OpenImageDialog
from photoslop.services import FileService


def _png(tmp_path, name, size, color) -> str:
    image = QImage(QSize(*size), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(*color))
    path = str(tmp_path / name)
    image.save(path)
    return path


def _window(qapp, size=(80, 60)) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(*size), 72, "import", QColor("white")))
    return win


def test_load_as_layer_centres_at_native_size(qapp, tmp_path):
    path = _png(tmp_path, "stamp.png", (20, 10), (0, 160, 220))
    layer = FileService.load_as_layer(path, QSize(80, 60))
    assert layer.name == "stamp"
    assert layer.image.size() == QSize(20, 10)
    assert (layer.offset.x(), layer.offset.y()) == (30, 25)


def test_load_as_layer_keeps_pixels_that_overhang_the_canvas(qapp, tmp_path):
    """The desktop engine gives every layer its own offset and extent, so an
    import larger than the canvas keeps all of its pixels and hangs off the
    edges. iOS scales to fit instead — a `.photoslop` layer image must be
    exactly canvas-sized or the document cannot be saved at all."""
    path = _png(tmp_path, "big.png", (200, 100), (200, 30, 30))
    layer = FileService.load_as_layer(path, QSize(80, 60))
    assert layer.image.size() == QSize(200, 100)
    assert (layer.offset.x(), layer.offset.y()) == (-60, -20)


def test_load_as_layer_flattens_a_layered_source(qapp, tmp_path):
    """A layer is one buffer; keeping the source's stack would make the import
    a merge of two documents rather than one new layer."""
    from photoslop.io_ora import save_ora
    from photoslop.layer import Layer

    source = Document.new(QSize(30, 20), 72, "stack", QColor("white"))
    source.layers.append(
        Layer("Top", QImage(QSize(30, 20), QImage.Format.Format_ARGB32_Premultiplied))
    )
    ora = str(tmp_path / "stack.ora")
    save_ora(source, ora)

    layer = FileService.load_as_layer(ora, QSize(80, 60))
    assert layer.image.size() == QSize(30, 20)


def test_menu_action_adds_every_selection_in_one_undo_step(qapp, tmp_path, monkeypatch):
    win = _window(qapp)
    doc = win.current_doc()
    first = _png(tmp_path, "one.png", (20, 10), (0, 160, 220))
    second = _png(tmp_path, "two.png", (10, 10), (220, 160, 0))
    monkeypatch.setattr(OpenImageDialog, "get_paths", staticmethod(lambda *a, **k: [first, second]))

    win.action_import_layer()

    assert [layer.name for layer in doc.layers] == ["Background", "one", "two"]
    assert doc.active_index == 2
    # one undo step for the whole selection, not one per file
    doc.undo_stack.undo()
    assert [layer.name for layer in doc.layers] == ["Background"]
    doc.undo_stack.redo()
    assert [layer.name for layer in doc.layers] == ["Background", "one", "two"]


def test_menu_action_reports_a_bad_file_and_imports_the_rest(qapp, tmp_path, monkeypatch):
    win = _window(qapp)
    doc = win.current_doc()
    good = _png(tmp_path, "good.png", (20, 10), (0, 160, 220))
    broken = str(tmp_path / "broken.png")
    (tmp_path / "broken.png").write_bytes(b"not an image")
    monkeypatch.setattr(OpenImageDialog, "get_paths", staticmethod(lambda *a, **k: [broken, good]))

    warned = []
    monkeypatch.setattr(
        "photoslop.mainwindow.QMessageBox.warning", lambda *args, **kw: warned.append(args)
    )

    win.action_import_layer()

    assert warned, "a file that cannot be decoded should be reported, not silently skipped"
    assert [layer.name for layer in doc.layers] == ["Background", "good"]


def test_menu_action_is_a_no_op_without_a_document(qapp, monkeypatch):
    win = MainWindow()
    called = []
    monkeypatch.setattr(
        OpenImageDialog, "get_paths", staticmethod(lambda *a, **k: called.append(1) or [])
    )
    win.action_import_layer()
    assert not called, "no open document means nothing to import into"


def test_the_import_action_is_registered_and_needs_a_document(qapp):
    win = MainWindow()
    win.action_registry.update()
    spec, action = win.action_registry.entries["import.layer"]
    assert spec.label == "New Layer from Image"
    assert spec.shortcut == "Ctrl+Shift+I"
    assert spec.prerequisite == "document"
    assert not action.isEnabled()
    win.add_document(Document.new(QSize(20, 20), 72, "doc", QColor("white")))
    assert action.isEnabled()


def test_import_that_fits_never_asks_about_the_canvas(qapp, tmp_path, monkeypatch):
    win = _window(qapp)
    path = _png(tmp_path, "small.png", (20, 10), (0, 160, 220))
    monkeypatch.setattr(OpenImageDialog, "get_paths", staticmethod(lambda *a, **k: [path]))
    asked = []
    monkeypatch.setattr(win, "_ask_import_overhang", lambda count: asked.append(count) or "keep")

    win.action_import_layer()

    assert not asked, "a source inside the canvas gives the prompt nothing to ask"
    assert [layer.name for layer in win.current_doc().layers] == ["Background", "small"]


def test_oversized_import_can_expand_the_canvas_in_one_undo_step(qapp, tmp_path, monkeypatch):
    win = _window(qapp)  # 80x60 canvas
    doc = win.current_doc()
    path = _png(tmp_path, "big.png", (200, 100), (200, 30, 30))
    monkeypatch.setattr(OpenImageDialog, "get_paths", staticmethod(lambda *a, **k: [path]))
    monkeypatch.setattr(win, "_ask_import_overhang", lambda count: "expand")

    win.action_import_layer()

    assert doc.size == QSize(200, 100)
    # the import centred the source, so expansion shifts every layer clear of
    # the negative offsets: the new layer starts at the origin, the old
    # background keeps its place relative to the source
    assert (doc.layers[1].offset.x(), doc.layers[1].offset.y()) == (0, 0)
    assert (doc.layers[0].offset.x(), doc.layers[0].offset.y()) == (60, 20)
    doc.undo_stack.undo()
    assert doc.size == QSize(80, 60)
    assert [layer.name for layer in doc.layers] == ["Background"]
    assert (doc.layers[0].offset.x(), doc.layers[0].offset.y()) == (0, 0)


def test_oversized_import_can_keep_the_canvas_and_overhang(qapp, tmp_path, monkeypatch):
    win = _window(qapp)
    doc = win.current_doc()
    path = _png(tmp_path, "big.png", (200, 100), (200, 30, 30))
    monkeypatch.setattr(OpenImageDialog, "get_paths", staticmethod(lambda *a, **k: [path]))
    monkeypatch.setattr(win, "_ask_import_overhang", lambda count: "keep")

    win.action_import_layer()

    assert doc.size == QSize(80, 60)
    layer = doc.layers[1]
    assert layer.image.size() == QSize(200, 100), "keeping the canvas drops no pixels"
    assert (layer.offset.x(), layer.offset.y()) == (-60, -20)


def test_oversized_import_can_be_cancelled_at_the_prompt(qapp, tmp_path, monkeypatch):
    win = _window(qapp)
    doc = win.current_doc()
    path = _png(tmp_path, "big.png", (200, 100), (200, 30, 30))
    monkeypatch.setattr(OpenImageDialog, "get_paths", staticmethod(lambda *a, **k: [path]))
    monkeypatch.setattr(win, "_ask_import_overhang", lambda count: "cancel")

    win.action_import_layer()

    assert [layer.name for layer in doc.layers] == ["Background"]
    assert doc.undo_stack.count() == 0, "a cancelled import leaves no undo entry behind"

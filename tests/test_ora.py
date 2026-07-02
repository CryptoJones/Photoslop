# SPDX-License-Identifier: Apache-2.0
import zipfile

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import Layer


def test_ora_round_trip(qapp, tmp_path):
    doc = Document.new(QSize(40, 30), 144.0, "art", QColor(10, 20, 30))
    top = Layer.blank("scribble", QSize(16, 12), QPoint(5, 7))
    top.image.fill(QColor(200, 100, 50, 255))
    top.opacity = 0.5
    top.visible = False
    doc.layers.append(top)

    path = str(tmp_path / "art.ora")
    save_ora(doc, path)

    with zipfile.ZipFile(path) as zf:
        assert zf.read("mimetype") == b"image/openraster"
        names = zf.namelist()
        assert "stack.xml" in names and "mergedimage.png" in names

    loaded = load_ora(path)
    assert loaded.size == QSize(40, 30)
    assert loaded.dpi == 144.0
    assert len(loaded.layers) == 2
    bottom, restored = loaded.layers
    assert bottom.name == "Background"
    assert restored.name == "scribble"
    assert restored.offset == QPoint(5, 7)
    assert abs(restored.opacity - 0.5) < 1e-3
    assert restored.visible is False
    assert restored.image.size() == QSize(16, 12)
    assert restored.image.pixelColor(3, 3) == QColor(200, 100, 50)
    assert bottom.image.pixelColor(0, 0) == QColor(10, 20, 30)

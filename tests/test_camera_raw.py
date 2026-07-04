# SPDX-License-Identifier: Apache-2.0
import sys

import numpy as np
import pytest
from PySide6.QtGui import QImage

from photoslop import io_raw, mainwindow
from photoslop.io_raw import RawSupportError, is_raw_path, load_raw
from photoslop.mainwindow import MainWindow


class FakeRaw:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def postprocess(self, **kwargs):
        assert kwargs.get("use_camera_wb") is True
        rgb = np.zeros((6, 8, 3), dtype=np.uint8)
        rgb[:, :, 0] = 200  # red-ish frame
        rgb[2, 3] = (10, 250, 30)
        return rgb


class FakeRawpy:
    @staticmethod
    def imread(path):
        return FakeRaw()


def test_is_raw_path():
    assert is_raw_path("shot.NEF") and is_raw_path("x.cr3") and is_raw_path("y.dng")
    assert not is_raw_path("flat.png") and not is_raw_path("doc.ora")


def test_load_raw_decodes_via_rawpy(qapp, monkeypatch):
    monkeypatch.setitem(sys.modules, "rawpy", FakeRawpy())
    img = load_raw("fake.nef")
    assert img.format() == QImage.Format.Format_ARGB32_Premultiplied
    assert img.width() == 8 and img.height() == 6
    assert img.pixelColor(0, 0).red() == 200
    assert img.pixelColor(3, 2).green() == 250


def test_missing_rawpy_gives_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "rawpy", None)  # forces ImportError
    with pytest.raises(RawSupportError, match="photoslop\\[raw\\]"):
        load_raw("shot.arw")


def test_open_path_routes_raw_to_document(qapp, monkeypatch):
    win = MainWindow()
    monkeypatch.setitem(sys.modules, "rawpy", FakeRawpy())
    # dismiss the (new in v1.10) develop dialog: cancel = camera defaults
    from photoslop.rawdialog import RawDevelopDialog

    monkeypatch.setattr(RawDevelopDialog, "exec", lambda self: 0)
    assert win.open_path("holiday.cr2")
    doc = win.current_doc()
    assert doc.name == "holiday.cr2"
    assert doc.size.width() == 8 and doc.size.height() == 6
    assert doc.layers[0].image.pixelColor(3, 2).green() == 250


def test_real_rawpy_rejects_non_raw_file(qapp, tmp_path):
    pytest.importorskip("rawpy")
    junk = tmp_path / "not_a_raw.nef"
    junk.write_bytes(b"definitely not a raw file")
    import rawpy

    with pytest.raises((rawpy.LibRawError, OSError, ValueError)):
        load_raw(str(junk))
    win = MainWindow()
    assert win.open_path(str(junk)) is False  # graceful status-bar failure


def test_raw_extensions_in_open_filter():
    from photoslop.opendialog import OPEN_FILTER

    for ext in ("*.nef", "*.cr3", "*.dng", "*.arw"):
        assert ext in OPEN_FILTER
    assert mainwindow is not None and io_raw is not None

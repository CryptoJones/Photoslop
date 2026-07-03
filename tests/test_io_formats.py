# SPDX-License-Identifier: Apache-2.0
"""AVIF + JPEG XL support (photoslop[formats], feature-detected)."""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from photoslop import cli, io_formats

HAVE_AVIF = io_formats.available("x.avif")
HAVE_JXL = io_formats.available("x.jxl")


def _grad(w=40, h=30):
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    for x in range(w // 2):
        for y in range(h):
            img.setPixelColor(x, y, QColor(200, 40, 40, 255))
    return img


@pytest.mark.parametrize("ext,have", [(".avif", HAVE_AVIF), (".jxl", HAVE_JXL)])
def test_round_trip_preserves_pixels_and_alpha(qapp, tmp_path, ext, have):
    if not have:
        pytest.skip(f"{ext} codec not installed")
    path = str(tmp_path / f"rt{ext}")
    assert io_formats.save_extra(_grad(), path, quality=95)
    back = io_formats.load_extra(path)
    assert back is not None and back.size() == QSize(40, 30)
    assert back.pixelColor(5, 5).red() > 150  # painted half survives
    assert back.pixelColor(35, 5).alpha() < 40  # transparent half stays clear


@pytest.mark.parametrize("ext,have", [(".avif", HAVE_AVIF), (".jxl", HAVE_JXL)])
def test_cli_output_and_input(qapp, tmp_path, ext, have):
    if not have:
        pytest.skip(f"{ext} codec not installed")
    out = str(tmp_path / f"cli{ext}")
    assert cli.main(["--new", "50x40", "--fill", "10,200,40",
                     "--output", out]) == 0
    # and back in as an input
    png = str(tmp_path / "back.png")
    assert cli.main([out, "--output", png]) == 0
    img = QImage(png)
    assert img.size() == QSize(50, 40)
    got = img.pixelColor(25, 20)
    # lossy codecs may drift a few values per channel
    assert abs(got.red() - 10) <= 6
    assert abs(got.green() - 200) <= 6
    assert abs(got.blue() - 40) <= 6


def test_quality_changes_avif_size(qapp, tmp_path):
    if not HAVE_AVIF:
        pytest.skip("avif codec not installed")
    # content-rich image: flat fills compress identically at any quality
    img = QImage(160, 120, QImage.Format.Format_ARGB32_Premultiplied)
    for x in range(160):
        for y in range(120):
            img.setPixelColor(x, y, QColor((x * 7 + y * 13) % 256,
                                           (x * 31) % 256, (y * 17) % 256))
    lo = io_formats.encode_extra(img, ".avif", quality=15)
    hi = io_formats.encode_extra(img, ".avif", quality=95)
    assert lo is not None and hi is not None and len(lo) < len(hi)


def test_missing_codec_is_a_clean_usage_error(qapp, tmp_path, monkeypatch):
    # simulate the extra not being installed
    monkeypatch.setattr(io_formats, "_checked", {".avif": False, ".jxl": False})
    out = str(tmp_path / "x.avif")
    with pytest.raises(SystemExit) as exc:
        cli.main(["--new", "20x20", "--output", out])
    assert exc.value.code == 2
    import os
    assert not os.path.exists(out)


def test_export_dialog_lists_formats_when_available(qapp):
    if not (HAVE_AVIF and HAVE_JXL):
        pytest.skip("formats extra not fully installed")
    from photoslop.document import Document
    from photoslop.exportdialog import ExportDialog

    doc = Document.new(QSize(20, 20), 72.0, "e", QColor(255, 255, 255))
    dlg = ExportDialog(doc)
    names = [dlg.format_box.itemText(i) for i in range(dlg.format_box.count())]
    assert "AVIF" in names and "JPEG XL" in names

    dlg.format_box.setCurrentText("AVIF")
    assert dlg.suggested_suffix() == ".avif"
    assert dlg.quality.isEnabled()  # lossy: quality slider live

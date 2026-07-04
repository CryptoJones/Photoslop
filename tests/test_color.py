# SPDX-License-Identifier: Apache-2.0
"""ICC color management (#108): assign/convert, viewport, proof, export."""

import os

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from photoslop import cli, color
from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora

CMYK_ICC = "/usr/share/color/icc/ghostscript/default_cmyk.icc"


def _doc(c=None):
    return Document.new(QSize(12, 10), 72.0, "icc", c or QColor(200, 60, 40))


def test_load_space_presets_files_and_errors(qapp, tmp_path):
    assert color.load_space("display-p3").isValid()
    assert color.load_space("srgb").isValid()
    icc = tmp_path / "srgb.icc"
    icc.write_bytes(bytes(color.load_space("srgb").iccProfile()))
    assert color.load_space(str(icc)).isValid()
    with pytest.raises(ValueError):
        color.load_space("nonexistent-space")
    bad = tmp_path / "junk.icc"
    bad.write_bytes(b"not a profile")
    with pytest.raises(ValueError):
        color.load_space(str(bad))


def test_assign_is_metadata_convert_moves_pixels(qapp):
    doc = _doc()
    before = doc.layers[0].image.pixelColor(5, 5)
    color.assign_profile(doc, color.load_space("display-p3"))
    assert doc.layers[0].image.pixelColor(5, 5) == before
    doc2 = _doc()
    color.convert_profile(doc2, color.load_space("display-p3"))
    after = doc2.layers[0].image.pixelColor(5, 5)
    assert (after.red(), after.green(), after.blue()) == (185, 71, 50)
    assert "P3" in color.describe(doc2.icc_space)


def test_viewport_transform_recovers_srgb_appearance(qapp):
    doc = _doc()
    color.convert_profile(doc, color.load_space("display-p3"))
    color.settings.update(display=color.load_space("srgb"),
                          proof=None, proof_on=False)
    try:
        assert color.viewport_active()
        view = color.apply_viewport(doc.flatten(), doc)
        c = view.pixelColor(5, 5)
        # 8-bit round trip may quantize by one count per channel
        assert abs(c.red() - 200) <= 1
        assert abs(c.green() - 60) <= 1
        assert abs(c.blue() - 40) <= 1
    finally:
        color.settings.update(display=None, proof=None, proof_on=False)
    assert not color.viewport_active()


def test_proof_simulation_round_trips(qapp):
    doc = _doc(QColor(0, 255, 0))  # saturated green: out of small gamuts
    flat = doc.flatten()
    proofed = color.proof_simulate(flat, doc, color.load_space("srgb"))
    assert proofed.size() == flat.size()  # sRGB->sRGB: lossless identity
    c = proofed.pixelColor(5, 5)
    assert (c.red(), c.green(), c.blue()) == (0, 255, 0)


def test_ora_round_trip_keeps_profile(qapp, tmp_path):
    doc = _doc()
    color.assign_profile(doc, color.load_space("adobe-rgb"))
    path = str(tmp_path / "icc.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert loaded.icc_space is not None and loaded.icc_space.isValid()
    assert "Adobe" in color.describe(loaded.icc_space)


def test_cli_convert_and_png_embeds_profile(qapp, tmp_path):
    src = str(tmp_path / "in.png")
    img = QImage(10, 8, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(200, 60, 40))
    img.save(src)
    out = str(tmp_path / "p3.png")
    assert cli.main([src, "--convert-profile", "display-p3",
                     "--output", out]) == 0
    loaded = QImage(out)
    assert loaded.colorSpace().isValid()
    assert "P3" in loaded.colorSpace().description()
    c = loaded.pixelColor(5, 4)
    assert (c.red(), c.green(), c.blue()) == (185, 71, 50)


def test_cli_assign_and_proof_flags(qapp, tmp_path):
    out = str(tmp_path / "a.png")
    assert cli.main(["--new", "10x8", "--fill", "10,200,60",
                     "--assign-profile", "display-p3",
                     "--proof", "srgb", "--output", out]) == 0
    assert QImage(out).colorSpace().isValid()
    with pytest.raises(SystemExit) as exc:
        cli.main(["--new", "8x8", "--assign-profile", "bogus",
                  "--output", str(tmp_path / "x.png")])
    assert exc.value.code == 2


@pytest.mark.skipif(not os.path.exists(CMYK_ICC),
                    reason="no ghostscript CMYK profile on this system")
def test_cmyk_export_writes_cmyk_jpeg(qapp, tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    out = str(tmp_path / "cmyk.jpg")
    assert cli.main(["--new", "16x12", "--fill", "200,60,40",
                     "--cmyk-out", CMYK_ICC, "--output", out]) == 0
    with Image.open(out) as im:
        assert im.mode == "CMYK"


def test_cmyk_export_needs_valid_target(qapp, tmp_path):
    doc = _doc()
    with pytest.raises(ValueError):
        color.cmyk_export(doc.flatten(), str(tmp_path / "x.png"),
                          "whatever.icc")

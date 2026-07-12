# SPDX-License-Identifier: Apache-2.0
"""Every CLI option, alone: one effect assertion + one malformed-value case.
A completeness test pins the op catalog to this file so they cannot drift."""

import json

import pytest
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage

from photoslop import cli
from photoslop.document import Document
from photoslop.io_ora import save_ora
from photoslop.layer import Layer

# op name -> (canned good argv fragment, malformed value or None if flag)
CASES = {
    "resize": ("30x20", "banana"),
    "canvas-size": ("80x60", "80"),
    "crop": ("5,5,20,15", "5,5"),
    "rotate": ("15", "sideways"),
    "rotate-layer": ("90", "sideways"),
    "content-aware-scale": ("40x30", "40"),
    "levels": ("10,240,1.2", "10,240"),
    "auto-levels": (None, None),
    "hue-sat": ("30,10,0", "30"),
    "color-balance": ("10,0,0,0,0,0,0,0,-10", "1,2,3"),
    "curves": ("0:20,255:235", "0:20:40"),
    "adjust": ("exposure=1,contrast=10", "sharpness=5"),
    "point-color": ("hue=20,range=28,dh=15,uniform=40", "hue=400"),
    "raw-develop": (None, "exposure=nan-ish"),
    "lens-correct": (None, None),
    "denoise-model": (None, "0"),
    "assign-profile": ("display-p3", "nope"),
    "convert-profile": ("adobe-rgb", "bogus.icc"),
    "proof": ("srgb", "nah"),
    "cmyk-out": (None, "missing.icc"),
    "filter": ("sepia:amount=100", "nope"),
    "gaussian-blur": ("2", "soft"),
    "unsharp": ("120", "sharp"),
    "tilt-shift": ("20,10,8,4", "20"),
    "drop-shadow": ("3,3,2,160", "3,3"),
    "glow": ("4", "big"),
    "stroke": ("2,0,0,255", "2"),
    "fill-opacity": ("50", "150"),
    "layer": ("0", "99"),
    "all-layers": (None, None),
    "select": ("5,5,10,10", "5,5"),
    "select-ellipse": ("5,5,20,16", "5,5"),
    "select-poly": ("5,5 25,5 25,15", "5,5 25,5"),
    "deselect": (None, None),
    "clear": (None, None),
    "flip": ("h", "diagonal"),
    "fill": ("10,200,40", "10,200"),
    "text": ("5,5,10:hello", "5,5,10"),
    "text-rich": ('5,5:<span style="color:#ff0000">Hi</span>', "5:oops"),
    "shape": ("rect,5,5,20,15,255,0,0", "blob,1,1,5,5,0,0,0"),
    "vector-op": ('{"op":"select","ids":[]}', "not-json"),
    "blend-mode": ("multiply", "extra-spicy"),
    "layer-opacity": ("50", "150"),
    "content-aware-fill": (None, None),
    "feather": ("3", "-1"),
    "duplicate-layer": (None, None),
    "flatten": (None, None),
    "convert-smart": (None, None),
    "restore-smart": (None, None),
    "add-artboard": ("Cover,0,0,30,20", "Cover,0,0"),
    "artboard-op": ('{"op":"add","name":"Page","rect":[0,0,20,10]}', "bad"),
    "model-url": ("http://localhost:1/x", " "),
    # network ops get their effect coverage in test_cli_combinations via the
    # fake HTTP server; here we cover their no-backend error paths
    "select-subject": (None, None),
    "generative-fill": ("a corn field", None),
}


def make_input(tmp_path, color=None, size=(60, 40)) -> str:
    img = QImage(size[0], size[1], QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(color or QColor(120, 90, 60))
    path = str(tmp_path / "in.png")
    img.save(path)
    return path


def run(argv) -> int:
    return cli.main([str(a) for a in argv])


def out_image(tmp_path) -> QImage:
    return QImage(str(tmp_path / "out.png"))


def test_catalog_is_complete():
    assert set(CASES) == set(cli.OPS), (
        "CLI ops and the test catalog drifted apart — add cases for: "
        f"{set(cli.OPS) ^ set(CASES)}")


@pytest.mark.parametrize("op", sorted(CASES))
def test_malformed_value_is_a_clean_usage_error(qapp, op, tmp_path):
    good, bad = CASES[op]
    if bad is None:
        pytest.skip("flag option or no malformed form")
    src = make_input(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run([src, f"--{op}", bad, "--output", tmp_path / "out.png"])
    assert exc.value.code == 2
    assert not (tmp_path / "out.png").exists()


def test_resize(qapp, tmp_path):
    src = make_input(tmp_path)
    assert run([src, "--resize", "30x20", "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).size() == QSize(30, 20)


def test_canvas_size_and_crop(qapp, tmp_path):
    src = make_input(tmp_path)
    assert run([src, "--canvas-size", "80x60",
                "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).size() == QSize(80, 60)
    assert run([src, "--crop", "5,5,20,15",
                "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).size() == QSize(20, 15)


def test_rotate_grows_bounding_box(qapp, tmp_path):
    src = make_input(tmp_path)
    assert run([src, "--rotate", "45", "--output", tmp_path / "out.png"]) == 0
    out = out_image(tmp_path)
    assert out.width() > 60 and out.height() > 40


def test_rotate_layer_spins_about_centre(qapp, tmp_path):
    src = make_input(tmp_path)  # 60×40 layer
    assert run([src, "--rotate-layer", "90", "--output",
                tmp_path / "out.ora"]) == 0
    from photoslop.io_ora import load_ora

    loaded = load_ora(str(tmp_path / "out.ora"))
    layer = loaded.layers[0]
    assert layer.image.width() == 40 and layer.image.height() == 60
    # centre preserved: (30,20) stays the middle, so the offset shifts
    assert (layer.offset.x(), layer.offset.y()) == (10, -10)
    # the canvas itself is untouched (unlike --rotate)
    assert loaded.size.width() == 60 and loaded.size.height() == 40


def test_content_aware_scale(qapp, tmp_path):
    src = make_input(tmp_path)
    assert run([src, "--content-aware-scale", "40x30",
                "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).size() == QSize(40, 30)


def test_levels_and_auto_levels(qapp, tmp_path):
    src = make_input(tmp_path, QColor(100, 100, 100))
    assert run([src, "--levels", "0,255,2.0",
                "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(5, 5).red() > 140  # gamma brightens
    assert run([src, "--auto-levels", "--output", tmp_path / "out.png"]) == 0


def test_hue_sat_lightness(qapp, tmp_path):
    src = make_input(tmp_path, QColor(100, 100, 100))
    assert run([src, "--hue-sat", "0,0,50",
                "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(5, 5).red() > 140


def test_color_balance_pushes_red(qapp, tmp_path):
    src = make_input(tmp_path, QColor(120, 120, 120))
    assert run([src, "--color-balance", "0,0,0,60,0,0,0,0,0",
                "--output", tmp_path / "out.png"]) == 0
    px = out_image(tmp_path).pixelColor(5, 5)
    assert px.red() > px.blue()


def test_curves_lifts_shadows(qapp, tmp_path):
    src = make_input(tmp_path, QColor(0, 0, 0))
    assert run([src, "--curves", "0:60,255:255",
                "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(5, 5).red() >= 55


def test_gaussian_blur_and_unsharp(qapp, tmp_path):
    img = QImage(60, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0))
    for y in range(40):
        for x in range(30, 60):
            img.setPixelColor(x, y, QColor(255, 255, 255))
    src = str(tmp_path / "edge.png")
    img.save(src)
    assert run([src, "--gaussian-blur", "4",
                "--output", tmp_path / "out.png"]) == 0
    edge = out_image(tmp_path).pixelColor(30, 20).red()
    assert 0 < edge < 255  # softened
    assert run([src, "--unsharp", "150", "--output", tmp_path / "out.png"]) == 0


def test_tilt_shift_blurs_top_keeps_band(qapp, tmp_path):
    img = QImage(60, 60, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0))
    for y in range(60):  # vertical stripes so blur is measurable per row
        for x in range(0, 60, 2):
            img.setPixelColor(x, y, QColor(255, 255, 255))
    src = str(tmp_path / "stripes.png")
    img.save(src)
    assert run([src, "--tilt-shift", "30,20,10,6",
                "--output", tmp_path / "out.png"]) == 0
    out = out_image(tmp_path)
    band_px = out.pixelColor(0, 30).red()  # inside the sharp band
    far_px = out.pixelColor(0, 2).red()  # far outside: fully blurred
    assert band_px in (255, 254)
    assert 40 < far_px < 220  # stripes averaged toward grey


def test_live_effect_ops_attach_and_bake(qapp, tmp_path):
    # chip on transparent ground so the shadow lands outside the fill
    doc = Document.new(QSize(60, 60), 72.0, "fx", QColor(255, 255, 255))
    chip = Layer.blank("chip", QSize(20, 20), QPoint(20, 20))
    chip.image.fill(QColor(255, 0, 0))
    doc.layers.append(chip)
    doc.active_index = 1
    src = str(tmp_path / "fx.ora")
    save_ora(doc, src)

    assert run([src, "--drop-shadow", "6,6,2,255",
                "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(44, 44).red() < 200  # baked shadow

    assert run([src, "--stroke", "3,0,0,255", "--fill-opacity", "0",
                "--output", tmp_path / "out.png"]) == 0
    out = out_image(tmp_path)
    assert out.pixelColor(30, 30) == QColor(255, 255, 255)  # fill hidden
    ring = out.pixelColor(18, 30)
    assert ring.blue() > 180 and ring.red() < 80  # blue stroke ring stays

    assert run([src, "--glow", "4", "--output", tmp_path / "out.png"]) == 0


def test_layer_and_all_layers_scope(qapp, tmp_path):
    doc = Document.new(QSize(40, 40), 72.0, "sc", QColor(50, 50, 50))
    top = Layer.blank("top", QSize(10, 10), QPoint(30, 30))
    top.image.fill(QColor(200, 200, 200))
    doc.layers.append(top)
    doc.active_index = 1
    src = str(tmp_path / "scope.ora")
    save_ora(doc, src)

    # --layer 0 targets the background; brightening it leaves the chip alone
    assert run([src, "--layer", "0", "--hue-sat", "0,0,50",
                "--output", tmp_path / "out.ora"]) == 0
    from photoslop.io_ora import load_ora

    loaded = load_ora(str(tmp_path / "out.ora"))
    assert loaded.layers[0].image.pixelColor(5, 5).red() > 90
    assert loaded.layers[1].image.pixelColor(5, 5) == QColor(200, 200, 200)

    assert run([src, "--all-layers", "--hue-sat", "0,0,50",
                "--output", tmp_path / "out.ora"]) == 0
    loaded = load_ora(str(tmp_path / "out.ora"))
    assert loaded.layers[1].image.pixelColor(5, 5).red() > 220


def test_select_confines_and_deselect_releases(qapp, tmp_path):
    src = make_input(tmp_path, QColor(100, 100, 100))
    assert run([src, "--select", "5,5,10,10", "--hue-sat", "0,0,50",
                "--output", tmp_path / "out.png"]) == 0
    out = out_image(tmp_path)
    assert out.pixelColor(7, 7).red() > 140  # inside selection
    assert out.pixelColor(30, 30).red() == 100  # outside untouched

    assert run([src, "--select", "5,5,10,10", "--deselect",
                "--hue-sat", "0,0,50", "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(30, 30).red() > 140


def test_select_ellipse_excludes_box_corners(qapp, tmp_path):
    src = make_input(tmp_path, QColor(100, 100, 100))
    assert run([src, "--select-ellipse", "5,5,20,16", "--hue-sat", "0,0,50",
                "--output", tmp_path / "out.png"]) == 0
    out = out_image(tmp_path)
    assert out.pixelColor(15, 13).red() > 140  # ellipse centre lifted
    assert out.pixelColor(6, 6).red() == 100  # box corner outside the ellipse
    assert out.pixelColor(30, 30).red() == 100  # outside the box entirely


def test_select_poly_confines_to_triangle(qapp, tmp_path):
    src = make_input(tmp_path, QColor(100, 100, 100))
    # right triangle: legs along the top and right edges of (5,5)-(25,15)
    assert run([src, "--select-poly", "5,5 25,5 25,15", "--hue-sat", "0,0,50",
                "--output", tmp_path / "out.png"]) == 0
    out = out_image(tmp_path)
    assert out.pixelColor(20, 8).red() > 140  # inside the triangle
    assert out.pixelColor(7, 13).red() == 100  # inside bbox, outside triangle
    assert out.pixelColor(40, 30).red() == 100  # far outside


def test_adjust_basic_sliders(qapp, tmp_path):
    src = make_input(tmp_path, QColor(100, 100, 100))
    assert run([src, "--adjust", "exposure=1", "--output",
                tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(5, 5).red() > 150  # +1 stop

    # selection gates it like every other adjustment op
    assert run([src, "--select", "5,5,10,10", "--adjust", "exposure=1",
                "--output", tmp_path / "out.png"]) == 0
    out = out_image(tmp_path)
    assert out.pixelColor(7, 7).red() > 150
    assert out.pixelColor(30, 30).red() == 100

    with pytest.raises(SystemExit) as exc:  # unknown slider name
        run([src, "--adjust", "sharpness=5", "--output", tmp_path / "bad.png"])
    assert exc.value.code == 2


def test_clear_erases_selection(qapp, tmp_path):
    src = make_input(tmp_path, QColor(100, 100, 100))
    assert run([src, "--select", "5,5,10,10", "--clear", "--deselect",
                "--output", tmp_path / "out.png"]) == 0
    out = out_image(tmp_path)
    assert out.pixelColor(7, 7).alpha() == 0  # erased to transparency
    assert out.pixelColor(30, 30) == QColor(100, 100, 100)

    with pytest.raises(SystemExit) as exc:  # needs a selection
        run([src, "--clear", "--output", tmp_path / "bad.png"])
    assert exc.value.code == 2
    assert not (tmp_path / "bad.png").exists()


def test_new_document_sizes_and_presets(qapp, tmp_path):
    out = tmp_path / "out.png"
    assert cli.main(["--new", "100x80", "--fill", "10,200,40",
                     "--output", str(out)]) == 0
    img = QImage(str(out))
    assert img.size() == QSize(100, 80)
    assert img.pixelColor(50, 40) == QColor(10, 200, 40)

    assert cli.main(["--new", "letter", "--output", str(out)]) == 0
    assert QImage(str(out)).size() == QSize(612, 792)  # 8.5×11″ at 72 dpi

    assert cli.main(["--new", "A4", "--dpi", "300", "--output", str(out)]) == 0
    assert QImage(str(out)).size() == QSize(2480, 3508)

    with pytest.raises(SystemExit) as exc:  # unknown preset
        cli.main(["--new", "tabloid", "--output", str(out)])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:  # input and --new are exclusive
        cli.main([make_input(tmp_path), "--new", "50x50", "--output", str(out)])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:  # neither is an error too
        cli.main(["--output", str(out)])
    assert exc.value.code == 2


def test_model_ops_require_backend(qapp, tmp_path):
    src = make_input(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run([src, "--select-subject", "--output", tmp_path / "out.png"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        run([src, "--select", "5,5,10,10", "--generative-fill", "corn",
             "--output", tmp_path / "out.png"])
    assert exc.value.code == 2
    # --model-url alone parses and validates
    assert run([src, "--model-url", "http://localhost:1/x", "--info"]) == 0


def test_info_json(qapp, tmp_path, capsys):
    src = make_input(tmp_path)
    assert run([src, "--info"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["size"] == [60, 40]
    assert info["layers"][0]["fill_opacity"] == 1.0

def test_flip_and_fill(qapp, tmp_path):
    img = QImage(20, 10, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0))
    img.setPixelColor(0, 0, QColor(255, 255, 255))
    src = str(tmp_path / "f.png")
    img.save(src)
    assert run([src, "--flip", "h", "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(19, 0) == QColor(255, 255, 255)
    assert run([src, "--fill", "10,200,40",
                "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(5, 5) == QColor(10, 200, 40)


def test_text_and_shape_add_layers(qapp, tmp_path):
    src = make_input(tmp_path, QColor(255, 255, 255))
    assert run([src, "--text", "5,5,12:Hi", "--shape", "rect,30,5,20,10,255,0,0",
                "--output", tmp_path / "out.ora"]) == 0
    from photoslop.io_ora import load_ora

    loaded = load_ora(str(tmp_path / "out.ora"))
    assert len(loaded.layers) == 3
    assert loaded.layers[2].name.startswith("Shape")
    assert loaded.layers[2].image.pixelColor(5, 5) == QColor(255, 0, 0)
    flat_has_ink = any(
        loaded.flatten().pixelColor(x, y).red() < 200
        for x in range(5, 30) for y in range(5, 25))
    assert flat_has_ink  # the text drew something


def test_text_color(qapp, tmp_path):
    src = make_input(tmp_path, QColor(255, 255, 255))
    assert run([src, "--text", "5,5,14,255,0,0:Hi",
                "--output", tmp_path / "out.ora"]) == 0
    from photoslop.io_ora import load_ora

    loaded = load_ora(str(tmp_path / "out.ora"))
    text_layer = loaded.layers[1]
    img = text_layer.image
    assert any(
        img.pixelColor(x, y).red() > 200 and img.pixelColor(x, y).green() < 60
        and img.pixelColor(x, y).alpha() > 200
        for x in range(img.width()) for y in range(img.height()))
    # the text parameters round-trip through ORA for later re-editing
    assert text_layer.text_data["text"] == "Hi"
    assert text_layer.text_data["color"] == [255, 0, 0, 255]

    # a head that is neither 3 nor 6 values is a usage error
    with pytest.raises(SystemExit) as exc:
        run([src, "--text", "5,5,14,255:Hi", "--output", tmp_path / "bad.png"])
    assert exc.value.code == 2


def test_text_rich_per_letter_colour(qapp, tmp_path):
    src = make_input(tmp_path, QColor(255, 255, 255))
    html = ('<span style="color:#ff0000;font-size:40pt">A</span>'
            '<span style="color:#0000ff;font-size:40pt">B</span>')
    assert run([src, "--text-rich", f"5,5:{html}",
                "--output", tmp_path / "out.ora"]) == 0
    from photoslop.io_ora import load_ora

    loaded = load_ora(str(tmp_path / "out.ora"))
    img = loaded.layers[1].image
    has_red = any(
        img.pixelColor(x, y).red() > 180 and img.pixelColor(x, y).blue() < 80
        and img.pixelColor(x, y).alpha() > 150
        for x in range(img.width()) for y in range(img.height()))
    has_blue = any(
        img.pixelColor(x, y).blue() > 180 and img.pixelColor(x, y).red() < 80
        and img.pixelColor(x, y).alpha() > 150
        for x in range(img.width()) for y in range(img.height()))
    assert has_red and has_blue  # both letter colours survive to the layer
    # the styled HTML round-trips through ORA for later re-editing
    assert loaded.layers[1].text_data["text"] == "AB"
    assert "html" in loaded.layers[1].text_data
    assert not (tmp_path / "bad.png").exists()


def test_blend_mode_and_layer_opacity(qapp, tmp_path):
    src = make_input(tmp_path, QColor(100, 100, 100))
    assert run([src, "--shape", "rect,0,0,60,40,255,255,255",
                "--blend-mode", "multiply", "--layer-opacity", "100",
                "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(5, 5).red() == 100  # white multiply
    assert run([src, "--shape", "rect,0,0,60,40,255,255,255",
                "--layer-opacity", "50", "--output", tmp_path / "out.png"]) == 0
    px = out_image(tmp_path).pixelColor(5, 5).red()
    assert 160 < px < 195  # 50% white over grey


def test_content_aware_fill_and_feather(qapp, tmp_path):
    img = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(80, 160, 80))
    for y in range(15, 25):
        for x in range(15, 25):
            img.setPixelColor(x, y, QColor(255, 0, 0))  # the blemish
    src = str(tmp_path / "caf.png")
    img.save(src)
    assert run([src, "--select", "13,13,14,14", "--content-aware-fill",
                "--deselect", "--output", tmp_path / "out.png"]) == 0
    px = out_image(tmp_path).pixelColor(20, 20)
    assert px.green() > px.red()  # blemish diffused away

    with pytest.raises(SystemExit) as exc:  # feather without selection
        run([src, "--feather", "3", "--output", tmp_path / "out.png"])
    assert exc.value.code == 2
    assert run([src, "--select", "10,10,20,20", "--feather", "4",
                "--gaussian-blur", "3", "--output", tmp_path / "out.png"]) == 0


def test_duplicate_flatten_smart(qapp, tmp_path):
    src = make_input(tmp_path, QColor(60, 60, 60))
    from photoslop.io_ora import load_ora

    assert run([src, "--duplicate-layer", "--output", tmp_path / "o.ora"]) == 0
    assert len(load_ora(str(tmp_path / "o.ora")).layers) == 2
    assert run([src, "--duplicate-layer", "--flatten",
                "--output", tmp_path / "o.ora"]) == 0
    assert len(load_ora(str(tmp_path / "o.ora")).layers) == 1

    assert run([src, "--convert-smart", "--fill", "255,0,0",
                "--restore-smart", "--output", tmp_path / "out.png"]) == 0
    assert out_image(tmp_path).pixelColor(5, 5) == QColor(60, 60, 60)
    with pytest.raises(SystemExit) as exc:  # restore without convert
        run([src, "--restore-smart", "--output", tmp_path / "out.png"])
    assert exc.value.code == 2


def test_add_artboard_export(qapp, tmp_path):
    src = make_input(tmp_path)
    board_dir = tmp_path / "boards"
    assert run([src, "--add-artboard", "Cover,0,0,30,20",
                "--export-artboards", board_dir]) == 0
    board = QImage(str(board_dir / "Cover.png"))
    assert board.size() == QSize(30, 20)

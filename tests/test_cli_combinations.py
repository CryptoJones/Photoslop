# SPDX-License-Identifier: Apache-2.0
"""Combinatorial CLI coverage: every ordered pair of operations runs end to
end, order-sensitive pairs are asserted on pixels, and one kitchen-sink
pipeline chains an op from every group. Model ops pair against a live local
HTTP server. Full N-way permutation space is factorial and out of scope —
pairwise + ordered cases is the honest sweep."""

import itertools
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PySide6.QtGui import QColor, QImage

from photoslop import cli
from photoslop.modeladapter import image_to_png_b64, png_b64_to_image

# canned pipeline fragments, chosen to be valid on the 60x40 grey fixture
# regardless of what ran before them (sizes stay >= 12px in every pair)
PAIR_ARGS = {
    "resize": ["--resize", "48x32"],
    "canvas-size": ["--canvas-size", "64x44"],
    "crop": ["--crop", "2,2,40,28"],
    "rotate": ["--rotate", "10"],
    "rotate-layer": ["--rotate-layer", "90"],
    "content-aware-scale": ["--content-aware-scale", "36x26"],
    "levels": ["--levels", "10,240,1.2"],
    "auto-levels": ["--auto-levels"],
    "hue-sat": ["--hue-sat", "30,10,5"],
    "color-balance": ["--color-balance", "10,0,0,0,5,0,0,0,-10"],
    "curves": ["--curves", "0:10,255:245"],
    "gaussian-blur": ["--gaussian-blur", "2"],
    "unsharp": ["--unsharp", "120"],
    "tilt-shift": ["--tilt-shift", "16,8,6,3"],
    "drop-shadow": ["--drop-shadow", "3,3,2,160"],
    "glow": ["--glow", "3"],
    "stroke": ["--stroke", "2,0,0,255"],
    "fill-opacity": ["--fill-opacity", "60"],
    "layer": ["--layer", "0"],
    "all-layers": ["--all-layers"],
    "select": ["--select", "2,2,8,8"],
    "select-ellipse": ["--select-ellipse", "2,2,10,10"],
    "select-poly": ["--select-poly", "2,2 12,2 12,12"],
    "deselect": ["--deselect"],
    "clear": ["--select", "3,3,6,6", "--clear", "--deselect"],
    "adjust": ["--adjust", "exposure=0.4,contrast=5"],
    "point-color": ["--point-color", "hue=20,range=40,ds=25"],
    "assign-profile": ["--assign-profile", "display-p3"],
    "convert-profile": ["--convert-profile", "adobe-rgb"],
    "proof": ["--proof", "srgb"],
    "filter": ["--filter", "pixelate:size=4"],
    "flip": ["--flip", "h"],
    "fill": ["--fill", "10,200,40"],
    "text": ["--text", "2,2,8,0,120,255:Hi"],
    "shape": ["--shape", "rect,2,2,10,8,255,0,0"],
    "blend-mode": ["--blend-mode", "multiply"],
    "layer-opacity": ["--layer-opacity", "70"],
    "content-aware-fill": ["--select", "3,3,6,6", "--content-aware-fill",
                           "--deselect"],
    "feather": ["--select", "2,2,10,10", "--feather", "2"],
    "duplicate-layer": ["--duplicate-layer"],
    "flatten": ["--flatten"],
    "convert-smart": ["--convert-smart"],
    "restore-smart": ["--convert-smart", "--restore-smart"],
    "add-artboard": ["--add-artboard", "B,0,0,10,10"],
}
# ops excluded from the pair sweep: need a backend or an on-disk
# ICC profile the harness cannot assume (cmyk-out gets its own
# skip-if-missing effect test in test_color.py)
NETWORK_OPS = ("model-url", "select-subject", "generative-fill",
               "cmyk-out")


def test_pair_catalog_covers_all_non_network_ops():
    assert set(PAIR_ARGS) == set(cli.OPS) - set(NETWORK_OPS)


def make_input(tmp_path) -> str:
    img = QImage(60, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(120, 90, 60))
    path = str(tmp_path / "in.png")
    img.save(path)
    return path


@pytest.mark.parametrize(
    "first,second",
    list(itertools.permutations(sorted(PAIR_ARGS), 2)),
    ids=lambda v: v if isinstance(v, str) else str(v))
def test_every_ordered_pair_runs(qapp, tmp_path, first, second):
    src = make_input(tmp_path)
    out = tmp_path / "out.png"
    code = cli.main([src, *PAIR_ARGS[first], *PAIR_ARGS[second],
                     "--output", str(out)])
    assert code == 0
    img = QImage(str(out))
    assert not img.isNull()
    assert img.width() >= 12 and img.height() >= 12


def test_order_sensitivity_resize_vs_blur(qapp, tmp_path):
    # blur radius acts on different pixel scales before/after resize —
    # the two orders must not produce identical images
    img = QImage(60, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0))
    for y in range(40):
        for x in range(30, 60):
            img.setPixelColor(x, y, QColor(255, 255, 255))
    src = str(tmp_path / "edge.png")
    img.save(src)

    a, b = tmp_path / "a.png", tmp_path / "b.png"
    assert cli.main([src, "--resize", "30x20", "--gaussian-blur", "3",
                     "--output", str(a)]) == 0
    assert cli.main([src, "--gaussian-blur", "3", "--resize", "30x20",
                     "--output", str(b)]) == 0
    ia, ib = QImage(str(a)), QImage(str(b))
    assert ia.size() == ib.size()
    assert any(ia.pixel(x, 10) != ib.pixel(x, 10) for x in range(30))


def test_order_sensitivity_crop_vs_effect(qapp, tmp_path):
    src = make_input(tmp_path)
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    # levels-then-crop == crop-then-levels (both whole-layer), but
    # select-then-levels ≠ levels-then-select: the selection gates only ops
    # that FOLLOW it in the pipeline
    assert cli.main([src, "--select", "2,2,8,8", "--hue-sat", "0,0,50",
                     "--output", str(a)]) == 0
    assert cli.main([src, "--hue-sat", "0,0,50", "--select", "2,2,8,8",
                     "--output", str(b)]) == 0
    ia, ib = QImage(str(a)), QImage(str(b))
    assert ia.pixelColor(30, 30).red() == 120  # gated: outside untouched
    assert ib.pixelColor(30, 30).red() > 160  # ungated: everything lifted


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        img = png_b64_to_image(body["image"])
        if self.path.endswith("/select-subject"):
            mask = QImage(img.size(), QImage.Format.Format_Grayscale8)
            mask.fill(0)
            for y in range(5, 15):
                for x in range(5, 25):
                    mask.setPixel(x, y, 0xFFFFFF)
            out = {"mask": image_to_png_b64(mask)}
        else:
            filled = QImage(img.size(),
                            QImage.Format.Format_ARGB32_Premultiplied)
            filled.fill(QColor(10, 200, 40))
            out = {"image": image_to_png_b64(filled)}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def model_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/photoslop"
    server.shutdown()
    server.server_close()


def test_model_op_pairs_against_live_server(qapp, tmp_path, model_server):
    src = make_input(tmp_path)
    out = tmp_path / "out.png"
    # select-subject then generative-fill: fill lands only in the subject
    assert cli.main([src, "--model-url", model_server, "--select-subject",
                     "--generative-fill", "a corn field",
                     "--output", str(out)]) == 0
    img = QImage(str(out))
    assert img.pixelColor(10, 10) == QColor(10, 200, 40)  # inside subject
    assert img.pixelColor(40, 30) == QColor(120, 90, 60)  # outside untouched

    # model ops compose with ordinary ops
    assert cli.main([src, "--resize", "40x30", "--model-url", model_server,
                     "--select-subject", "--gaussian-blur", "2",
                     "--deselect", "--levels", "10,240,1.1",
                     "--output", str(out)]) == 0
    assert QImage(str(out)).width() == 40


def test_kitchen_sink_pipeline(qapp, tmp_path, model_server):
    src = make_input(tmp_path)
    out = tmp_path / "out.png"
    code = cli.main([
        src,
        "--canvas-size", "70x50",
        "--rotate", "5",
        "--auto-levels",
        "--curves", "0:8,255:250",
        "--hue-sat", "10,5,0",
        "--color-balance", "5,0,0,0,0,0,0,0,-5",
        "--select", "5,5,20,20",
        "--gaussian-blur", "2",
        "--deselect",
        "--unsharp", "110",
        "--tilt-shift", "20,10,6,3",
        "--model-url", model_server,
        "--select-subject",
        "--generative-fill", "corn",
        "--deselect",
        "--drop-shadow", "3,3,2,140",
        "--stroke", "1,255,255,255",
        "--fill-opacity", "80",
        "--resize", "50x36",
        "--output", str(out),
    ])
    assert code == 0
    img = QImage(str(out))
    assert img.size().width() == 50 and img.size().height() == 36

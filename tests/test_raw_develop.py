# SPDX-License-Identifier: Apache-2.0
"""Raw develop + lens + model denoise (#112). The rawpy decode is mocked
with a deterministic 16-bit array so the full DD-007 pipeline (16-bit
transient in, 8-bit layer out) is tested without camera files."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from photoslop import cli, lens
from photoslop.io_raw import DEVELOP_FIELDS, develop_raw, tone_map, wb_multipliers
from photoslop.modeladapter import image_to_png_b64, png_b64_to_image


class _FakeRaw:
    def __init__(self, path):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def postprocess(self, **kwargs):
        self.kwargs = kwargs
        _FakeRaw.last_kwargs = kwargs
        # mid-gray plus a bright quadrant, 16-bit
        arr = np.full((20, 30, 3), 20000, dtype=np.uint16)
        arr[:10, :15] = 60000
        if "exp_shift" in kwargs:
            arr = np.clip(arr.astype(np.float64) * kwargs["exp_shift"], 0, 65535).astype(np.uint16)
        return arr


@pytest.fixture
def fake_rawpy(monkeypatch, tmp_path):
    import sys
    import types

    mod = types.SimpleNamespace(imread=_FakeRaw)
    monkeypatch.setitem(sys.modules, "rawpy", mod)
    raw = tmp_path / "shot.dng"
    raw.write_bytes(b"fake raw bytes")
    return str(raw)


def test_wb_multipliers_directions(qapp):
    warm, cool = wb_multipliers(8000, 0), wb_multipliers(3500, 0)
    assert warm[0] > cool[0] and warm[2] < cool[2]
    assert wb_multipliers(6500, 60)[1] < wb_multipliers(6500, 0)[1]


def test_tone_map_monotone_and_bounded(qapp):
    hi = np.full((2, 2, 3), 0.9, np.float32)
    lo = np.full((2, 2, 3), 0.1, np.float32)
    assert tone_map(hi, -50, 0)[0, 0, 0] < 0.9  # recovery pulls down
    assert tone_map(lo, 0, 50)[0, 0, 0] > 0.1  # shadow lift
    assert tone_map(hi, 100, 100).max() <= 1.0  # bounded


def test_develop_pipeline_16bit_in_8bit_out(qapp, fake_rawpy):
    img = develop_raw(fake_rawpy, exposure=1.0, temp=6500, tint=10, highlights=-40, shadows=20)
    assert img.format() == QImage.Format.Format_ARGB32_Premultiplied
    assert (img.width(), img.height()) == (30, 20)
    kwargs = _FakeRaw.last_kwargs
    assert kwargs["output_bps"] == 16  # DD-007 transient depth
    assert kwargs["exp_shift"] == 2.0  # +1 EV
    assert "user_wb" in kwargs  # temp engaged
    bright = img.pixelColor(5, 5)
    gray = img.pixelColor(25, 15)
    assert bright.red() > gray.red()


def test_cli_raw_develop_and_errors(qapp, fake_rawpy, tmp_path, monkeypatch):
    from photoslop.io_raw import RAW_EXTENSIONS

    assert fake_rawpy.endswith(".dng") and ".dng" in RAW_EXTENSIONS
    out = str(tmp_path / "dev.png")
    monkeypatch.setattr("photoslop.io_raw.load_raw", lambda p: develop_raw(p))
    assert (
        cli.main([fake_rawpy, "--raw-develop", "exposure=1,highlights=-30", "--output", out]) == 0
    )
    assert QImage(out).width() == 30
    # non-raw input is a clean usage error
    png = str(tmp_path / "x.png")
    QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied).save(png)
    with pytest.raises(SystemExit) as exc:
        cli.main([png, "--raw-develop", "exposure=1", "--output", str(tmp_path / "n.png")])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc2:
        cli.main([fake_rawpy, "--raw-develop", "exposure=99", "--output", str(tmp_path / "n2.png")])
    assert exc2.value.code == 2


def test_develop_fields_and_dialog_values(qapp, fake_rawpy):
    from photoslop.rawdialog import RawDevelopDialog

    dlg = RawDevelopDialog(fake_rawpy)
    dlg._debounce.stop()
    assert set(dlg.values()) == set(DEVELOP_FIELDS)
    dlg._sliders["exposure"].setValue(150)  # scaled x100
    assert dlg.values()["exposure"] == 1.5
    dlg._reset()
    assert dlg.values()["exposure"] == 0.0


def test_lens_gating_and_errors(qapp, tmp_path, monkeypatch):
    img = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(1, 2, 3))
    monkeypatch.setattr(lens, "lens_available", lambda: False)
    with pytest.raises(ValueError, match="photoslop\\[lens\\]"):
        lens.correct_lens(img, "whatever.jpg")


@pytest.mark.skipif(not lens.lens_available(), reason="photoslop[lens] not installed")
def test_lens_no_exif_is_clean_error(qapp, tmp_path):
    img = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(1, 2, 3))
    png = str(tmp_path / "noexif.png")
    img.save(png)
    with pytest.raises(ValueError, match="no camera EXIF"):
        lens.correct_lens(img, png)


class _DenoiseHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path.endswith("/denoise")
        assert 1 <= body["strength"] <= 100
        img = png_b64_to_image(body["image"])
        clean = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
        clean.fill(QColor(7, 7, 200))
        data = json.dumps({"image": image_to_png_b64(clean)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_cli_denoise_model_against_live_server(qapp, tmp_path):
    server = HTTPServer(("127.0.0.1", 0), _DenoiseHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/photoslop"
        out = str(tmp_path / "dn.png")
        assert (
            cli.main(
                [
                    "--new",
                    "12x10",
                    "--fill",
                    "90,90,90",
                    "--model-url",
                    url,
                    "--denoise-model",
                    "40",
                    "--output",
                    out,
                ]
            )
            == 0
        )
        assert QImage(out).pixelColor(6, 5) == QColor(7, 7, 200)
        with pytest.raises(SystemExit) as exc:
            cli.main(
                [
                    "--new",
                    "8x8",
                    "--model-url",
                    url,
                    "--denoise-model",
                    "500",
                    "--output",
                    str(tmp_path / "n.png"),
                ]
            )
        assert exc.value.code == 2
    finally:
        server.shutdown()
        server.server_close()

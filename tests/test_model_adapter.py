# SPDX-License-Identifier: Apache-2.0
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from PySide6.QtCore import QSettings, QSize
from PySide6.QtGui import QColor, QImage

from photoslop import modeladapter
from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.modeladapter import (
    SELECT_SUBJECT,
    HttpModelAdapter,
    ModelAdapter,
    create_adapter,
    image_to_png_b64,
    png_b64_to_image,
    register_adapter,
)


def subject_mask(w=40, h=30) -> QImage:
    mask = QImage(w, h, QImage.Format.Format_Grayscale8)
    mask.fill(0)
    for y in range(10, 20):
        for x in range(5, 25):
            mask.setPixel(x, y, 0xFFFFFF)
    return mask


class FakeAdapter(ModelAdapter):
    name = "fake"
    label = "Fake test adapter"

    def capabilities(self):
        return frozenset({SELECT_SUBJECT})

    def select_subject(self, image):
        return subject_mask(image.width(), image.height())


def test_b64_round_trip(qapp):
    img = QImage(8, 6, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(10, 200, 30))
    back = png_b64_to_image(image_to_png_b64(img))
    assert back.size() == img.size()
    assert back.pixelColor(4, 3).green() == 200


def test_registry_and_select_subject_flow(qapp):
    register_adapter(FakeAdapter)
    assert create_adapter("fake", {}) is not None
    assert create_adapter("http", {}) is None  # http needs a URL
    assert create_adapter("nope", {}) is None

    win = MainWindow()
    win.add_document(Document.new(QSize(40, 30), 72.0, "ms",
                                  QColor(255, 255, 255)))
    doc = win.current_doc()

    win.action_select_subject()  # unconfigured: clean refusal
    assert doc.selection is None

    QSettings("CryptoJones", "Photoslop").setValue("model/adapter", "fake")
    win.action_select_subject()
    bounds = doc.selection_bounds()
    assert bounds is not None
    assert (bounds.x(), bounds.y()) == (5, 10)
    assert (bounds.width(), bounds.height()) == (20, 10)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert "image" in body
        if self.path.endswith("/select-subject"):
            out = {"mask": image_to_png_b64(subject_mask())}
        else:
            img = png_b64_to_image(body["image"])
            img.fill(QColor(1, 2, 3))
            out = {"image": image_to_png_b64(img)}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_http_adapter_against_local_server(qapp):
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/photoslop"
        adapter = HttpModelAdapter(base, timeout=10)
        img = QImage(40, 30, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(9, 9, 9))
        mask = adapter.select_subject(img)
        assert mask.pixelColor(10, 15).red() > 200
        filled = adapter.generative_fill(img, mask, "a corn field")
        assert filled.pixelColor(0, 0) == QColor(1, 2, 3)
    finally:
        server.shutdown()
        server.server_close()
    assert modeladapter is not None

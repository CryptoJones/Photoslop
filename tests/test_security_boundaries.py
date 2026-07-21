# SPDX-License-Identifier: Apache-2.0
"""Adversarial coverage for parser, allocation, plugin, model, and MCP gates."""

import base64
import json
import zipfile
from email.message import Message

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from photoslop import gmicpack, modeladapter, server
from photoslop.document import Document
from photoslop.filters import available_filters, register_filter
from photoslop.io_ora import load_ora, save_ora
from photoslop.io_svg import _commands, load_svg
from photoslop.modeladapter import (
    MAX_MODEL_RESPONSE,
    HttpModelAdapter,
    png_b64_to_image,
)
from photoslop.resources import (
    ResourceBudget,
    ResourceLimitError,
    validate_dimensions,
)


def test_geometry_hard_and_working_set_limits_are_distinct():
    budget = ResourceBudget(
        max_dimension=100,
        max_pixels=10_000,
        max_working_bytes=100,
    )
    with pytest.raises(ResourceLimitError, match="maximum dimension"):
        validate_dimensions(101, 1, budget=budget)
    with pytest.raises(ResourceLimitError, match="working set"):
        validate_dimensions(10, 10, buffers=2, budget=budget)
    validate_dimensions(10, 10, buffers=2, budget=budget, allow_large=True)
    with pytest.raises(ResourceLimitError):
        Document(QSize(32_769, 1))


def _minimal_stack() -> bytes:
    return b'<?xml version="1.0"?><image w="8" h="8"><stack/></image>'


def test_ora_rejects_traversal_members(tmp_path):
    path = tmp_path / "traversal.ora"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("stack.xml", _minimal_stack())
        archive.writestr("../outside", b"x")
    with pytest.raises(ResourceLimitError, match="unsafe member"):
        load_ora(str(path))


def test_ora_rejects_suspicious_compression_ratio(tmp_path):
    path = tmp_path / "bomb.ora"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("stack.xml", _minimal_stack())
        archive.writestr("data/bomb", b"0" * (2 << 20))
    with pytest.raises(ResourceLimitError, match="compression ratio"):
        load_ora(str(path))


def test_imported_smart_filter_recipes_are_untrusted(qapp, tmp_path):
    doc = Document.new(QSize(8, 8))
    doc.active_layer.source = QImage(doc.active_layer.image)
    doc.active_layer.smart_filters = [("filter", "sepia", (("amount", 80),))]
    path = tmp_path / "recipe.ora"
    save_ora(doc, str(path))
    loaded = load_ora(str(path))
    assert loaded.active_layer.smart_filters
    assert loaded.active_layer.smart_filters_trusted is False


def test_svg_rejects_entities_external_resources_and_unknown_path_ops(tmp_path):
    entity = tmp_path / "entity.svg"
    entity.write_text(
        '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<svg width="8" height="8"><text>&xxe;</text></svg>',
        encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe XML"):
        load_svg(str(entity))

    external = tmp_path / "external.svg"
    external.write_text(
        '<svg width="8" height="8"><image href="file:///etc/passwd"/></svg>',
        encoding="utf-8")
    with pytest.raises(ValueError, match="external resources"):
        load_svg(str(external))

    with pytest.raises(ValueError, match="unsupported SVG path command"):
        _commands("M 0 0 H 7")
    with pytest.raises(ValueError, match="invalid SVG path syntax"):
        _commands("M 0 0 @ 7 7")


def test_native_filters_require_explicit_opt_in(qapp):
    register_filter(gmicpack.GmicRaw)
    assert "gmic" not in available_filters()
    assert "gmic" in available_filters(allow_unsafe=True)


def test_model_url_and_payload_validation(monkeypatch):
    with pytest.raises(ValueError, match="http"):
        HttpModelAdapter("file:///tmp/model")
    with pytest.raises(ValueError, match="loopback"):
        HttpModelAdapter("http://example.com/model")
    HttpModelAdapter("http://example.com/model", allow_insecure_http=True)
    with pytest.raises(ValueError, match="invalid base64"):
        png_b64_to_image("not base64!!")
    monkeypatch.setattr(modeladapter, "MAX_MODEL_RESPONSE", 4)
    oversized = base64.b64encode(b"xxxxx").decode()
    with pytest.raises(ValueError, match="too large"):
        png_b64_to_image(oversized)


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json",
                 length: int | None = None):
        self.body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amount: int) -> bytes:
        return self.body[:amount]


def test_model_response_type_schema_and_length(monkeypatch):
    adapter = HttpModelAdapter("http://127.0.0.1:8188/model")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(b"{}", "text/html"))
    with pytest.raises(ValueError, match="application/json"):
        adapter._post("test", {})

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            b"{}", length=MAX_MODEL_RESPONSE + 1))
    with pytest.raises(ValueError, match="too large"):
        adapter._post("test", {})

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(json.dumps([]).encode()))
    with pytest.raises(ValueError, match="JSON object"):
        adapter._post("test", {})


def test_mcp_confines_paths_blocks_overwrite_and_network_ops(qapp, tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    image.save(str(root / "input.png"))
    image.save(str(outside / "secret.png"))
    server.configure(root=root)

    assert server.document_info("input.png")["size"] == [4, 4]
    with pytest.raises(ValueError, match="MCP root"):
        server.document_info(str(outside / "secret.png"))
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="MCP root"):
        server.document_info("escape/secret.png")

    existing = root / "existing.png"
    image.save(str(existing))
    with pytest.raises(ValueError, match="overwrite is disabled"):
        server.edit_image([], new="4x4", output="existing.png")
    with pytest.raises(ValueError, match="not exposed through MCP"):
        server.edit_image(
            [{"op": "model-url", "value": "http://127.0.0.1"}],
            new="4x4", info=True)

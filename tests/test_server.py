# SPDX-License-Identifier: Apache-2.0
"""The MCP server surface. The tool functions are plain Python and tested
directly; the FastMCP wiring is exercised only when the optional ``mcp`` extra
is installed."""
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from photoslop import cli, server


@pytest.fixture(autouse=True)
def _confine_server_to_test_directory(tmp_path):
    server.configure(root=tmp_path)


def make_png(tmp_path, name="pic.png", size=(600, 400)):
    img = QImage(QSize(*size), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(10, 120, 240))
    path = str(tmp_path / name)
    img.save(path)
    return path


def test_list_operations_mirrors_cli_ops():
    catalog = server.list_operations()
    ops = catalog["operations"]
    assert catalog["count"] == len(cli.OPS) - 4
    assert [o["name"] for o in ops] == [
        name for name in cli.OPS
        if name not in {"model-url", "select-subject", "generative-fill",
                        "denoise-model"}
    ]
    by_name = {o["name"]: o for o in ops}
    assert by_name["resize"]["args"] == "WxH"
    assert by_name["auto-levels"]["args"] is None  # a no-argument flag op
    assert "rescale" in by_name["resize"]["help"]


def test_edit_image_new_document_info():
    result = server.edit_image([], new="40x30", info=True)
    assert result["info"]["size"] == [40, 30]


def test_edit_image_paper_preset_matches_cli(tmp_path):
    # same paper-preset maths as `photoslop-cli --new A4 --dpi 300`
    result = server.edit_image([], new="A4", dpi=300, info=True)
    assert result["info"]["size"] == [2480, 3508]


def test_edit_image_pipeline_writes_output(qapp, tmp_path):
    src = make_png(tmp_path, size=(600, 400))
    out = str(tmp_path / "out.png")
    result = server.edit_image(
        [{"op": "resize", "value": "300x200"}],
        input=src,
        output=out,
    )
    assert result["output"] == out
    written = QImage(out)
    assert (written.width(), written.height()) == (300, 200)


def test_edit_image_operations_compose_in_order(qapp, tmp_path):
    src = make_png(tmp_path, size=(100, 100))
    result = server.edit_image(
        [
            {"op": "resize", "value": "50x50"},
            {"op": "canvas-size", "value": "80x80"},
        ],
        input=src,
        info=True,
    )
    # resize then grow-canvas → 80×80, proving left-to-right composition
    assert result["info"]["size"] == [80, 80]


def test_edit_image_requires_a_result():
    with pytest.raises(ValueError, match="nothing to do"):
        server.edit_image([], new="40x30")


def test_edit_image_rejects_input_and_new_together(tmp_path):
    src = make_png(tmp_path)
    with pytest.raises(ValueError, match="not both"):
        server.edit_image([], input=src, new="40x30", info=True)


def test_edit_image_unknown_op():
    with pytest.raises(ValueError, match="unknown operation"):
        server.edit_image([{"op": "no-such-op", "value": ""}], new="10x10",
                          info=True)


def test_edit_image_malformed_operation_entry():
    with pytest.raises(ValueError, match="must be an object"):
        server.edit_image(["resize 10x10"], new="10x10", info=True)


def test_document_info_is_read_only(qapp, tmp_path):
    src = make_png(tmp_path, size=(80, 50))
    info = server.document_info(src)
    assert info["size"] == [80, 50]
    assert len(info["layers"]) == 1


def test_build_server_registers_the_three_tools(tmp_path):
    pytest.importorskip("mcp")
    srv = server.build_server(root=tmp_path)
    assert srv.name == "photoslop"
    import asyncio

    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert {"list_operations", "edit_image", "document_info"} <= names

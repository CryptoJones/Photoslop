# SPDX-License-Identifier: Apache-2.0
"""Dirty overlays, bounded thumbnails/proxies, and benchmark reports."""

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop import benchmarks
from photoslop.document import Document
from photoslop.exportdialog import ExportDialog
from photoslop.layerpanel import LayerPanel
from photoslop.mainwindow import MainWindow


def test_hover_overlay_dirty_region_is_smaller_than_canvas(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(2000, 1200), 72, "dirty", QColor("white")))
    canvas = win.current_editor().canvas
    dirty = canvas._overlay_dirty_rect(win.active_tool, QPointF(500, 400))
    assert dirty.width() < canvas.width() and dirty.height() < canvas.height()


def test_thumbnail_cache_is_generation_aware_and_live_layer_bounded(qapp):
    doc = Document.new(QSize(40, 30), 72, "thumb", QColor("red"))
    panel = LayerPanel()
    panel.set_document(doc)
    layer = doc.active_layer
    first = panel._thumb(layer)
    assert panel._thumb(layer).cacheKey() == first.cacheKey()
    layer.image.fill(QColor("blue"))
    changed = panel._thumb(layer)
    assert changed.cacheKey() != first.cacheKey()
    assert len(panel._thumb_cache) <= len(doc.layers)


def test_export_preview_is_proxy_bounded(qapp):
    doc = Document.new(QSize(1600, 900), 72, "proxy", QColor("green"))
    dialog = ExportDialog(doc)
    assert max(dialog._proxy.width(), dialog._proxy.height()) <= 512


def test_peak_rss_uses_the_platform_process_high_water_mark():
    assert benchmarks._peak_rss_kb() > 0


def test_scaled_benchmark_report_schema_and_gates(qapp, monkeypatch):
    # Wall-clock/RSS budgets run in dedicated CI processes. A monolithic test
    # process has unrelated historical ru_maxrss and is not performance evidence.
    monkeypatch.setattr(benchmarks, "_measure_render_cancellation", lambda _doc: 1.0)
    monkeypatch.setattr(benchmarks, "_peak_rss_kb", lambda: 64 * 1024)
    report = benchmarks.run(benchmarks.PRESETS["4k-50"], scale=0.01, samples=3)
    for key in (
        "frame_ms_p50",
        "frame_ms_p95",
        "document_bytes",
        "peak_rss_kb",
        "cancellation_ms",
        "target_frame_ms_p95",
        "target_gui_heartbeat_ms",
        "target_cancellation_ms",
        "target_peak_rss_kb",
        "layer_surface_bytes",
        "rendered_viewport_bytes",
    ):
        assert key in report and report[key] >= 0
    assert report["cancellation_ms"] < report["target_cancellation_ms"]
    assert report["frame_ms_p95"] < report["target_frame_ms_p95"]
    assert report["measured"]["layers"] == 50
    assert report["measured"]["layer_surface_bytes"] == report["layer_surface_bytes"]
    assert report["configured_limits"] == {"open_preview_max_px": 256, "export_preview_max_px": 512}
    assert report["passed"] and all(report["gates"].values())


def test_enforce_returns_nonzero_for_a_failed_budget(monkeypatch, capsys):
    monkeypatch.setattr(benchmarks, "run", lambda *_args, **_kwargs: {"passed": False})
    assert benchmarks.main(["4k-50", "--enforce"]) == 1
    assert '"passed": false' in capsys.readouterr().out

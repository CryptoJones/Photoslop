# SPDX-License-Identifier: Apache-2.0
"""Dirty overlays, bounded thumbnails/proxies, and benchmark reports."""

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.benchmarks import PRESETS, run
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


def test_scaled_benchmarks_report_p50_p95_memory_and_targets(qapp):
    report = run(PRESETS["4k-50"], scale=0.01, samples=3)
    for key in ("frame_ms_p50", "frame_ms_p95", "document_bytes", "peak_rss_kb",
                "target_frame_ms_p95", "target_gui_heartbeat_ms"):
        assert key in report and report[key] >= 0

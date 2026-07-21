# SPDX-License-Identifier: Apache-2.0
"""Reproducible interaction fixtures and P50/P95/RSS benchmark reporting."""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import sys
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, QRect, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document, render_region
from photoslop.layer import Layer
from photoslop.tasks import TaskService, TaskState


@dataclass(frozen=True)
class BenchmarkPreset:
    name: str
    width: int
    height: int
    layers: int
    target_frame_ms_p95: float
    target_peak_rss_mb: int


PRESETS = {
    "4k-50": BenchmarkPreset("4K / 50 layers", 3840, 2160, 50, 33, 2048),
    "12k-20": BenchmarkPreset("12K / 20 layers", 12000, 8000, 20, 33, 2048),
    "4k-10": BenchmarkPreset("4K / 10 layers", 3840, 2160, 10, 1000, 2048),
    "12mp-4": BenchmarkPreset("12 MP / 4 layers", 4000, 3000, 4, 750, 2048),
}


def fixture(preset: BenchmarkPreset, scale: float = 1.0) -> Document:
    width = max(16, round(preset.width * scale))
    height = max(16, round(preset.height * scale))
    doc = Document.new(QSize(width, height), 72, preset.name, QColor(30, 30, 30))
    for index in range(1, preset.layers):
        layer = Layer.blank(f"Layer {index + 1}", QSize(width, height))
        layer.image.fill(
            QColor(index * 37 % 255, index * 67 % 255, index * 97 % 255, 30 + index % 80)
        )
        doc.layers.append(layer)
    doc.active_index = len(doc.layers) - 1
    return doc


def _peak_rss_kb() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(value / 1024) if sys.platform == "darwin" else value


def _measure_render_cancellation(doc: Document) -> float:
    """Cancel a real TaskService render loop and wait until work has stopped."""
    app = QCoreApplication.instance() or QCoreApplication([])
    service = TaskService(max_workers=1, memory_budget=max(1, doc.memory_bytes() * 2))
    viewport = QRect(0, 0, min(doc.size.width(), 512), min(doc.size.height(), 512))
    started = threading.Event()
    stopped = threading.Event()

    def render_until_cancelled(context):
        started.set()
        try:
            while True:
                context.check_cancelled()
                rendered = render_region(doc, viewport)
                if rendered.size() != viewport.size():
                    raise RuntimeError("cancel benchmark rendered the wrong region")
        finally:
            stopped.set()

    handle = service.submit(
        "benchmark.render",
        "Benchmark render",
        render_until_cancelled,
        max(1, viewport.width() * viewport.height() * 8),
    )
    start_deadline = time.monotonic() + 5
    while handle.state is TaskState.QUEUED and time.monotonic() < start_deadline:
        app.processEvents()
        time.sleep(0.001)
    if handle.state is not TaskState.RUNNING:
        raise RuntimeError("render cancellation benchmark did not start")
    if not started.wait(5):
        raise RuntimeError("render cancellation benchmark worker did not start")
    start = time.perf_counter()
    handle.cancel()
    if not stopped.wait(5):
        raise RuntimeError("render side effects did not stop after cancellation")
    cancellation_ms = (time.perf_counter() - start) * 1000
    completion_deadline = time.monotonic() + 1
    while handle.state not in {TaskState.CANCELLED, TaskState.FAILED}:
        if time.monotonic() >= completion_deadline:
            raise RuntimeError("render cancellation completion was not delivered")
        app.processEvents()
        time.sleep(0.001)
    if handle.state is TaskState.FAILED:
        raise RuntimeError("render cancellation benchmark failed")
    service.pool.waitForDone()
    return cancellation_ms


def run(preset: BenchmarkPreset, scale: float = 1.0, samples: int = 20) -> dict:
    if not 0 < scale <= 1:
        raise ValueError("benchmark scale must be in (0, 1]")
    if samples < 1:
        raise ValueError("benchmark samples must be positive")
    doc = fixture(preset, scale)
    viewport = QRect(0, 0, min(doc.size.width(), 1920), min(doc.size.height(), 1080))
    warm = render_region(doc, viewport)  # exclude one-time Qt/cache initialization
    if warm.size() != viewport.size() or warm.isNull():
        raise RuntimeError("benchmark produced an invalid viewport")
    timings = []
    for _ in range(samples):
        start = time.perf_counter()
        render_region(doc, viewport)
        timings.append((time.perf_counter() - start) * 1000)
    ordered = sorted(timings)
    p95_index = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
    cancellation_ms = _measure_render_cancellation(doc)
    peak_rss_kb = _peak_rss_kb()
    layer_bytes = sum(layer.image.sizeInBytes() for layer in doc.layers)
    target_frame = preset.target_frame_ms_p95
    target_cancellation = 250
    target_peak_rss_kb = preset.target_peak_rss_mb * 1024
    gates = {
        "frame_p95": ordered[p95_index] <= target_frame,
        "cancellation": cancellation_ms <= target_cancellation,
        "peak_rss": peak_rss_kb <= target_peak_rss_kb,
        "output": warm.size() == viewport.size() and not warm.isNull(),
    }
    report = {
        "preset": preset.name,
        "scale": scale,
        "samples": samples,
        "frame_ms_p50": statistics.median(ordered),
        "frame_ms_p95": ordered[p95_index],
        "document_bytes": doc.memory_bytes(),
        "layer_surface_bytes": layer_bytes,
        "rendered_viewport_bytes": warm.sizeInBytes(),
        "peak_rss_kb": peak_rss_kb,
        "cancellation_ms": cancellation_ms,
        "measured": {
            "layers": len(doc.layers),
            "viewport": [viewport.width(), viewport.height()],
            "layer_surface_bytes": layer_bytes,
            "rendered_viewport_bytes": warm.sizeInBytes(),
        },
        "configured_limits": {
            "open_preview_max_px": 256,
            "export_preview_max_px": 512,
        },
        "target_frame_ms_p95": target_frame,
        "target_gui_heartbeat_ms": 100,
        "target_cancellation_ms": target_cancellation,
        "target_peak_rss_kb": target_peak_rss_kb,
        "gates": gates,
    }
    report["passed"] = all(gates.values())
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("preset", choices=PRESETS)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument(
        "--enforce", action="store_true", help="exit nonzero when a reviewed budget is exceeded"
    )
    args = parser.parse_args(argv)
    report = run(PRESETS[args.preset], args.scale, args.samples)
    print(json.dumps(report, indent=2))
    return 1 if args.enforce and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

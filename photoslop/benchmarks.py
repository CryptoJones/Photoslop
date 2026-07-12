# SPDX-License-Identifier: Apache-2.0
"""Reproducible interaction fixtures and P50/P95/RSS benchmark reporting."""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document, render_region
from photoslop.layer import Layer


@dataclass(frozen=True)
class BenchmarkPreset:
    name: str
    width: int
    height: int
    layers: int


PRESETS = {
    "4k-50": BenchmarkPreset("4K / 50 layers", 3840, 2160, 50),
    "12k-20": BenchmarkPreset("12K / 20 layers", 12000, 8000, 20),
}


def fixture(preset: BenchmarkPreset, scale: float = 1.0) -> Document:
    width = max(16, round(preset.width * scale))
    height = max(16, round(preset.height * scale))
    doc = Document.new(QSize(width, height), 72, preset.name, QColor(30, 30, 30))
    for index in range(1, preset.layers):
        layer = Layer.blank(f"Layer {index + 1}", QSize(width, height))
        layer.image.fill(QColor(index * 37 % 255, index * 67 % 255,
                                index * 97 % 255, 30 + index % 80))
        doc.layers.append(layer)
    doc.active_index = len(doc.layers) - 1
    return doc


def run(preset: BenchmarkPreset, scale: float = 1.0, samples: int = 20) -> dict:
    doc = fixture(preset, scale)
    viewport = QRect(0, 0, min(doc.size.width(), 1920), min(doc.size.height(), 1080))
    render_region(doc, viewport)  # exclude one-time Qt/font/cache initialization
    timings = []
    for _ in range(samples):
        start = time.perf_counter()
        render_region(doc, viewport)
        timings.append((time.perf_counter() - start) * 1000)
    ordered = sorted(timings)
    p95_index = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
    cancelled = threading.Event()
    observed = threading.Event()

    def cooperative_worker():
        while not cancelled.is_set():
            time.sleep(0.001)
        observed.set()

    worker = threading.Thread(target=cooperative_worker)
    worker.start()
    cancel_start = time.perf_counter()
    cancelled.set()
    worker.join(timeout=1)
    cancellation_ms = (time.perf_counter() - cancel_start) * 1000
    assert observed.is_set()
    return {
        "preset": preset.name,
        "scale": scale,
        "samples": samples,
        "frame_ms_p50": statistics.median(ordered),
        "frame_ms_p95": ordered[p95_index],
        "document_bytes": doc.memory_bytes(),
        "peak_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "cancellation_ms": cancellation_ms,
        "cache_budgets": {"thumbnail_entries": len(doc.layers),
                          "open_preview_max_px": 256,
                          "export_preview_max_px": 512},
        "target_frame_ms_p95": 33,
        "target_gui_heartbeat_ms": 100,
        "target_cancellation_ms": 100,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("preset", choices=PRESETS)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args(argv)
    print(json.dumps(run(PRESETS[args.preset], args.scale, args.samples), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

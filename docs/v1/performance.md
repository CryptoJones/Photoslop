# Performance and memory verification

Photoslop keeps one resident ARGB32 buffer per ordinary layer, uses COW worker
snapshots, bounds caches to live objects/proxies, and never retains a flattened
full-canvas cache.

## Reproducible fixtures

The pull-request jobs run these as scaled algorithm smoke checks:

```console
QT_QPA_PLATFORM=offscreen uv run python -m photoslop.benchmarks 4k-50 --scale 0.01 --enforce
QT_QPA_PLATFORM=offscreen uv run python -m photoslop.benchmarks 12k-20 --scale 0.01 --enforce
```

Scale `0.01` does not constitute performance evidence. A scheduled workflow
allocates bounded, full-resolution fixtures instead:

```console
QT_QPA_PLATFORM=offscreen uv run python -m photoslop.benchmarks 4k-10 --enforce
QT_QPA_PLATFORM=offscreen uv run python -m photoslop.benchmarks 12mp-4 --enforce
```

The JSON report includes viewport P50/P95, document/layer/rendered bytes,
process peak RSS, actual `TaskService` render-cancellation latency, output
validity, reviewed targets, and a pass/fail gate per measurement. `--enforce`
exits nonzero when a budget is exceeded; `--samples N` controls repetitions.
Run each evidence preset in a fresh process: peak RSS is a process-lifetime
high-water mark and a shared functional-test process would include unrelated
earlier allocations.
Linux/macOS read the process high-water mark through `getrusage`; Windows uses
`GetProcessMemoryInfo.PeakWorkingSetSize`, reported in the same KiB unit.

## Observed full-resolution baseline

On 2026-07-21, Linux 7.0.0 x86-64, Python 3.12.13, and PySide6 6.11.1,
five-sample enforced runs produced:

| Fixture | P50 | P95 | Peak RSS | Cancellation | Result |
|---|---:|---:|---:|---:|---|
| 4K / 10 layers | 8.39 ms | 10.97 ms | 397.3 MiB | 0.06 ms | pass |
| 12 MP / 4 layers | 3.27 ms | 6.40 ms | 264.8 MiB | 0.55 ms | pass |

These numbers are one machine's baseline, not a cross-platform performance
claim. Scheduled reports remain the release evidence and must be compared using
the complete environment record below.

## Filter transients

Full-layer pixel work in `photoslop.npimage` and `photoslop.adjust` runs in
row bands (`BAND_ROWS` / `CHUNK_ROWS`, 256 rows), so the float planes a
filter needs exist for one band at a time and the peak does not grow with the
layer's height. The blur family adds a halo of three box radii either side of
each band and keeps its vertical sums in integers, which makes the banded
result bit-identical to the whole-image computation
(`tests/test_npimage_banding.py` checks this, and that the peak is the same at
3 MP and 6 MP).

Measured on 2026-09-02 with `tracemalloc` (which sees numpy's allocations; the
layer buffer itself is Qt's and is excluded) on a 4000×3000 premultiplied
layer, one operation per process, Linux 7.0.0 x86-64, Python 3.12.13,
numpy 2.5.0:

| Operation | Peak before (v2.20.0) | Peak after (v2.20.1) | Wall before → after |
|---|---:|---:|---:|
| `gaussian_blur`, radius 8 | 687 MiB | 43 MiB | 3.27 s → 1.84 s |
| `gaussian_blur`, radius 50 | 687 MiB | 57 MiB | 3.27 s → 2.37 s |
| `unsharp_mask`, radius 4 | 641 MiB | 65 MiB | 3.52 s → 1.50 s |
| `blend_by_weights` (tilt-shift, feathered filters) | 824 MiB | 23 MiB | 1.06 s → 0.29 s |
| `puppet_warp`, two pins | 2518 MiB | 164 MiB | 3.76 s → 1.21 s |

The remaining peaks scale with the layer *width* times the band (plus the
blur halo); a 12 MP layer's four float32 planes alone would be 192 MiB.
`feathered_weights` and `drop_shadow_image` still blur whole planes, but a
single float32 plane, not four.

## Interaction budgets

- Scaled smoke work targets **33 ms P95**. Full-scale targets are stored with
  each preset and reported beside each measurement.
- The GUI heartbeat remains below **100 ms** while background work runs.
- Progress or indeterminate busy feedback appears at task enqueue.
- Scheduling is bounded by peak bytes and workers, preserves FIFO inside its
  priority class, and lets a runnable small task bypass a memory-blocked head.
- Actual render work stops within **250 ms** after cooperative cancellation.
- Thumbnail entries exist only for live layers and regenerate on image changes.
- Open/export previews discard stale generations and are capped at 256/512 px;
  exact export encoding runs through a revision-safe worker.
- Hover, brush, path, transform, guide, focus, and selection overlays repaint
  only their old/new visible bounds.

Comparisons must record machine/OS/Qt/Python, commit, fixture, scale, samples,
P50/P95, peak RSS, cancellation latency, measured surface/view bytes, and all
gate results. An optimization fails review if it creates a persistent
full-canvas composite or an unbounded cache.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

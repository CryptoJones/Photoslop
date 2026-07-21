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

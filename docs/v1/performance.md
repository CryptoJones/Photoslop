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

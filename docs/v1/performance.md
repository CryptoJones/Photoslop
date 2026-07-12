# Performance and memory verification

Photoslop keeps one resident ARGB32 buffer per ordinary layer, uses COW worker
snapshots, bounds caches to live objects/proxies, and never retains a flattened
full-canvas cache.

## Reproducible fixtures

Run either standardized fixture from the repository environment:

```console
QT_QPA_PLATFORM=offscreen uv run python -m photoslop.benchmarks 4k-50
QT_QPA_PLATFORM=offscreen uv run python -m photoslop.benchmarks 12k-20
```

The JSON report includes sample count, viewport render P50/P95 milliseconds,
document pixel bytes, process peak RSS, and the 33 ms P95 frame / 100 ms GUI
heartbeat targets. `--samples N` controls repetitions; `--scale 0.01` provides a
deterministic CI smoke version without allocating the reference fixture.

## Interaction budgets

- Fit-to-window canvas work targets **33 ms P95** on the documented machine.
- The GUI heartbeat must remain below **100 ms** while background work runs.
- Progress or indeterminate busy feedback appears immediately on task enqueue.
- Task scheduling is bounded by declared peak bytes and worker count.
- Thumbnail entries exist only for live layers and regenerate only when that
  layer's QImage generation changes.
- Open/export previews discard stale generations. Display previews are capped
  at 256/512 px; exact full-size export encoding occurs in a cancellable worker.
- Hover, brush, path, transform, guide, and selection animation repaint only
  their old/new visible dirty bounds.

Benchmark comparisons must record machine/OS/Qt/Python, Photoslop commit,
fixture, samples, P50/P95, peak RSS, task cancellation latency, and cache sizes.
An optimization fails review if it creates a persistent full-canvas composite
or grows a cache without an explicit bound.

# Actions

Edit → Actions — the batch-workflow macro recorder.

1. **Start Recording**, then work normally. Parametrised operations record
   themselves with their exact dialog values (Gaussian Blur, Unsharp Mask,
   Tilt-Shift in v1).
2. **Stop Recording** captures the sequence (the status bar lists the steps).
3. **Play** (`F9`) runs the action against the *current* document's active
   layer — switch documents to apply the same look everywhere. Playback is
   one "Play Action" undo macro.

Actions live in memory for the session; on-disk action files are a planned
follow-up. For durable scripted pipelines today, use the
[command line](cli.md) — every recorded operation has a CLI equivalent.

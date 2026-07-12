# Actions

## Command palette and availability

Press `Ctrl+Shift+P` to search every registered menu command by name, stable
command ID, or shortcut. The detail line says whether the command is available;
disabled entries explain the missing document, layer, selection, clipboard, or
idle-task prerequisite. Menus and search use the same action metadata, so their
enabled state cannot drift apart.

The Properties dock follows the active layer or vector-backed object and offers
named controls for visibility, name, opacity, and blend mode. The tool-options
bar names the active tool, exposes units to assistive technology, includes Reset
Tool Options, and moves excess controls into Qt's overflow at narrow widths.
Saved layouts that no longer intersect any current screen are moved back onto
the primary display.

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

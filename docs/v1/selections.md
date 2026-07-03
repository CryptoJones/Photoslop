# Selections

Selections are QPainterPath regions; marching ants render on canvas, and
every selection-aware operation (fills, filters, adjustments, CLI ops)
honours them.

## Making selections
Marquee `M`, Lasso `L`, Polygonal `Shift+L`, **Magnetic Lasso** `Alt+L`
(live-wire edge snapping), Magic Wand `W` (tolerance; contiguous toggle for
colour-range), Quick Select `Shift+W` (paint to grow), and **Select Subject
(Model)** via any configured model backend (see
[Model Backends](model-backends.md)). `Ctrl+A` all, `Ctrl+D` deselect.

## Refine (`Ctrl+Alt+R`)
Grow / shrink / smooth the selection with numpy morphology, previewed live.

## Feather (`Ctrl+Alt+D`)
Gives the selection a soft edge; subsequent operations blend by normalized
feathered weights (border-corrected — no under-counting at image edges).

## Content-Aware Fill (`Shift+F5`)
Diffusion-inpaints the selected region from its boundary.

## Crop to Selection (`Ctrl+Alt+C`)
Instant offset-shift crop, fully undoable.

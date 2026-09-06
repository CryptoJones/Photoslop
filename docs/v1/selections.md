# Selections

Selections are QPainterPath regions; marching ants render on canvas, and
every selection-aware operation (fills, filters, adjustments, CLI ops)
honours them.

## Making selections
Marquee `M`, Elliptical Marquee `Shift+M` (hold Shift while dragging for a
perfect circle), Lasso `L`, Polygonal `Shift+L` (Enter, double-click, or
clicking the first vertex closes), **Magnetic Lasso** `Alt+L`
(live-wire edge snapping), Magic Wand `W` (tolerance; contiguous toggle for
colour-range), Quick Select `Shift+W` (paint to grow), and **Select Subject
(Model)** via any configured model backend (see
[Model Backends](model-backends.md)). All selection commands live in the
**Select** menu: All `Ctrl+A`, Deselect `Ctrl+D`, Subject (Model),
Cut is `Ctrl+X` (headless: `--clear`). CLI selections: `--select`,
`--select-ellipse`, `--select-poly`.
Feather…, Refine….

## Refine (`Ctrl+Alt+R`)
Grow / shrink / smooth the selection with numpy morphology, previewed live.

## Feather (`Ctrl+Alt+D`)
Gives the selection a soft edge; subsequent operations blend by normalized
feathered weights (border-corrected — no under-counting at image edges).

## Fill Selection (`Shift+Backspace`)
Fills the selected region of the active layer with the foreground colour,
one undo step; a feathered selection fades over its ramp. Fill Layer
(`Alt+Backspace`) deliberately ignores the selection and paints the whole
layer — the two are separate commands. Headless: `--fill-selection R,G,B`.
The bucket is a third thing again: it grows a region of similar colour from
a click and stops at the selection's edge, so on a selection spanning more
than one colour it paints only the region clicked in.

## Content-Aware Fill (`Shift+F5`)
Diffusion-inpaints the selected region from its boundary.

## Crop to Selection (`Ctrl+Alt+C`)
Instant offset-shift crop, fully undoable.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

# Tools

All 31 tools, their keys, and what they do. Cycling variants share a key with
`Shift` (Photoshop convention).

## Cursor feedback

The canvas pointer follows the active tool and its current context. Paint tools
show the effective brush diameter at the current zoom (with the full-size canvas
outline retained for very large brushes); selection modifiers display add,
subtract, or intersect badges; `Alt` switches Zoom to zoom-out and marks
Clone/Healing source sampling. Transform edges and corners use directional
resize pointers, while move, rotate, warp-node, and invalid targets are distinct.
Custom cursors use a black-and-white high-contrast outline and HiDPI pixmaps.

Holding `Space` always overrides the current pointer with Open Hand, changes to
Closed Hand while dragging, and restores the exact prior tool/modifier state on
release.

## Toolbox groups and density

Related tools share a flyout button instead of occupying one long column. Click
the main button to reactivate the last-used member; click its menu side to choose
another tool. The groups cover Move, marquees, lassos, automatic selection,
crop/warp, paint, healing, retouching, fill, Pen, Shape, Text, Eyedropper, and
navigation. Every member retains its documented keyboard shortcut and is
available as a named menu action for keyboard and assistive-technology users.

The final toolbox button selects Compact icons, Comfortable icons, or Icons and
labels. The choice persists across launches. Icons are palette-aware SVGs with
normal, active, selected, and disabled states at 1× and 2× rendering sizes; see
`THIRD_PARTY_NOTICES.md` for the pinned Tabler source and MIT license.

## Paint
| Tool | Key | Behaviour |
|---|---|---|
| Brush | `B` | Soft/hard round strokes; size, hardness, opacity, **flow** (stroke-ceiling engine), spacing, and scatter in the options bar. `[` / `]` size, `Shift+[` / `Shift+]` hardness. |
| Pencil | `Shift+B` | Hard-edged, aliased strokes. |
| Eraser | `E` | Erases to transparency at brush parameters. |
| Bucket | `G` | Fill by tolerance; contiguous toggle; **pattern fill** via Edit → Define Pattern and fill-source option. |
| Gradient | `G` (cycles) | Linear or radial, foreground→background. |
| Clone Stamp | `S` | `Alt`-click to set the source; aligned sampling. |
| Healing Brush | `Shift+S` | Clone with texture-preserving tone blend (src − blur(src) + blur(dst)). |
| Spot Heal | `J` | Paint a blemish; it diffusion-fills from the boundary. |
| Patch | `Alt+Shift+J` | Lasso a region, drag it to a source; tone-matched fill. |
| Smudge/Mixer | `Shift+J` | Drags colour along the stroke. |
| Dodge | `O` | Lightens (soft-light stamps). |
| Burn | `Shift+O` | Darkens. |

## Select
| Tool | Key | Behaviour |
|---|---|---|
| Rectangular Marquee | `M` | Drag a rectangle. |
| Elliptical Marquee | `Shift+M` | Drag an ellipse; hold Shift for a perfect circle. |
| Lasso | `L` | Freehand. |
| Polygonal Lasso | `Shift+L` | Click vertices; `Enter`, double-click, or clicking the first point closes. |
| Magnetic Lasso | `Alt+L` | Live-wire edge snapping (Dijkstra over gradient). |
| Magic Wand | `W` | Tolerance select; contiguous toggle = colour-range mode. |
| Quick Select | `Shift+W` | Paint to grow a selection. |

See [Selections](selections.md) for refine, feather, and content-aware fill.

## Vector-ish
| Tool | Key | Behaviour |
|---|---|---|
| Shape | `U` | Drag a rect/ellipse/line onto a **new bounded layer**; `Shift+U` cycles the kind. **Parametric**: click the active shape layer to re-edit — drag corner/endpoint handles or the body to move; transforms re-render from geometry. |
| Pen | `P` | Click anchors; the path smooths through them (Catmull-Rom). `Enter` strokes at brush size, `Ctrl+Enter` fills the closed path, double-click commits, `Esc` cancels. **Parametric**: click the active pen layer to pick its anchors back up — drag to move, click to append, commit re-renders. |
| Text | `T` | Click to place; a **rich-text editor** takes the content — a WYSIWYG box that previews the text in the font and colour you choose as you type. Pick a font/size, toggle **bold**/*italic*, and colour the whole block *or individual letters* (select a run, then pick a colour). Rasterises to a new layer. Clicking inside the **active** text layer re-opens the editor with all its styling intact and edits it in place. |

## Transform & navigation
| Tool | Key | Behaviour |
|---|---|---|
| Move | `V` | Move layers (or whole groups); snaps to guides/grid. |
| Vector Selection | `A` | Select native vector objects; Shift-click builds a multi-selection and drag applies one undoable transform. |
| Direct Selection | `Shift+A` | Select an anchor in the current native vector selection for node editing. |
| Crop | `C` | Drag, `Enter` commits (offset-shift crop — instant, no pixel copies). |
| Free Transform | `Ctrl+T` | Scale/rotate/translate; `Ctrl`-drag corners for distort/perspective. See [Transforms](transforms.md). |
| Liquify | `Y` | Push pixels under the brush (bilinear warp). |
| Puppet Warp | `Shift+Y` | Place pins; anchored pins hold, dragged pins bend (IDW displacement). |
| Perspective Warp | `Shift+P` | Define a quad, then drag corners; projective re-render. |
| Eyedropper | `I` | Sample colour (composite-aware). `X` swaps fg/bg, `D` resets. |
| Hand | `H` (or hold `Space`) | Pan. |
| Zoom | `Z` | Click/`Alt`-click; `Ctrl+=`/`Ctrl+-`, `Ctrl+0` fit, `Ctrl+1` 100%, toolbar +/− buttons. Ladder 1/32×–16×. |
| Rotate View | `R` / `Shift+R` | 90° display-only rotation — pixels untouched. |

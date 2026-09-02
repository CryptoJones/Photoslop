# Filters

All filters are selection-aware (mask-confined; feathered selections blend at
the edge) and land as one undo step.

- **Gaussian Blur** — radius in px (triple box-blur approximation, cumsum-
  based, O(n) in pixels).
- **Unsharp Mask** — amount in percent over a fixed radius.
- **Tilt-Shift** — keep a horizontal band sharp (centre, band, transition)
  and blur outward to the given radius.

## Node Machine

Generative circuit-trace artwork grown from the layer's **silhouette**: nodes
are scattered inside the mask, wired to their nearest neighbours, and each
edge is routed the way a PCB autorouter would — one axis-aligned run plus one
45-degree diagonal — then stroked as a bundle of parallel copies, with pads at
the nodes and a two-stop gradient projected across the frame.

It wants a **cut-out subject on a transparent layer**. On a fully opaque layer
there is no silhouette, so `source=auto` falls back to a luma threshold —
which is the "subject on a black background" case; force either behaviour with
`source=alpha` or `source=luma`.

Six presets ship as separate filters, each a full set of live sliders:

| Filter | CLI name | Look |
|---|---|---|
| Node Machine | `node-machine` | green-to-white bundled traces, contour stroked |
| Node Machine (Circu1t) | `node-machine-circuit` | thin cyan traces laid over the original art |
| Node Machine (Web) | `node-machine-web` | sparse cyan node web with big pads |
| Node Machine (Nodes) | `node-machine-nodes` | dense triangulated graph, yellow-to-blue, glowing |
| Node Machine (Lightning) | `node-machine-lightning` | magenta-to-cyan bundles with a bloom |
| Node Machine (Vertical Flow) | `node-machine-vertical` | vertical drop lines and pads |

Parameters (all shared by every preset):

| Key | Range | Meaning |
|---|---|---|
| `components` | 4–400 | node count |
| `traces` | 1–8 | neighbours wired per node |
| `bundle` | 1–8 | parallel copies of each trace |
| `spacing` | 1–12 | px between bundled copies |
| `weight` | 1–6 | line width in px |
| `pads` | 0–12 | pad radius; 0 turns pads off |
| `outline` | 0/1 | stroke the silhouette contour |
| `style` | pcb / straight / vertical | routing shape |
| `glow` | 0–100 | additive blurred halo |
| `hue-a` / `sat-a` | 0–359 / 0–100 | gradient start (saturation 0 = white) |
| `hue-b` / `sat-b` | 0–359 / 0–100 | gradient end |
| `angle` | 0–359 | gradient direction in degrees |
| `keep` | 0–100 | opacity of the source art kept underneath |
| `source` | auto / alpha / luma | where the silhouette comes from |
| `seed` | 0–9999 | RNG seed — the same seed always redraws the same art |

```bash
photoslop-cli statue.png --filter "node-machine:components=120,glow=40" --output traced.png
photoslop-cli statue.png --filter node-machine-circuit --output overlay.png
```

Filters applied to a smart-object layer record themselves for
**Re-apply Smart Filters** — see [Layers](layers.md).

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

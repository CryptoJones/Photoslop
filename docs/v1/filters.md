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

## Beam Dither

One-bit rendering, either as a classic dither or as a modulated CRT raster
(#384). Two stages, and they are separable on purpose.

**Conditioning** comes first — brightness, contrast, blur, sharpen, grain —
because every dither is only as good as the contrast handed to it. Error
diffusion applied to a flat photograph gives flat noise; the same photograph
pushed to a hard tonal curve first gives structure. Sharpen runs after blur so
the pair acts as a band-pass rather than cancelling out, and grain is added
last so the dither sees it as signal.

**Rendering** is then one of two different ideas:

- A **dither** asks which pixels to light so that a coarse palette still
  averages out to the original tone. *Error diffusion* (`floyd-steinberg`,
  `atkinson`, `jarvis`, `stucki`, `sierra`, `burkes`) pushes each pixel's
  rounding error into neighbours it has not visited yet, scanning serpentine so
  the residual cannot drift the same way on every row and print as diagonal
  worming. *Ordered* dithering (`bayer-2/4/8`) compares against a fixed
  threshold matrix instead and has no memory at all, which makes it stable and
  tileable where error diffusion is neither. `atkinson` deliberately diffuses
  only 6/8 of the error — that deficit is why classic Macintosh dithers look
  crisp and a little blown out.
- **Beam modulation** (`beam`) is not a dither and does not preserve average
  tone. It draws a raster of horizontal beams and lets the picture *deflect*
  them, the way a CRT's vertical deflection coil is driven by a signal. Bright
  pixels push their beam off its resting row and widen it, so the image appears
  as bending, thickening scanlines that trace contours. The soft shoulders are
  then stippled at `levels=2`, so a beam thins into dots as it leaves the light
  rather than fading to grey.

**Cell size** (`scale`) is what makes a render read as chunky: the algorithm
sees one value per cell and the cell is on or off as a whole. It is also the
performance control — error diffusion is inherently sequential and costs
O(pixels), so a large image at `scale=1` is slow by nature, not by accident.

**Render mode** inks the result. `mono` is two-tone. `tonal` is tri-tone: which
ink a lit pixel takes is chosen by the *original* luminance beneath it, so
shadows keep their own colour even where the dither happens to light them.
`color` dithers each RGB channel independently, which is where the colour
speckle of an indexed-palette render comes from.

| Parameter | Range | Meaning |
|---|---|---|
| `algorithm` | beam / floyd-steinberg / atkinson / jarvis / stucki / sierra / burkes / bayer-2 / bayer-4 / bayer-8 / threshold | how the tone is rendered |
| `mode` | mono / tonal / color | how the result is inked |
| `scale` | 1–32 | cell size in px; also the cost control |
| `levels` | 2–8 | output tones; 2 is one-bit |
| `brightness` / `contrast` | -100–100 | conditioning, contrast pivots on mid grey |
| `blur` | 0–20 | conditioning blur radius |
| `sharpen` / `sharpen_radius` | 0–300 / 1–20 | unsharp mask strength and radius |
| `noise` | -100–100 | negative denoises, positive adds seeded grain |
| `beam_pitch` | 2–64 | px between beams (`beam` only) |
| `beam_amplitude` | 0–8 | how far luminance deflects a beam; 0 is straight scanlines |
| `highlights` / `midtones` / `shadows` | `#RRGGBB` | the three inks; only `tonal` uses all three |
| `background` | `#RRGGBB` | what an unlit pixel becomes |

```bash
# engraved contour lines, the CRT-raster look
photoslop-cli portrait.jpg \
  --filter "beam-dither:algorithm=beam,scale=2,beam_pitch=7,beam_amplitude=2,contrast=35,sharpen=90,sharpen_radius=6" \
  --output engraved.png

# classic one-bit stipple, tri-toned in cyan
photoslop-cli portrait.jpg \
  --filter "beam-dither:algorithm=floyd-steinberg,mode=tonal,scale=2,shadows=#0B3C5D,midtones=#6CCFF6,highlights=#FFFFFF" \
  --output stippled.png
```

Filters applied to a smart-object layer record themselves for
**Re-apply Smart Filters** — see [Layers](layers.md).

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

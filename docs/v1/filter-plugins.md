# Filter Plugins

Photoslop discovers filters from the **`photoslop.filters` entry-point
group** — the same architecture as [model backends](model-backends.md). A
pip-installed plugin can appear in the **Filter menu** (with an auto-generated
parameter dialog), works in the **CLI** as `--filter "name:key=val,..."`,
respects **selections and feathering**, participates in **actions** and
**smart-filter replay** — all from one class and one entry point.

Seven built-ins ship in the box and double as living documentation — all pure
numpy, so none of them needs the unsafe-plugin opt-in below:

| Filter | CLI name | Params |
|---|---|---|
| Sepia | `sepia` | `amount` 0–100 |
| Pixelate | `pixelate` | `size` 2–128 |
| Denoise (Chroma) | `denoise` | `strength` 1–100 |
| Retro Console (8-Bit) | `retro-console` | `size` 1–64, `levels` 2–8, `dither` 0/1 |
| Pixel Sort (Glitch) | `pixel-sort` | `low`/`high` 0–255, `vertical` 0/1, `reverse` 0/1 |
| Datamosh + Chromatic Aberration | `datamosh` | `block` 4–64, `amount` 0–100, `drift` 0–64, `aberration` 0–20, `seed` 0–9999 |
| Film Negative → Positive | `film-negative` | `mode` auto/color/mono, `clip` 0.0–5.0 |

**Film Negative** develops a scanned negative into the photograph that was on
the film. It is not an inversion. Two things make `255 - v` wrong:

- A **colour negative carries an orange mask** — a dye layer in the film base
  that corrects the dyes' unwanted absorptions — so a plain invert leaves the
  familiar muddy cyan-blue image with the mask still in it.
- Film records **transmittance**, so the inversion is a reciprocal rather than
  a subtraction: the positive is `base / v`, which is a subtraction in *density*
  space, not in scan values.

Both fall to one operation — normalise each channel independently in reciprocal
space between its own clipped extremes. Per-channel normalisation removes the
mask (a constant density offset per channel is a constant factor here, and
divides straight out); the reciprocal gets film's tonality right.

A **black-and-white** negative has no mask and must stay neutral: normalising
its channels independently would stretch whatever tint the acetate base and the
scanner contributed into a colour cast. Mono negatives are developed from a
single luma channel and written back neutral.

`mode=auto` tells the two apart by mean per-pixel chroma — the mask puts a
colour negative far from neutral everywhere, a monochrome scan sits near zero,
and the threshold has wide margin on both sides. Set `mode` explicitly for the
unusual frame: a badly faded or cross-processed negative, or a colour negative
that was scanned to greyscale. `clip` is the percentage discarded from each end
before normalising, so a dust speck, a scanner flare or the clear film edge
cannot define the whole scale on its own.

**Pixel Sort** gathers pixels whose luma falls inside the `low`..`high` band
into contiguous runs along each row (or column) and sorts each run by
brightness; everything outside the band stays put, and those untouched darks
and highlights are what bound the smear. A full band (`low=0,high=255`)
liquefies the frame; a narrow one picks out edges.

**Datamosh** cuts the image into a macroblock grid, hands a fraction of blocks
a random motion vector, and lets every other block inherit the vector above
it — displacement accumulates down the frame the way a P-frame chain does with
no keyframe to reset it, which is what separates a mosh from block noise.
`aberration=0` gives the mosh alone; `amount=0` gives the radial colour fringe
alone.

`seed` is what makes the glitch **reusable across a set of images**. The motion
field is keyed by block *position*, not by draw order, so the same seed puts the
same glitch on every image you apply it to regardless of their sizes — batch a
folder through the CLI and the whole set matches. Actions and smart-filter
replay reproduce it exactly for the same reason. The one limit is the canvas
edge: displacement is clamped to the image, so a `drift` big enough to run a
block off a small picture cannot land identically on a larger one.

Native packs and third-party Python entry points are disabled by default. Enable
them locally under **Preferences → Security** (restart required), or pass
`--allow-unsafe-plugins` to `photoslop-cli`. That opt-in permits arbitrary local
code/process execution and is intentionally unavailable through MCP. Built-in
Sepia and Pixelate remain available without it. Smart-filter recipes imported
from ORA files prompt for trust before replay.

## The G'MIC pack (`photoslop[gmic]`)

```bash
pip install "photoslop[gmic]"       # gmic-py wheel; or apt install gmic for the CLI fallback
```

With the wheel (or a `gmic` binary on PATH) installed, the pack
auto-registers — no entry point needed:

| Filter | CLI name | Params |
|---|---|---|
| G'MIC Cartoon | `gmic-cartoon` | `smoothness` 0–10, `colors` 0.5–3 |
| G'MIC Old Photo | `gmic-old-photo` | — |
| G'MIC Drawing | `gmic-drawing` | `amplitude` 1–300 |
| G'MIC Stencil (B&W) | `gmic-stencil` | `radius` 0.5–10, `smoothness` 1–30 |
| G'MIC Spread | `gmic-spread` | `dx`/`dy` 0–32 |
| G'MIC Solarize | `gmic-solarize` | `threshold` 0–255 |
| G'MIC Smooth (anisotropic) | `gmic-smooth` | `amplitude` 1–500 |
| **G'MIC Command** | `gmic` | `command` — any G'MIC pipeline, verbatim |

**G'MIC Command is the whole library**: `--filter "gmic:command=fx_bokeh
3,8,0,30,8,4,0.3,0.2,210,210,80,160,0.7,30,20,1,1,170,130,20,110,0.15,0"`
runs the community bokeh; commas after `command=` belong to the command.
Only RGB is handed to G'MIC — alpha is kept aside and reattached, so
transparency can't be corrupted. Per DD-008, each run costs a transient
float copy of one layer; resident memory is untouched.

## The GEGL pack (Linux, system-library gated)

```bash
sudo apt install python3-gi gir1.2-gegl-0.4    # that's the whole setup
```

No bundling, ever (DD-001): the pack finds a python interpreter that can
import Gegl — the venv's own if pygobject is installed, else the system
python3 — and every run is **spawn-per-call**: a short-lived worker
applies one operation between temp PNGs and dies, so GEGL never enters
Photoslop's resident memory.

| Filter | CLI name | Params |
|---|---|---|
| GEGL Vignette | `gegl-vignette` | `radius`, `softness` |
| GEGL Bloom | `gegl-bloom` | `strength`, `radius` |
| GEGL Pixelize | `gegl-pixelize` | `size-x`, `size-y` |
| GEGL Newsprint | `gegl-newsprint` | `period` |
| GEGL Posterize | `gegl-posterize` | `levels` |
| GEGL Motion Blur | `gegl-motion-blur` | `length`, `angle` |
| GEGL Edge Detect (Sobel) | `gegl-edge-sobel` | — |
| **GEGL Operation** | `gegl` | `operation` — any of ~200 ops + props |

Raw form: `--filter "gegl:operation=gegl:vignette radius=1.2,softness=0.5"`
— the first token is the operation, the rest `key=val` properties (ints,
floats, and strings coerce; unknown operations and properties fail with
the worker's error text).

## The GIMP bridge (escape hatch — spawn-per-call, DD-006)

With a `gimp` 3.x binary on PATH, four more filters register: **GIMP
Oilify / Softglow / Cubism** (GIMP's own GEGL operations, which plain
gegl packages don't ship) and **GIMP Script-Fu** — a raw hatch that binds
`image` and `drawable` and runs whatever you write, reaching any plug-in
or PDB procedure GIMP has installed:

```bash
photoslop-cli --allow-unsafe-plugins in.png \
  --filter "gimp-script:script=(gimp-drawable-invert drawable FALSE)" \
  --output out.png
```

**Every run spawns a fresh GIMP that exits when done** (per
[DD-006](https://github.com/CryptoJones/Photoslop/blob/main/DESIGNDECISIONS.md)
— a resident headless GIMP idles at 200–500 MB and is rejected by
design). Expect seconds per run; the bridge is the long-tail escape
hatch, not the fast path. Errors surface the batch error text; runaway
scripts are killed at a timeout.

## The contract

```python
from photoslop.filters import Filter, ParamSpec

class MyFilter(Filter):
    name = "my-filter"          # kebab-case, unique — CLI + replay identity
    label = "My Filter"         # menu text
    params = (
        ParamSpec("amount", "Amount", "int", 0, 100, 50),
        #         key       label     type  min  max  default
        ParamSpec("mode", "Mode", "choice", 0, 0, "auto", ("auto", "fast")),
        #  a "choice" ignores min/max and takes a tuple of permitted values;
        #  the dialog renders a combo box, the CLI validates membership, so a
        #  mode never has to be smuggled in as a magic integer in a spin box
    )

    def apply(self, image, params):   # QImage, dict -> edit in place
        ...
```

- `apply` edits the QImage **in place**; it receives a transient per-layer
  copy — never the resident buffer — so selections, feather blending, and
  undo happen outside the plugin (you write zero Qt UI and zero undo code).
- `params` arrives validated against your `ParamSpec`s: the GUI builds
  spinboxes (or a combo box, for `choice`) from them, the CLI parses `key=val`
  against them, and both reject out-of-range or unknown values before your code
  runs. Types are `int`, `float`, `str` and `choice`.
- Buffers are **premultiplied ARGB32**; use
  `photoslop.npimage.view_u32(image)` for a zero-copy numpy view.

## Packaging

```toml
[project.entry-points."photoslop.filters"]
my-filter = "my_package:MyFilter"
```

A complete installable reference plugin lives in
[`examples/photoslop-invert-filter/`](https://github.com/CryptoJones/Photoslop/tree/main/examples/photoslop-invert-filter)
— `pip install .` in that directory and **Invert** appears in the Filter
menu and the CLI.

For quick experiments (or tests), skip packaging:

```python
from photoslop.filters import register_filter
register_filter(MyFilter)
```

## CLI

```bash
photoslop-cli in.png --filter "sepia:amount=100" --output toned.png
photoslop-cli in.png --select 0,0,400,300 --feather 8 \
                     --filter "pixelate:size=12" --output redacted.png
photoslop-cli in.png --filter sepia --output toned.png   # defaults
```

Unknown names exit 2 listing the installed filters; parameter errors name
the offending key and its valid range.

## Memory notes (DD-001)

The framework itself holds no image memory — the registry stores classes.
Each run costs the same transient copy every built-in filter already pays.
A plugin that allocates wildly is the plugin's bug, not the host's; keep
per-pixel work chunked (see `CHUNK_ROWS` in `photoslop/adjust.py` for the
house pattern).

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

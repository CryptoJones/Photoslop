# Command Line — `photoslop-cli`

The whole engine without a window. Headless-safe (offscreen Qt), scriptable,
CI-friendly.

## Model
**Operations are pipeline steps applied in command-line order** — combinations
compose left to right, and the same option may repeat:

```bash
photoslop-cli shot.cr2 --resize 1600x1067 --auto-levels \
              --select 200,150,400,300 --feather 6 --generative-fill "wildflowers" \
              --deselect --drop-shadow 6,6,10,140 --output final.png
```

## Input & output
- **input** (positional): PNG/JPG/BMP/WebP/GIF/TIFF, `.ora`, editable-subset
  `.svg`, or camera raw
  (with the `photoslop[raw]` extra).
- `--new WxH|PRESET` — start from a blank white document instead of an input
  file: a pixel size (`800x600`) or a paper preset (`A5`, `A4`, `A3`,
  `Letter`, `Legal`) rendered at `--dpi N` (default 72). `--new A4 --dpi 300`
  gives 2480×3508.
- `--output PATH` — `.ora` keeps layers (effects and all); `.svg` writes native
  vector objects and artboards; raster extensions
  flatten (effects baked). `.avif` / `.jxl` need the `photoslop[formats]`
  extra and also work as inputs ([File Formats](file-formats.md)).
- `--export-artboards DIR` — each artboard as `<name>.png`.
- `--info` — document JSON (size, dpi, layers, effects, vector IDs/types,
  artboards) to stdout.
- `--version`.
- `--allow-large-document` relaxes only the adaptive working-memory estimate
  for trusted local files; hard geometry/archive/parser limits remain.
- `--allow-unsafe-plugins` enables native-process and third-party plugins.
- `--allow-insecure-model-http` permits plain HTTP to a non-loopback model host.

## Exit codes

Automation receives both a stable process status and a bracketed error code on
stderr (`photoslop-cli: error [io_failure]: …`).

| Exit | Error code | Meaning |
|---:|---|---|
| 0 | — | success |
| 1 | `internal_error` | unexpected engine failure |
| 2 | `invalid_input` | usage, option value, schema, or decode input error |
| 3 | `unsupported_capability` | operation/backend is not supported |
| 4 | `unsafe_operation` | trust, path, overwrite, or transport policy denied it |
| 5 | `cancelled` | operation was cancelled |
| 6 | `io_failure` | filesystem or endpoint I/O failed |

## Operations
| `--resize` `WxH` | rescale the whole image |
| `--canvas-size` `WxH` | grow/shrink the canvas (content centred) |
| `--crop` `X,Y,W,H` | crop the canvas to a rectangle |
| `--rotate` `DEG` | rotate the whole image by any angle |
| `--rotate-layer` `DEG` | rotate the target layer(s) about their centre |
| `--content-aware-scale` `WxH` | seam-carve the target layer(s) |
| `--levels` `B,W,GAMMA` | levels adjustment |
| `--auto-levels` | 0.1%-percentile auto levels |
| `--hue-sat` `H,S,L` | hue/saturation/lightness (-180..180,-100..100) |
| `--raw-develop` `"KEY=VAL,..."` | re-develop a raw input: `exposure` (EV), `temp` (K), `tint`, `highlights`, `shadows` — 16-bit transient, 8-bit out |
| `--lens-correct` | distortion + vignetting from the input's EXIF (`photoslop[lens]`) |
| `--denoise-model` `STRENGTH` | AI denoise via the model backend (`--model-url`) |
| `--assign-profile` `PROFILE` | assign an ICC profile (preset or .icc path) — metadata only |
| `--convert-profile` `PROFILE` | convert pixels to a profile (srgb, adobe-rgb, display-p3, prophoto-rgb, srgb-linear, or .icc) |
| `--proof` `PROFILE` | soft-proof simulation applied to raster output |
| `--cmyk-out` `FILE.icc` | write --output as CMYK JPEG/TIFF through this profile |
| `--point-color` `"KEY=VAL,..."` | targeted hue-band HSL: `hue` (required), `range`, `dh`, `ds`, `dl`, `uniform` — skin tones ≈ `hue=20,range=28` |
| `--color-balance` `9 INTS` | shadows,midtones,highlights r,g,b each |
| `--curves` `X:Y,...` | master curve points in 0..255 |
| `--adjust` `"KEY=VAL,..."` | Lightroom Basic sliders (temperature, tint, exposure, contrast, highlights, shadows, whites, blacks, vibrance, saturation) |
| `--gaussian-blur` `RADIUS` | gaussian blur (selection-aware) |
| `--filter` `"NAME:KEY=VAL,..."` | run a filter plugin — built-ins `sepia`, `pixelate`; the G'MIC pack (`gmic-cartoon`, raw `gmic:command=...`, …) with `photoslop[gmic]`; the GEGL pack (`gegl-vignette`, raw `gegl:operation=...`, …) with system python3-gi + gir1.2-gegl; the GIMP bridge (`gimp-oilify`, raw `gimp-script:script=...`, spawn-per-call) with a gimp binary; more via [Filter Plugins](filter-plugins.md) |
| `--unsharp` `AMOUNT` | unsharp mask, percent |
| `--tilt-shift` `C,B,T,R` | tilt-shift blur: centre,band,transition,radius |
| `--drop-shadow` `DX,DY,BLUR,ALPHA` | live drop-shadow effect |
| `--glow` `SIZE` | live outer-glow effect |
| `--stroke` `W,R,G,B` | live stroke effect |
| `--effect` `JSON` | append any structured Appearance effect; supports all ten effect types and may repeat to build an ordered stack |
| `--set-effects` `JSON_ARRAY` | replace the target layer's ordered Appearance stack |
| `--clear-effects` | remove every Appearance effect from the target layer |
| `--appearance-preset` `NAME` | apply a built-in or locally saved Appearance preset |
| `--fill-opacity` `PCT` | fill opacity (effects keep full strength) |
| `--layer` `N` | target layer index for following ops |
| `--all-layers` | apply following ops to every visible layer |
| `--select` `X,Y,W,H` | rectangular selection for region-aware ops |
| `--select-ellipse` `X,Y,W,H` | elliptical selection inscribed in the box |
| `--select-poly` `"X,Y X,Y X,Y..."` | polygon selection from three or more points |
| `--deselect` | clear the selection |
| `--clear` | erase the selection to transparency (headless Cut) |
| `--flip` `h|v` | mirror the target layer(s) |
| `--fill` `R,G,B` | fill the whole target layer with a colour |
| `--text` `"X,Y,SIZE[,R,G,B]:TEXT"` | rasterise text onto a new layer (default colour black) |
| `--text-rich` `"X,Y:<html>"` | rasterise **rich HTML** text onto a new layer — per-letter colour, font-family, bold/italic (the headless mirror of the GUI Text tool's styled editor) |
| `--shape` `KIND,X,Y,W,H,R,G,B` | rect/ellipse/line onto a schema-v1 native vector layer (direct crisp rendering, ORA fallback, re-renders on --resize) |
| `--vector-op` `JSON` | native-vector `select`, `transform`, `appearance`, `group`, `align`, `distribute`, `node`, or `boolean` operation; object IDs come from `--info` |
| `--blend-mode` `NAME` | set the target layer's blend mode |
| `--layer-opacity` `PCT` | set the target layer's opacity |
| `--content-aware-fill` | diffusion-fill the selection |
| `--feather` `RADIUS` | feather the current selection's edge |
| `--duplicate-layer` | duplicate the active layer |
| `--flatten` | collapse all layers into one |
| `--convert-smart` | snapshot target layer(s) as smart objects |
| `--restore-smart` | restore smart-object pristine pixels |
| `--add-artboard` `NAME,X,Y,W,H` | register a named export region |
| `--artboard-op` `JSON` | add/update/delete/reorder/clear named artboards through the shared undoable engine |
| `--model-url` `URL` | backend for model ops (generic HTTP adapter) |
| `--select-subject` | ask the model backend for a subject selection |
| `--generative-fill` `PROMPT` | model-paint the selection from a prompt |

Notes:
- `--layer N` / `--all-layers` set the target scope for the operations that
  follow them; `--select` / `--feather` / `--deselect` likewise gate only
  what comes after.
- `--content-aware-scale` retargets the canvas; in multi-layer documents each
  targeted layer carves by the canvas ratio.
- `--curves` points are in 0–255 space (`0:20,255:235` lifts blacks, dims
  whites).
- Model ops need `--model-url` first — see
  [Model Backends](model-backends.md) for the server contract.

## Recipes
```bash
# batch raw develop
for f in *.CR3; do photoslop-cli "$f" --auto-levels --unsharp 110 --output "${f%.CR3}.jpg"; done

# thumbnail with a watermark-ish stamp
photoslop-cli in.png --resize 400x300 --text "8,280,12,255,255,255:© CryptoJones" --output thumb.png

# multi-colour headline — each letter styled via HTML (mirror of the GUI editor)
photoslop-cli in.png --text-rich '40,40:<span style="font-family:Georgia;font-size:48pt;color:#e00">Big</span> <span style="font-size:48pt;color:#05a">Red</span>' --output headline.png

# editable text with an ordered Drop Shadow + Outline appearance stack
photoslop-cli --new 800x300 --text-rich '40,40:<span style="font-size:72pt">Photoslop</span>' \
  --effect '{"type":"drop-shadow","parameters":{"offset_x":8,"offset_y":8,"blur":10}}' \
  --effect '{"type":"outline","parameters":{"width":3,"color":[255,255,255,255]}}' \
  --output title.ora

# subject cut-out driven by your own model server
photoslop-cli photo.png --model-url http://localhost:8188/ps --select-subject \
              --feather 3 --generative-fill "clean studio background" --output out.png

# inspect an ORA without opening the GUI
photoslop-cli project.ora --info | jq '.layers[].name'

# a print-ready A4 canvas from nothing, developed entirely headless
photoslop-cli --new A4 --dpi 300 --fill 245,240,230 \
              --text "200,200,64,40,40,40:Hello from the CLI" --output poster.png
```

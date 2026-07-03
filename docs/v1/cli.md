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
- **input** (positional): PNG/JPG/BMP/WebP/GIF/TIFF, `.ora`, or camera raw
  (with the `photoslop[raw]` extra).
- `--new WxH|PRESET` — start from a blank white document instead of an input
  file: a pixel size (`800x600`) or a paper preset (`A5`, `A4`, `A3`,
  `Letter`, `Legal`) rendered at `--dpi N` (default 72). `--new A4 --dpi 300`
  gives 2480×3508.
- `--output PATH` — `.ora` keeps layers (effects and all); raster extensions
  flatten (effects baked).
- `--export-artboards DIR` — each artboard as `<name>.png`.
- `--info` — document JSON (size, dpi, layers, effects, artboards) to stdout.
- `--version`.

## Exit codes
`0` success · `2` usage or option-value errors (nothing written) · `1`
runtime failures (decode errors, unreachable backends) with a one-line
message on stderr.

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
| `--color-balance` `9 INTS` | shadows,midtones,highlights r,g,b each |
| `--curves` `X:Y,...` | master curve points in 0..255 |
| `--adjust` `"KEY=VAL,..."` | Lightroom Basic sliders (temperature, tint, exposure, contrast, highlights, shadows, whites, blacks, vibrance, saturation) |
| `--gaussian-blur` `RADIUS` | gaussian blur (selection-aware) |
| `--unsharp` `AMOUNT` | unsharp mask, percent |
| `--tilt-shift` `C,B,T,R` | tilt-shift blur: centre,band,transition,radius |
| `--drop-shadow` `DX,DY,BLUR,ALPHA` | live drop-shadow effect |
| `--glow` `SIZE` | live outer-glow effect |
| `--stroke` `W,R,G,B` | live stroke effect |
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
| `--shape` `KIND,X,Y,W,H,R,G,B` | rect/ellipse/line onto a new layer |
| `--blend-mode` `NAME` | set the target layer's blend mode |
| `--layer-opacity` `PCT` | set the target layer's opacity |
| `--content-aware-fill` | diffusion-fill the selection |
| `--feather` `RADIUS` | feather the current selection's edge |
| `--duplicate-layer` | duplicate the active layer |
| `--flatten` | collapse all layers into one |
| `--convert-smart` | snapshot target layer(s) as smart objects |
| `--restore-smart` | restore smart-object pristine pixels |
| `--add-artboard` `NAME,X,Y,W,H` | register a named export region |
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

# subject cut-out driven by your own model server
photoslop-cli photo.png --model-url http://localhost:8188/ps --select-subject \
              --feather 3 --generative-fill "clean studio background" --output out.png

# inspect an ORA without opening the GUI
photoslop-cli project.ora --info | jq '.layers[].name'

# a print-ready A4 canvas from nothing, developed entirely headless
photoslop-cli --new A4 --dpi 300 --fill 245,240,230 \
              --text "200,200,64,40,40,40:Hello from the CLI" --output poster.png
```

# File Formats

## OpenRaster (`.ora`) — the native format
Layers, offsets, opacity, blend modes (standard composite-ops), plus
Photoslop extensions as non-namespaced attributes other editors ignore:

| Attribute | Carries |
|---|---|
| `photoslop-mask` | layer mask PNG entry |
| `photoslop-clipped` | clipping-mask flag |
| `photoslop-group` | group membership |
| `photoslop-adjustment` | adjustment-layer LUT (raw `.bin` entry) |
| `photoslop-source` | smart-object pristine PNG entry |
| `photoslop-smart-filters` | recorded smart-filter stack (JSON) |
| `photoslop-effects` | live layer effects (JSON) |
| `photoslop-fill-opacity` | fill opacity |
| `photoslop-text` | text-layer parameters for re-editing (JSON: text/family/size/color) |
| `photoslop-artboards` (image element) | named export regions (JSON) |
| `photoslop-vector` | Shape/Pen geometry for re-editing (JSON) |
| `photoslop-icc` | document ICC profile (base64) |

## Raster
PNG, JPEG, BMP, WebP, GIF, TIFF open directly; Export As / `--output` writes
flattened raster (live effects baked in).

## AVIF + JPEG XL (`photoslop[formats]` extra)
`.avif` and `.jxl` open, preview, export (with the quality slider), and work
as CLI input/output once the extra is installed:

```bash
pip install "photoslop[formats]"    # Pillow ≥11 (AVIF) + pillow-jxl-plugin
```

Alpha survives both directions. Without the extra, opening or writing these
extensions shows the exact install command instead of failing — same
feature-detection pattern as camera raw. Both are quality-based lossy in
Export As (Photoslop encodes at the chosen quality; use PNG for lossless).

## Camera raw (`photoslop[raw]` extra)
NEF, CR2/CR3, DNG, ARW, RAF, ORF, PEF, RW2, NRW, SRW decode via rawpy.
Opening a raw brings up the **Raw Develop** dialog: exposure (EV), white
balance (temp/tint — 0 = camera), highlights and shadows, with a live
half-size preview. Per [DD-007](https://github.com/CryptoJones/Photoslop/blob/main/DESIGNDECISIONS.md)
the decode and tone work happen at 16-bit **transiently** — the document
layer that comes out is 8-bit. Cancel uses camera defaults. CLI:
`--raw-develop "exposure=1,temp=5500,highlights=-40"` re-develops a raw
input headlessly. Without the extra installed, opening a raw shows the
exact install command instead of failing.

### Lens corrections (`photoslop[lens]` extra)
**Filter → Lens Correction (EXIF)** (CLI: `--lens-correct`) fixes
distortion and vignetting via lensfunpy, identifying the camera and lens
from the opened file's EXIF. Clear errors when the camera or lens isn't
in the lensfun database.

### Denoise
**Filter → Denoise (Chroma)** (`--filter "denoise:strength=40"`) is the
fast local baseline — luma untouched, chroma smoothed. **Filter → Denoise
(Model)** (`--denoise-model 40` with `--model-url`) routes to any AI
denoiser through the model-backend contract (`POST {base}/denoise`) —
the heavy lifting and its memory stay on the backend (DD-009).

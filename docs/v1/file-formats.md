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
NEF, CR2/CR3, DNG, ARW, RAF, ORF, PEF, RW2, NRW, SRW decode via rawpy with
camera white balance into a normal document. Without the extra installed,
opening a raw shows the exact install command instead of failing.

# Photoslop for iPadOS

Photoslop v1.30.0 includes an iPad-native edition targeting iPadOS 17 and newer.
It lives in `ipados/` and uses SwiftUI, UIKit, and PencilKit. This is a native
client rather than a repackaging of the desktop Python process: Qt supports
iOS, but Qt for Python does not currently provide a supported iOS deployment
path.

## Editing workflow

- Draw with Apple Pencil using the Pen or bitmap Eraser. PencilKit supplies
  pressure and predicted-touch handling. Turn on **Finger** to draw with touch;
  otherwise one finger pans and two fingers pinch to zoom.
- Set ink color and brush width from the bottom tool strip.
- Use the layer sidebar to add, duplicate, rename, show/hide, change opacity,
  reorder, merge down, clear, or delete raster layers.
- Open an image from Files or Photos. Imports create a document at the image's
  native pixel dimensions.
- Create, open, autosave, and reopen layered `.photoslop` package documents.
  The package preserves canvas geometry, stable layer IDs/order, names,
  visibility, opacity, raster PNGs, the active layer, and PencilKit strokes.
- Undo and redo drawing, layer lifecycle/reordering, visibility, opacity,
  renaming, clearing, imports, and document replacement with the toolbar or
  `Command-Z` / `Shift-Command-Z`.
- Export a flattened PNG through the iPadOS document picker. The exported image
  includes every visible raster layer and PencilKit drawing at its layer
  opacity.
- Standard document-browser New/Open/Save behavior is available with a hardware
  keyboard; `Shift-Command-E` exports PNG.

Compositing, merge rendering, and PNG export run outside the main actor. A
generation check prevents an older background render from replacing a newer
edit. iPad documents are capped at 16,384 px per side, 100 million pixels,
2,048 layers, 256 MiB per layer payload, and 1 GiB per project package.

## `.photoslop` package layout

```text
Example.photoslop/
  manifest.json
  layers/
    <stable-layer-uuid>/
      image.png
      drawing.data
```

The versioned manifest is the source of layer order and metadata. Opening a
package validates its schema, UUID uniqueness, dimensions, counts, payload
sizes, layer image geometry, opacity, and PencilKit drawing data before the
document is installed.

## Build an iPad device bundle

Requirements:

- macOS with Xcode 15 or newer and the iOS platform installed
- XcodeGen 2.46.0. CI downloads the reviewed release archive and verifies SHA-256
  `4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806`;
  local developers may install that version with their preferred package manager.

From the repository root:

```bash
./scripts/build-ipados.sh
```

The script regenerates `ipados/Photoslop-iPadOS.xcodeproj`, builds the arm64
device app with signing disabled, and writes
`ipados/dist/Photoslop-iPadOS-unsigned.zip`. CI performs the same build and
compiles/runs the iPad simulator tests. `XCODEGEN` may point the script at an
executable; CI uses that hook for the downloaded, checksum-verified binary.

To run on a physical iPad, generate the project, open it in Xcode, select the
`PhotoslopIPad` target, choose your Apple Developer team, and run on the paired
device. TestFlight and App Store distribution require the maintainer's Apple
distribution identity and provisioning profile; those credentials are never
stored in this repository or in release artifacts.

## Initial-edition boundary

The iPad edition currently covers persistent layered raster/PencilKit painting,
image import, document-wide undo, and flattened PNG export. The desktop edition
remains the authoritative home for OpenRaster round trips, selections,
adjustments, filters, appearance effects, editable vectors/text, automation,
CLI, and MCP. An unsigned GitHub artifact is a reproducible developer build,
not an App Store-signed IPA.

Proudly Made in Nebraska. Go Big Red! 🌽 https://xkcd.com/2347/

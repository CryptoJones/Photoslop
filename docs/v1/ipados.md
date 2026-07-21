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
- Export a flattened PNG through the iPadOS document picker. The exported image
  includes every visible raster layer and PencilKit drawing at its layer
  opacity.
- `Command-N`, `Command-O`, and `Command-S` are available with a hardware
  keyboard.

## Build an iPad device bundle

Requirements:

- macOS with Xcode 15 or newer and the iOS platform installed
- XcodeGen (`brew install xcodegen`)

From the repository root:

```bash
./scripts/build-ipados.sh
```

The script regenerates `ipados/Photoslop-iPadOS.xcodeproj`, builds the arm64
device app with signing disabled, and writes
`ipados/dist/Photoslop-iPadOS-unsigned.zip`. CI performs the same build and
compiles/runs the iPad simulator tests.

To run on a physical iPad, generate the project, open it in Xcode, select the
`PhotoslopIPad` target, choose your Apple Developer team, and run on the paired
device. TestFlight and App Store distribution require the maintainer's Apple
distribution identity and provisioning profile; those credentials are never
stored in this repository or in release artifacts.

## Initial-edition boundary

The iPad edition currently covers layered raster painting, image import, and
flattened PNG export. The desktop edition remains the authoritative home for
OpenRaster round trips, selections, adjustments, filters, appearance effects,
editable vectors/text, automation, CLI, and MCP. An unsigned GitHub artifact is
a reproducible developer build, not an App Store-signed IPA.

Proudly Made in Nebraska. Go Big Red! 🌽 https://xkcd.com/2347/

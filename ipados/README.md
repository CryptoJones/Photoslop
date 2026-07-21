# Photoslop for iPadOS

The iPad-native editor uses SwiftUI `DocumentGroup` and a versioned
`.photoslop` package document. It preserves layered raster images and PencilKit
strokes, participates in iPadOS autosave/open-in-place, and supports
document-wide undo/redo. Composite previews and PNG exports render off the main
actor.

The native iPadOS 17+ application is generated from `project.yml` with
XcodeGen. Source lives in `Photoslop/`; XCTest coverage lives in
`PhotoslopTests/`.

```bash
brew install xcodegen
xcodegen generate
open Photoslop-iPadOS.xcodeproj
```

For a reproducible unsigned arm64 build from the repository root, run
`./scripts/build-ipados.sh`. Physical-device, TestFlight, and App Store builds
must be signed with an Apple Developer team in Xcode.

The full feature and distribution notes are in
[`docs/v1/ipados.md`](../docs/v1/ipados.md).

Proudly Made in Nebraska. Go Big Red! 🌽 https://xkcd.com/2347/

# Photoslop for iPadOS

Photoslop v2.18.4 includes an iOS-native edition targeting iPadOS and iOS 17 and
newer. It is a universal app: iPad and iPhone ship in one binary from `ipados/`,
built with SwiftUI, UIKit, and PencilKit. This is a native
client rather than a repackaging of the desktop Python process: Qt supports
iOS, but Qt for Python does not currently provide a supported iOS deployment
path.

## iPhone and iPad

One binary serves both, adapting to the horizontal size class rather than the
device name, so an iPad in a narrow Split View gets the phone layout too.

- **Regular width** keeps the layer list in a sidebar beside the canvas, and
  every document action on the navigation bar.
- **Compact width** moves the layer list to a sheet reached from **Layers**,
  because `NavigationSplitView` collapses its sidebar into a pushed column
  there, and reaching the layers would otherwise navigate away from the
  drawing.
- A phone's navigation bar holds three controls beside the document title, so
  the compact layout picks them rather than leaving the choice to UIKit:
  **Layers**, a **More Actions** menu holding New, Canvas Size, Resize Document,
  Crop, Resize Layer, the text actions, Import Image, and About, and
  **Export**. Undo and redo move
  to the leading edge of the tool strip, which never has to be scrolled to.
- The tool strip narrows its brush picker and width slider at compact width and
  scrolls horizontally if it still does not fit.

CI runs the simulator suite on both an iPad and an iPhone so neither layout
regresses unnoticed. Toolbar reachability is covered by XCUITest rather than
the unit suite: whether a control survives a real navigation bar is a question
only a running app can answer.

The XCUITests run with `-retry-tests-on-failure -test-iterations 2`, down from
three, and what the flag covers has changed completely.

The suite used to fail a different test on most runs, which was read as harness
raciness on the evidence that fifteen consecutive launches inside one test method
never flaked. That reading was wrong. **Six** causes were hiding behind the flag,
and every one of them that belonged to this project is now fixed rather than
absorbed:

- **A navigation bar over its budget.** An iPad mini in portrait is 744pt and
  reports the *regular* size class, so it took the iPad layout — nine bar items,
  eleven once a text layer made Edit Text and Move Text appear. UIKit collapsed
  the trailing group behind an unlabelled chevron and **Export Image left the
  bar**, which is [#227](https://github.com/CryptoJones/Photoslop/issues/227)
  again one size class up. The test that hit it was never the one that failed:
  the helpers reach Export through a query that does not care whether a button is
  on the bar or in the system overflow, so the run carried on and the *next* test
  timed out on "the editor never came up" while the editor had been up the whole
  time. That is what made the failure appear to move around.
- **Shared state.** `DocumentGroup` keeps every document a test creates, so a run
  ended with "Untitled 1" through "Untitled 15" behind it.
  `-PhotoslopFreshDocumentStore` empties the directory at launch.
- **A racing assertion.** The photo-layer test read `cells.count` once, straight
  after the layer list appeared, while the decode it counts is asynchronous.
- **Queries too expensive to snapshot.** Between Create Document and the editor
  the system document browser is on screen — another process's hierarchy, and a
  large one. `.firstMatch` stops at the first hit instead of resolving all of it.
- **Cold start charged to an arbitrary test.** A freshly booted simulator
  installing the app and creating its first document took longer than the
  90-second wait, and whichever class sorted first paid for it. That path now
  runs once in a warm-up holding no assertions — a warm-up must not be able to
  fail a test.
- **The canvas-size question asked twice.** Reopening a still-blank document asks
  again, which is documented behaviour; emptying the store made more runs start
  from a genuinely new document and meet it. The helper answers until the
  question stops being asked.

With all six fixed the suite passes with **no retries at all** on erased
simulators — an iPad mini (A17 Pro) and an iPhone 17 Pro, 13 UI and 59 unit tests
green on each — and the iPad leg has passed on CI with none.

What the two iterations still cover is not ours to fix: the XCTest daemon
occasionally fails to bring up a UI-testing session at all —

```
Failed to initialize for UI testing: XCTDaemonErrorDomain Code=19
"Failed call to AXDisableAccessibilityOnTermination: kAXErrorCannotComplete"
```

— and **zero tests execute** when it does. No app is involved, there is no
assertion to wait on, and nothing in test code can reach it; retrying the
invocation is the only remedy available. Keep the number at two: the lower it is,
the less room there is for the next real defect to hide as flakiness, which is
what it was doing to #227.

## Editing workflow

- Draw with Apple Pencil using the Pen, Pencil, Marker, or bitmap Eraser.
  PencilKit supplies pressure and predicted-touch handling. Turn on **Finger**
  to draw with touch; otherwise one finger pans and two fingers pinch to zoom.
- Brushes differ in which Apple Pencil inputs they read. Pen varies with force
  alone, so tilting the Pencil does not change its stroke. Pencil and Marker
  also read the Pencil's altitude and azimuth and broaden as it is laid over,
  which is the tool to reach for when shading. Pen remains the default.
- Set ink colour, stroke opacity and brush width from the bottom tool strip.
  Colour and opacity share one control — a swatch showing the ink as it will
  actually paint, opening a popover with both. They share a slot deliberately:
  the strip is budgeted for an iPad mini in portrait, where it has overflowed
  before and put the ink controls off the edge of the screen (#246), so its item
  count may not grow.
- **Add Text** puts text on its own layer, on top of the stack, centred on the
  canvas and ready to move. The anchor is the text's top-left, the same
  convention as `photoslop-cli --text "X,Y,SIZE[,R,G,B]:TEXT"`.
- Text stays editable. **Edit Text** reopens the words, size, and colour of the
  selected text layer and re-renders it in place, keeping its position in the
  stack along with its visibility and opacity. **Move Text** drags it to a new
  spot, and the whole drag is a single undo step rather than one per touch.
  Drawing is suspended while either mode is armed, so a touch positions rather
  than paints.
- The words, size, colour, and anchor are stored in the document, which is what
  makes that possible. Documents saved before this shipped still open; they
  simply contain no text layers.
- **New** offers a starting canvas size: Standard, Square, HD, 4K UHD, A4 and
  US Letter at 300 DPI, Photo 6x4, or a custom size. **Canvas Size** applies the
  same choice to the open document, padding or cropping around centred content
  exactly as `photoslop-cli --canvas-size` does, and is undoable. Reach for it to
  change a size already in use, or after cancelling the question a new document
  asks.
- **Resize Document** takes the same size choice and *scales* to it, resampling
  every layer, its strokes and its text rather than padding around them. It
  mirrors `photoslop-cli --resize WxH`. The three size operations are distinct
  and none replaces another — see
  [Three ways to change a size](#three-ways-to-change-a-size).
- **About Photoslop** introduces the app the way the desktop edition does: Le
  Basilisk, the name with no platform attached, and the same one-line
  description, over the licence and repository link. It also reports the
  marketing version and build number, and the open document's canvas size and
  layer count. The sheet opens at half height and can be dragged up.

  The mascot is drawn in code by `photoslop/appicon.py` and has no asset file, so
  `scripts/render-ios-mascot.py` exports the QPainter original into
  `Mascot.imageset` at three scales. Re-run it after changing `draw_mascot`; the
  `quality` CI job fails if the committed asset has drifted from the code. The
  check compares decoded pixels with a tolerance rather than PNG bytes: Qt
  antialiases and packs PNGs slightly differently on Linux than on macOS, so a
  byte comparison fails on the CI runner for an asset that is perfectly current. The
  app icon is not reused for this: it is flattened onto white, which would show
  as a white box in a grouped list and in dark mode.
- Use the layer sidebar to add, duplicate, rename, show/hide, change opacity,
  reorder, merge down, clear, or delete raster layers.
- Open an image from Files or Photos. An import is fitted to the canvas the
  document already has, scaled to fit and centred — the size chosen when the
  document was created is the size it keeps. Importing used to take the canvas
  from the image, so a photo dropped into a 1920x1080 document silently made it
  4032x3024 — that is how a photo *becomes* a document. To put
  one *into* the document already open, see
  [Importing a photo as a layer](#importing-a-photo-as-a-layer) below.

- Creating a document asks for its canvas size before you draw. The question
  cannot ride on a flag set when the document is built: creating one writes it to
  disk and reopens it through `init(configuration:)`, so anything set in `init()`
  belongs to a store that never reaches the screen. The opening path recognises
  an untouched new document instead — default canvas, one unedited `Background`
  layer — which is what survives that round trip. Reopening a still-blank
  document therefore asks again; Cancel keeps the size.
- Create, open, autosave, and reopen layered `.photoslop` package documents.
  The package preserves canvas geometry, stable layer IDs/order, names,
  visibility, opacity, raster PNGs, the active layer, and PencilKit strokes.
  Documents are visible in Files under **On My iPhone/iPad → Photoslop**; the
  app declares `UIFileSharingEnabled` alongside
  `LSSupportsOpeningDocumentsInPlace` so that a device with no other local
  provider — a fresh one, or one not signed into iCloud Drive — still has
  somewhere to save.
- Undo and redo drawing, layer lifecycle/reordering, visibility, opacity,
  renaming, clearing, imports, and document replacement with the toolbar or
  `Command-Z` / `Shift-Command-Z`.
- Export a flattened image through the iOS document picker. **Export** names
  the file and picks PNG, JPEG, HEIC, TIFF, GIF, or BMP, with a quality slider
  for the lossy two; formats without an alpha channel are flattened onto white
  first. The exported image includes every visible raster layer and PencilKit
  drawing at its layer opacity.
- Standard document-browser New/Open/Save behavior is available with a hardware
  keyboard; `Shift-Command-E` exports.

Compositing, merge rendering, and PNG export run outside the main actor. A
generation check prevents an older background render from replacing a newer
edit. iPad documents are capped at 16,384 px per side, 100 million pixels,
2,048 layers, 256 MiB per layer payload, and 1 GiB per project package.

### Cropping to a region you choose

**Crop…**, beside Canvas Size in the actions menu, puts a rectangle over the
canvas whose edges and corners drag. The area outside it dims, thirds guides sit
inside it, and the resulting pixel size shows while you drag — cropping to *a
custom canvas size* only means something if you can see the size you are landing
on. **Crop** applies it as one undo step; **Cancel** leaves the document
untouched.

See [Three ways to change a size](#three-ways-to-change-a-size) for how this
differs from Canvas Size and Resize Document.

The aspect control locks the rectangle's shape — **Free**, **Original**, **1:1**,
**3:2**, **4:3** or **16:9**. Free is the default because a custom size is the
point; the presets are what you reach for when the destination has a shape.
Locking one reshapes the rectangle immediately rather than waiting for the next
drag, and a locked drag keeps the corner opposite the handle still, so the
rectangle does not slide out from under your finger while it corrects itself.

Handles are drawn small and touched large: the hit area is 44pt though the
painted handle is half that, because a crop handle sits under a fingertip. It
stays 44 *points* at any zoom: the box is drawn in document pixels and its
chrome is divided by the zoom scale, so handles do not become postage stamps
when you zoom in to place an edge exactly.

Drawing is suspended while the box is up, so a drag positions the rectangle
rather than painting a stroke beneath it — but **navigation is not**. Pinch to
zoom and two fingers to pan work throughout, which is the point: choosing a crop
edge precisely is exactly when you want to zoom in. One finger belongs to the
box, two fingers to the canvas, the same division that already applied while
drawing.

### Three ways to change a size

They are easy to confuse and they do different things to the picture:

| Action | The canvas | The content |
|---|---|---|
| **Canvas Size** | becomes the chosen size | unchanged in pixels, padded or trimmed around centre |
| **Crop** | becomes the chosen region | unchanged in pixels, everything outside discarded |
| **Resize Document** | becomes the chosen size | resampled — nothing lost, nothing padded |

Canvas Size and Crop share one implementation, differing only in whether the
origin is centred or chosen. Resize Document is the sibling that resamples. All
three move a layer's pixels *and* its PencilKit strokes *and* its text anchor
together, which is the part that is easy to forget and the reason they are not
three separate code paths.

### Placing and resizing a layer

A single imported picture arrives at **its own size**, centred, and stops in a
placement box before it is committed. The box's corners and edges drag, the
resulting pixel size shows while you drag, and **Constrain proportions** starts
on — one tap releases it, because a non-proportional resize distorts a picture
and is never what anyone wants by accident. **Done** applies it as one undo
step; **Cancel** removes the layer, since declining the placement declines the
import.

The same box is reached again through **Resize Layer…** for a layer that came in
the wrong size, and through **Fit Text…** for a text layer, where dragging the
box scales the type to span it and moves the anchor to its corner.

A layer imported in this session keeps its original pixels as a source, so
resizing it repeatedly resamples from the original rather than compounding
losses. A layer restored from a saved document has no separate source yet — see
DD-011 — so its box opens on the whole canvas and its own pixels are the source.

Several pictures chosen at once still arrive scaled to fit the canvas: placing
each of twenty photos by hand is not a workflow anybody wants.

The box may be dragged past the canvas edge, which is how you fill a canvas with
the middle of a photograph. A crop rectangle may not — you cannot keep a region
of a picture that is not in the picture.

Cropping shares its implementation with Canvas Size — the same operation with a
chosen origin rather than a centred one. That is deliberate: a layer is pixels
*and* PencilKit strokes *and* possibly a text anchor, all of which have to travel
together, and a second code path would be a second chance to forget one. The
result agrees with `photoslop-cli --crop X,Y,W,H` for the same rectangle.
### Importing from Photos or from Files

**Import Image…** asks where the picture is coming from before it asks which
one, offering **Photos** and **Files** with Photos the default. It reached the
Files hierarchy only, which on a phone or an iPad is where pictures usually are
not — the action named "import an image" led to the one place they generally are
not kept. It is the same segmented control export uses for its destination,
asking the opposite question.

**New Layer from Image**, on the layer list, asks the same question, so a layer
can now come from a file as well as from the library.

### Exporting to Files or to the photo library

**Export** offers a destination: **Files** or **Photos**. Both use the same
format, quality and rendering choices, and both are handed the same encoded
bytes, so the two cannot drift into producing different pictures from the same
settings.

Photos is the one a finished picture usually wants on a phone — it is what the
camera roll and the share sheet mean by "my photos". Before this, export went
only through `fileExporter`, which presents a document picker and can reach only
the Files hierarchy; getting a picture into the library meant saving it to Files
and importing it from the Photos app by hand.

Two details are deliberate. The app asks for **add-only** access
(`PHAccessLevel.addOnly`) rather than full library access, because saving an
export needs permission to add one asset and nothing more — asking for the whole
library would be asking to read every photo you own in order to perform a write.
And the format list **narrows** when Photos is chosen: PNG, JPEG and HEIC are
what the library reliably accepts, while BMP, GIF and TIFF are not, and a
rejected asset fails *after* the render with an opaque error rather than at the
moment of choosing.

Saving to Photos confirms that it worked. The picture leaves for another app's
library and nothing on the editor screen changes, so without the confirmation a
successful export is indistinguishable from having done nothing.

There is no headless mirror for this one, and that is a parity ruling rather
than an omission: the photo library is an iOS facility with no desktop or CLI
equivalent. `photoslop-cli --output` writes a file, which is what the Files
destination already does.

### The launch screen

Before any document exists, the app shows its own launch scene rather than
dropping straight into a file browser. It carries a small identity bar — the
mascot, the version and build, the licence, and a link to the repository — above
the system's own title and **Create Document** button.

That bar is deliberately in the margin. The system owns the middle of this scene:
its title, its actions, and the document browser below. A block placed in the
background accessory renders behind the browser's sheet and is never seen, and
one placed at the bottom of the overlay is covered by that same sheet — both were
tried. The strip above the card is what the system leaves free.

The version, licence and repository link are here rather than only in About
because this is the first screen a person meets, and for App Review it is the
screen that has to say what the app is.

### Importing a photo as a layer

**New layer from photo**, beside Add / Duplicate / Merge in the layer list,
brings photos into the document you already have open. Take a multiple
selection and each photo becomes its own layer on top of the stack, in one undo
step for the whole selection. On a phone the picker is raised from the layer
list itself.

This is a separate action from opening an image, which is how a photo *becomes*
a document — importing used to replace the whole document, so a second image
threw the first away and a double exposure was impossible. Two clearly separate
actions beat one that guesses from context which was meant, which is the same
ruling the desktop **Layer ▸ New Layer from Image…** and the CLI's
`--import-layer` follow ([Layers](layers.md#new-layer-from-an-image-file)).

Photos are scaled to fit the canvas and centred, never cropped — **this is the
one place the iOS edition deliberately differs from the desktop**, which keeps
the source at native size and lets it overhang. Fitting works in both
directions: an image smaller than the canvas is scaled up to fill it rather than
sitting small in the middle. That reverses an earlier ruling which left small
images alone because upscaling invents detail. True, but it made one action
behave two ways depending on the size of the photo picked, which is harder to
predict than a rule that always fits. A `.photoslop` layer image has
to be exactly canvas-sized or `ProjectArchive.snapshot` refuses it and the
document cannot be saved at all, so a mismatched aspect ratio must lose either
the parts outside the canvas or the space at the edges. Transparent edges are
recoverable and cropped pixels are not, and a portrait photo dropped into a
landscape canvas would lose most of itself to a crop. Images smaller than the
canvas keep their own size rather than being stretched, because upscaling
invents detail that was never captured.

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
device. The device must be registered in the developer account and must have
Developer Mode enabled (Settings, then Privacy & Security, then Developer Mode)
before an installed development build will launch.

## TestFlight distribution

Tag builds upload to App Store Connect automatically. The `testflight` job in
`.github/workflows/ipados.yml` runs after the unsigned validation build on any
`v*` tag, and delegates to `scripts/publish-ipados-testflight.sh`, which
archives the Release configuration, exports an App Store `.ipa`, validates it,
and uploads it with `altool`.

Signing credentials live in the `testflight` GitHub environment, never in this
repository or in release artifacts:

| Secret | Contents |
| --- | --- |
| `IOS_DISTRIBUTION_CERTIFICATE_P12` | Base64 of the Apple Distribution `.p12` |
| `IOS_DISTRIBUTION_CERTIFICATE_PASSWORD` | Export password for that `.p12` |
| `APP_STORE_CONNECT_KEY_ID` | App Store Connect API key identifier |
| `APP_STORE_CONNECT_ISSUER_ID` | App Store Connect API issuer identifier |
| `APP_STORE_CONNECT_PRIVATE_KEY` | Base64 of the API key `.p8` |

The API key needs the **Admin** role so `-allowProvisioningUpdates` can maintain
the App Store provisioning profile without a committed profile. App Manager is
not sufficient: cloud signing fails with `Cloud signing permission error` and
`No profiles for 'io.ronin48.photoslop.ipad' were found`. An API key's access
cannot be edited after it is generated, so a key with the wrong role has to be
replaced rather than upgraded.

Because `check-version.py` derives `CURRENT_PROJECT_VERSION` from the marketing
version, each upload consumes exactly one build number. App Store Connect
rejects a repeated build number, so re-publishing requires a version bump
rather than a re-run of the same tag.

Once a build finishes processing, internal testers on the App Store Connect
team receive it immediately. External testers, up to 10,000 by email or public
link, require Beta App Review on the first build of a version.

## Initial-edition boundary

The iPad edition currently covers persistent layered raster/PencilKit painting,
image import, document-wide undo, and flattened image export. The desktop edition
remains the authoritative home for OpenRaster round trips, selections,
adjustments, filters, appearance effects, editable vectors/text, automation,
CLI, and MCP. An unsigned GitHub artifact is a reproducible developer build,
not an App Store-signed IPA.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

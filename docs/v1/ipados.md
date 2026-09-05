# Photoslop for iPadOS

Photoslop v2.32.0 includes an iOS-native edition targeting iPadOS and iOS 17 and
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

- Draw with Apple Pencil using the Pen, Pencil, Marker, or bitmap Eraser, or
  fill with the **Bucket**. PencilKit supplies pressure and predicted-touch
  handling. Turn on **Finger** to draw with touch; otherwise one finger pans
  and two fingers pinch to zoom.
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
- **Effects…** opens a text layer's appearance stack (#316): drop shadow, inner
  shadow, outer and inner glow, outline, colour and gradient overlay, and bevel
  and emboss, each with the desktop's parameters under the desktop's names
  (colour, offset, blur, spread, angle, depth, and so on), plus opacity and a
  blend mode per effect. Add stacks a new effect; drag to reorder, swipe to
  remove, and the toggle on each row disables it without losing its settings.
  The **Presets** section is the desktop's built-in set — Lifted, Sticker,
  Neon, Letterpress, Chrome, Soft Focus — and picking one replaces the stack,
  as it does there. The canvas previews every change live; **Apply** commits
  the whole edit as one undo step and **Cancel** puts the layer back.
- Effects are never baked into the layer. They are re-drawn from the type each
  time it is composited, so Edit Text, Fit Text and Move Text keep them; they
  are included in Flatten, in every export, and in the document preview; and
  they round-trip through the `.photoslop` package as the same JSON the
  desktop writes into an OpenRaster `photoslop-effects` attribute, so the
  stack is one vocabulary across the CLI (`--drop-shadow`, `--glow`,
  `--stroke`, `--effect`, `--set-effects`), the desktop, and the app. Two
  desktop kinds, Gaussian blur and feather, are kept with the document but not
  drawn on iOS yet; the app says so on their page.
- On iPhone the button lives inside the text submenu, so the top-level tool
  menu does not gain an item (#313).
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
- The **Bucket** fills the region of similar colour under a tap with the ink
  as the swatch shows it, colour and opacity both, on the active layer, as one
  undo step. Its one option is **Tolerance** (0–255, 32 to start, the desktop's
  default), which takes the width slider's slot on the strip. See
  [Paint bucket](#paint-bucket).
- The **Magic Wand** selects the region of similar colour under a tap — the
  flood with the write swapped for a mask — and the marching ants show what is
  selected. Its options are the same **Tolerance** slider, a **Contiguous**
  toggle (off is the desktop's colour-range mode) and a combine mode that
  stands in for the desktop's Shift and Alt clicks. The **Select** menu holds
  Select All, Deselect, Invert Selection and **Delete Selection**, which is
  how a background comes off a photo: wand it, delete it. The bucket stays
  inside the selection. See [Magic wand and selections](#magic-wand-and-selections).
- The **Eyedropper** sets the ink to the colour under a tap, so the next stroke
  paints with what is already on the canvas. It samples the merged composite
  rather than the active layer, exactly as the desktop's Eyedropper (`I`) does.
  It has no width and no tolerance — it reads one pixel — and the ink swatch
  stays on the strip while it is armed, because that is where the sampled
  colour lands. See [Eyedropper](#eyedropper).
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
### Eyedropper

Pick **Eyedropper** from the tool palette and tap the canvas. The colour under
the tap becomes the ink, and the swatch on the strip shows it immediately —
switch back to a brush and the next stroke paints with it.

It samples the **merged composite**, not the active layer. That is the desktop's
`Document.sample_color` behaviour and it is the only one that makes sense for a
picker: the pixel you point at usually belongs to a layer below the one you are
painting on, and the whole reason to reach for the tool is to pick up a colour
you can see. A layer that is hidden, or at zero opacity, is not on screen and so
is not sampled; a half-opaque layer samples as the blend the canvas actually
drew.

Two rules, both stated so they are not surprises:

- **A transparent pixel is ignored.** Tapping a hole in the picture leaves the
  ink alone rather than arming an invisible colour, which is what the desktop
  tool does with the same tap.
- **There is no Shift for the background.** The desktop keeps a foreground and
  a background swatch and Shift-clicks into the second; iOS has a single ink,
  so the tool sets that. Nothing is lost, because nothing on iOS reads a
  background swatch.

Sampling costs one pixel, not one canvas. `EditorStore.sampleColor` composites
a 1x1 context through the same `drawComposite` pass that draws the whole canvas
— the same layer order, opacities, effects and strokes — with the sampled point
translated onto that single pixel. Two things follow: the colour reported cannot
drift from the colour shown, and sampling a 4000x3000 document allocates four
bytes rather than the 48 MB a flatten would (#309, #348-#354).

### Paint bucket

Pick **Bucket** from the tool palette and tap the canvas. The pixels connected
to the tap whose colour is within **Tolerance** of the tapped pixel take the
ink — the same colour and opacity the swatch shows, premultiplied the way the
desktop bucket premultiplies its foreground. A finger tap fills whether or not
**Finger** drawing is on: the bucket is a tap tool, so there is no stroke for a
Pencil to own. One finger still pans and two fingers still pinch.

The fill is the desktop's fill, not a look-alike. `FloodFill.swift` is a port
of `photoslop.npimage.flood_fill` — the same iterative scanline algorithm, the
same per-channel tolerance against the tapped pixel (alpha included, on
premultiplied values), the same 4-connectivity, so a one-pixel outline holds
and a diagonal gap does not leak. The proof is a fixture the desktop
implementation generates (`scripts/gen-flood-fill-fixture.py`) and the iOS
tests compare against word for word, at tolerance 0, a mid tolerance and an
enclosed region. Contiguous fill only: the desktop bucket has no colour-range
mode either (that is the wand's — see
[Magic wand and selections](#magic-wand-and-selections)).

Two rules, both stated so they are not surprises:

- **Text layers are refused.** A text layer's pixels are re-rendered from its
  words every time Edit Text, Fit Text or Move Text runs, so a fill on one would
  vanish at the next edit. The app says so and leaves the layer alone; fill a
  paint layer beneath it instead.
- **Strokes become pixels.** The fill has to see the outline you drew, so the
  layer's PencilKit strokes are baked into its bitmap before the fill runs, as
  Merge Down already does. A placed photo's pristine source is dropped for the
  same reason: a later resize re-rendered from the source would throw the fill
  away. Undo puts all of it back.

With a selection up, the fill stops at its edge, and a tap outside the
selection fills nothing — the desktop bucket's `sel_mask` behaviour. With
nothing selected a fill runs to the edge of its region.

#### The pixel seam and memory

The bucket is the first user of `PixelBuffer` (#324, DD-013), the seam every
pixel operation on iOS goes through: it borrows a layer's pixels as a
premultiplied ARGB32 buffer — the byte-for-byte equivalent of what the
desktop's `view_u32` reads from a `QImage` — hands them to an operation, and
puts the result back as the layer image in one undo step.

A buffer costs one canvas-sized bitmap (12 MiB on the standard canvas), and the
result is a second one until the old image is released to undo. The store
budgets that through the same free-memory check import makes before it decodes
(#354) and shows the same refusal rather than risking a jetsam kill. Inside an
operation, work runs in bands of 256 rows — the desktop's `CHUNK_ROWS` — each
in its own autorelease pool, so a per-row transient is sized to a band rather
than the picture. The flood fill itself allocates only its two masks, two bytes
per pixel, as the desktop version does.

### Magic wand, marquee, lasso and selections

Three tools make a selection. Pick **Magic Wand** from the tool palette and tap the canvas. The pixels whose
colour is within **Tolerance** of the tapped pixel become the selection, and
marching ants — a white hairline under a walking black dash, one screen point
wide at every zoom — trace its edge. The wand is the bucket's flood with the
write swapped for a mask: the same `FloodFill.swift`, the same fixture-proven
parity with `photoslop.npimage.flood_mask` and `global_mask`, so a wand on
iOS selects exactly the pixels the desktop wand would. Selecting is not an
undo step, as it is not on the desktop; the selection simply changes.

The wand reads the active layer as the canvas shows it, strokes included, and
writes nothing, so it works on a text layer too. Its options sit in a menu
beside the Tolerance slider:

- **Contiguous** (on to start) limits the selection to the pixels connected
  to the tap. Off, every pixel in the layer within tolerance is selected
  wherever it is — the desktop's colour-range toggle.
- **New Selection**, **Add to Selection** and **Subtract from Selection** say
  how the tapped region meets the selection already there. They are the
  desktop's plain, Shift and Alt clicks, made into a choice a finger can
  make, and the menu's icon shows which is current.

**Rectangle Select** and **Lasso Select** (#370) sit beside the wand and share
its New / Add / Subtract option. Drag a marquee, or draw a loop; the shape is
drawn as a hairline in the ants' colours while the finger moves and becomes
the selection when it lifts — the desktop rebuilds the selection on every
mouse move, which would be a mask of the canvas per sample here. A lasso is
closed back to its first point and filled under the desktop's odd-even rule,
so a loop that crosses itself leaves the crossed part unselected, exactly as
`QPainterPath` fills it: the rasteriser is an emulation of Qt's, and
`scripts/gen-selection-fixture.py` writes the desktop's masks as a Swift
fixture the iOS masks are asserted against pixel for pixel. A drag under two
pixels, or a lasso of fewer than three points, is the desktop's click: it
deselects under New Selection and does nothing under Add or Subtract. A tap
that never moves does nothing at all — Deselect is in the Select menu. Both
tools take no ink and, like the wand, work on a text layer.

### Cut, Copy and Paste

While a selection is up, **Cut**, **Copy**, **Paste** and **Delete Selection**
appear together at the left of the tool strip, next to Undo and Redo, and go
away when the selection does (#374). That is the one-tap route, and it is
where these belong: making a selection is a modal act, and on a phone the
Select menu is inside **More**, which is a system menu that cannot show what
is under it — Delete Selection shipped there in 2.22.0 and went unfound. The
same four commands stay in the Select menu, with ⌘X / ⌘C / ⌘V for a keyboard.

- **Copy** puts the selected pixels of the active layer on the system
  pasteboard, cropped to the selection's bounds. With nothing selected it
  copies the whole layer. A feathered selection copies with its soft edge, so
  what you paste back is what you cut, ramp and all.
- **Cut** is Copy and Delete Selection as a single undo step. It needs a
  selection; text layers stay editable and refuse it, as they refuse the
  bucket.
- **Paste** puts the pasteboard's image on a new layer above the active one,
  one undo step. A copy made in this app goes back where it came from; a
  screenshot, or an image copied in another app, lands at the top-left. All
  three work the same whichever tool made the selection.

The **Select** menu (under **More** on a phone, on the toolbar on an iPad)
holds the rest of the desktop's selection commands:

- **Select All** (⌘A) and **Deselect** (⌘D).
- **Invert Selection** (⌘⇧I) swaps selected and unselected. With nothing
  selected it is Select All, so the ants never simply vanish.
- **Delete Selection** (Delete) clears the selected pixels of the active layer
  to transparent, one undo step. This is the workflow the wand exists for:
  tap the background, delete it, and the subject is left on transparency
  ready to export as PNG or to sit over another layer. Text layers are
  refused for the reason the bucket refuses them: their pixels are re-rendered
  from the words at the next edit, so a hole cut in them would not survive.
- **Feather…** (⌘⌥D) softens the selection's edge by 0–100 px, the desktop's
  Select ▸ Feather with `npimage.feathered_weights` ported exactly: three
  passes of a truncated box blur over the hard mask, normalised against the
  same blur of a solid plane so a selection at the canvas edge stays solid
  there. The menu shows the current radius; a new selection is hard again,
  as on the desktop. The marching ants stay on the hard edge — the feather is
  a weight per pixel, not a different selection — and Delete Selection, the
  paint bucket and the brushes all fade over it. That is one step further
  than the desktop, which applies the feather to its filters only; iOS reads
  it everywhere a selection is consulted, which is what the word means to a
  user. The weights cost one byte per canvas pixel and one float plane while
  they are computed, so setting a feather is refused under the same memory
  notice as adding a layer.

**Strokes honour the selection** (#370). With a selection up, the pen, pencil,
marker and eraser stop at its edge. While the finger is down the stroke is
clipped on screen by the selection's outline; when it lifts, the stroke is
rasterised over its own bounding box and composited onto the layer's pixels
by the selection's weight, one undo step — ink outside the selection never
reaches the layer, the composite or the saved document, and a stroke that
lands nothing registers no step. Strokes under a selection are pixels from
then on, as they are after Merge Down or a bucket fill, and the layer's earlier
strokes are baked in with the first of them. The eraser changes character
here: PencilKit's stroke eraser has nothing to erase once strokes are pixels,
so under a selection it draws a frosted preview and takes its coverage out of
the layer on release, erasing a photograph inside the selection as readily as
a stroke — the desktop's eraser is a pixel eraser too. Without a selection it
is the stroke eraser it always was. Text layers refuse strokes under a
selection as they refuse every pixel operation. The design, and why no
document-sized bitmap was added to draw a stroke, is DD-015.

A selection is a mask in canvas pixels, one flag per pixel, rather than the
path the desktop keeps — every producer and consumer on iOS speaks pixels,
so keeping the mask skips the desktop's two conversions and loses nothing
while every selection is pixel-aligned. It belongs to the document, not to a
layer: switching layers keeps it, and the bucket honours it on whichever layer
is active. Resizing or cropping the canvas drops it, since a mask for the old
canvas describes no pixel of the new one. The bucket, Delete Selection and
the brushes all honour it; the feather rides with it as a weight per pixel.

### Filters

The **Filters** submenu of **More Actions** holds the seven built-in filters
of the desktop **Filters** menu — **Sepia**, **Pixelate**, **Denoise
(Chroma)**, **Retro Console (8-Bit)**, **Pixel Sort (Glitch)**, **Datamosh +
Chromatic Aberration** and **Film Negative → Positive** — in the desktop's
order. Each row opens a sheet built from the same parameters the desktop
dialog and `photoslop-cli --filter` take, with the same ranges and defaults:
an integer is a slider (a 0/1 flag such as Dither is a switch), a float a
finer slider, a choice a picker. **Apply** runs the filter over the active
layer as one undo step, named for the filter; **Cancel** changes nothing.
There is no live preview, as the desktop dialog has none.

The filters are ports of `photoslop.filters` over the iOS `PixelBuffer`, and
they produce the *same pixels*, not a similar look: `scripts/gen-filter-fixture.py`
runs the desktop code over synthetic images and `FilterParityTests` compares
every word of every case. That took three things a port could easily lose —
the desktop's `float32` arithmetic in the same order, Qt's nearest-neighbour
sampling grid for the shrink-and-enlarge filters, and NumPy's seeded
generator (`SeedSequence` + `PCG64`, in `NumpyRandom.swift`) for Datamosh, so
a seed lays the same glitch on a phone as it does on the desktop and in the
CLI. Pixel Sort permutes whole pixels, as on the desktop, so nothing is
invented; premultiplied alpha is unpremultiplied and re-premultiplied exactly
where the desktop does it.

With a selection, the filter runs over the layer and every pixel outside the
selection is put back — the desktop's hard-mask path. A filter does not read
the selection's feather, as on the desktop. Text layers are refused for the reason
the bucket refuses them. Each filter works in 256-row bands where the maths is
per pixel; Denoise holds two full-size chroma planes and Datamosh a snapshot to
sample from, and those are counted against the memory budget before the
filter starts, so a layer too large to filter is refused with the low-memory
notice rather than a crash.

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

The versioned manifest is the source of layer order and metadata. Version 4
adds an `effects` array to a layer record — the desktop's normalised effect
objects, verbatim — which a layer without effects omits; a version 3 package
opens with empty stacks. Opening a
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
the paint bucket, the magic wand and pixel selections, the seven built-in
filters, image import, document-wide undo, and flattened image export. The
desktop edition remains the authoritative home for OpenRaster round trips,
marquee and lasso selections, adjustments, filter plugins and smart filters,
appearance effects on non-text layers, editable vectors, automation,
CLI, and MCP. An unsigned GitHub artifact is a reproducible developer build,
not an App Store-signed IPA.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

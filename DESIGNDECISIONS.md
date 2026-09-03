# Design Decisions

The record of what Photoslop deliberately **won't** do, what it will only do
**partially**, and why. Every entry is judged against the project's prime
directive; when a proposed feature and the directive collide, the directive
wins and the reasoning lands here so it never has to be re-litigated from
scratch.

Format: each decision has a status (**Accepted** / **Rejected** /
**Partial**), the decision itself, the why, and the consequences —
including which backlog trackers it re-scoped or closed.

---

## DD-001 — Memory performance beats features (the prime directive)

**Status: Accepted (founding constraint, 2026-07-02).**

Photoslop exists to be the layered editor that treats RAM like it costs
money: exactly one premultiplied 8-bit buffer per layer, copy-on-write
sharing, viewport-only compositing, 128-px tile undo deltas, crop as an
offset shift, and an install measured in megabytes. Every feature proposal
is evaluated against this first, features second. A capability that would
be routine elsewhere is rejected here if its *resident* memory cost scales
with document size.

**Consequence:** the rulings below. The dividing line that recurs in all of
them: **transient spikes during an operation are acceptable house style;
resident growth of the per-layer budget is not.**

---

## DD-002 — No resident deep-bit buffers (16-bit / 32-bit layers)

**Status: Rejected (2026-07-03).**

16-bit-per-channel layers double every buffer (8 bytes/px vs 4); 32-bit
float quadruples them (16 bytes/px). A 45 MP layer goes 180 MB → 360 MB →
720 MB, and layers *are* the memory budget — this is not a corner case, it
is the core cost. Even as an opt-in document flag, deep bit depth infects
every engine path (numpy views, LUTs, blends, ORA I/O), roughly doubles the
code and test surface, and its entire payoff contradicts DD-001.

**Consequences:** the deep-bit rows were removed from tracker #108 (which
was re-scoped to ICC only — see DD-004). Transient high-bit-depth inside a
single operation remains allowed (see DD-007).

---

## DD-003 — No scene-referred / HDR pipeline

**Status: Rejected (2026-07-03). Tracker #113 closed.**

A scene-referred workflow (filmic/sigmoid view transforms, linear-light
math, EXR/HDR I/O) requires 32-bit float buffers plus linear intermediates —
the worst resident-memory profile of anything on the backlog. It is also a
solved problem elsewhere: darktable exists, is free, and is excellent at
exactly this. Photoslop stays display-referred 8-bit and interoperates
instead of competing where its architecture forbids it to win.

---

## DD-004 — ICC color management: yes, because it's viewport-only

**Status: Accepted (2026-07-03). Tracker #108 re-scoped to this.**

Color management was accepted precisely because it does *not* touch the
per-layer budget: document profiles are metadata, the display transform
applies to the composited **viewport region only** (the architecture's
native unit of work), soft-proofing is a viewport LUT, and export
conversion is a transient pass over tiles. This is the rare parity feature
that the memory-frugal design makes *cheaper*, not harder.

**Consequence:** #108 is now "ICC color management + soft-proofing" —
assign/convert document profiles, monitor-profile-aware display, soft-proof
toggle, and transient CMYK export (DD-005), with the print pipeline as a
stretch row.

---

## DD-005 — No CMYK working mode; CMYK export only

**Status: Partial (2026-07-03).**

A native CMYK mode means a fourth channel (+25% resident memory) and a
duplicated compositing/adjustment pipeline. Rejected. CMYK **export** — a
one-shot transient conversion at write time through the ICC machinery — is
fine and stays on #108 as a stretch row.

---

## DD-006 — GIMP-bridge: spawn-per-call only, never resident

**Status: Partial (2026-07-03). Tracker #111 annotated.**

Keeping a headless GIMP warm (Script-Fu server) idles at 200–500 MB RSS —
the least memory-frugal idea on the board, rejected outright. The bridge
survives only as **spawn-per-call**: launch GIMP headless for the one
filter run, harvest the result, and let the process die. Slower, but the
memory cost is transient and zero at rest. If spawn latency makes it
useless in practice, the bridge dies entirely rather than going resident.

---

## DD-007 — Raw development: transient 16-bit in, 8-bit layer out

**Status: Partial (2026-07-03). Tracker #112 re-scoped.**

The raw develop stage may hold the full raw plus a 16-bit RGB intermediate
*while the develop dialog is open* — a bounded, single-document transient,
same class as crop and rotate. The **result committed to the document is an
8-bit layer**, keeping the resident budget untouched. Heavy raw ML (denoise,
upscale) routes through the model-adapter contract so the memory lives on
whatever backend the user brings — the most memory-frugal feature shape
Photoslop has (see DD-009).

---

## DD-008 — G'MIC filter runs: bounded float transients accepted

**Status: Accepted with eyes open (2026-07-03). Tracker #111 annotated.**

libgmic computes in float internally, so each filter run costs roughly a
4× transient copy of **one layer at a time**, released when the filter
returns. That is within the transient-spike allowance of DD-001 and is the
price of ~600 filters for near-zero code. The tracker documents the cost so
nobody mistakes it for a leak.

---

## DD-009 — ML features never hardwire infrastructure

**Status: Accepted (2026-07-02, CJ directive).**

Model-backed features (Select Subject, Generative Fill, future denoise/
upscale) speak the documented ModelAdapter contract — any HTTP backend or
entry-point plugin, no vendor account, no bundled model weights, no
hardwired hosts. Besides the freedom argument, this is also the memory
story: the heavy lifting happens on whatever machine the user points at,
and Photoslop's resident footprint stays flat.

---

## DD-010 — iOS stays a DocumentGroup app, browser panel and all

**Status: Accepted (2026-08-06).**

The iOS launch screen shows Apple's document browser beneath it — recents,
locations, and a file listing — before the user has said whether they want to
create or open anything. Photoslop keeps it.

**Why.** `DocumentGroupLaunchScene` layers a launch view *over* the browser; the
browser is the scene's root and no API hides it. This was confirmed by probe
rather than assumed: renaming the scene's title changed the screen while the
panel beneath it did not move, so the launch scene is in control and the panel
is simply not its to remove.

Getting a landing page with no browser means not rooting the app on
`DocumentGroup` — a `WindowGroup` shell presenting a document browser on demand.
`DocumentGroup` supplies document rename, autosave, version history, and iCloud
integration for free, and every one of them would have to be rebuilt and then
kept correct. Rename in particular is already shipped and confirmed working on
device.

**Consequences.**

- The launch screen is the standard iOS document-app experience. That is a
  deliberate choice, not an unfinished one, so a future report of "it shows the
  files first" is answered here rather than reopened.
- Documents keep rename, autosave, versions, and iCloud without app-side code.
- Reversing this means accepting the rebuild cost above, in a new entry that
  supersedes this one.

---

## DD-011 — Layer sources are kept as compressed bytes, not a layer cap

**Status: Accepted (2026-08-13).**

Resizing a placed layer on iOS ([#262](https://github.com/CryptoJones/Photoslop/issues/262))
needs pristine source pixels, or every resize resamples the resampled result and
detail is lost for good. The question was how to pay for that on a device, and
whether to buy it by capping documents at four layers.

**The decision: keep the source as its original compressed bytes, decode on
demand, and do not cap the layer count.**

**Why.** At the default 2048x1536 canvas the numbers decide it:

| | |
|---|---:|
| Placed layer bitmap, decoded, canvas-sized | 12 MiB |
| Pristine source kept as a decoded bitmap (4032x3024 photo) | 48 MiB |
| Pristine source kept as its original compressed bytes | 2-4 MiB |

The expensive reading of "spend memory per layer" is the second row — a second
decoded bitmap, four times the cost of the layer itself. The third row costs
less than a third of what the layer already costs, and it is what makes resize
non-destructive: each resize re-renders from the source with a new scale rather
than compounding on the last result.

Only imported layers carry a source. A drawn layer has none, so the cost falls
exactly on the layers that can be resized and nowhere else.

**Why not the four-layer cap.** It would refuse work the app can already do — a
background, two subjects, two speech bubbles and a caption is six layers and was
composed on a phone before this was written. And the guard it would provide
already exists in a better shape: `ProjectArchive` enforces 256 MiB per layer and
1 GiB per project. Those are byte budgets, which bound what actually costs
something. A count does not: 2048 layers is 24 GB of bitmaps and the byte cap
stops that long before the count is reached, while a cap of four stops a
composite that fits in 80 MiB.

**The backstop, if retention needs one.** Bound the *sources*, not the layers:
keep them until they total a fixed budget, then drop the oldest and let those
layers resize destructively. That degrades under pressure instead of refusing a
sixth layer, and it is consistent with DD-001 — memory is managed, not rationed
by fiat.

**Consequences.**
- `RasterLayer` grows an optional compressed source for imported layers; the
  `.photoslop` package carries it, so a resize is still non-destructive after a
  document is closed and reopened.
- A document with sources is larger on disk. The per-layer and per-project caps
  already police that.
- This is the iOS answer only. The desktop already solves it with smart objects
  (`--convert-smart` / `--restore-smart`), which keep pristine pixels resident
  because a desktop can afford it.

**Addendum (2026-09-02): implemented as decided, with the backstop, plus two
neighbours the same audit found.** The v2.9.0 implementation of #262 shipped the
*first* row's cousin, not the third: `RasterLayer.source` was the decoded
`UIImage`, held "for now". The 2026-08-24 memory audit measured what that
"now" cost — ten placed 12 MP photos, 488 MB of sources beside 126 MB of layers
([#350](https://github.com/CryptoJones/Photoslop/issues/350)) — and v2.20.4
moves it to the decision above.

- `LayerSource` is the compressed bytes and the header size. The import paths
  already hold the file or photo `Data`; it is kept as-is (a 12 MP JPEG is ~3
  MB against 48.8 MB decoded), and a layer placed for the first time from its
  own pixels — one restored from a document — gets a PNG of them, which is
  lossless and still smaller than the bitmap. `placeLayer` decodes inside an
  `autoreleasepool` and lets the decode go once the canvas-sized bitmap is
  drawn. Re-placement is lossless exactly as before: the same bytes decode to
  the same pixels, which is what the test `testReplacingALayerLargerAgain-
  GivesTheFirstPlacementsPixels` holds still.
- The backstop is live: `sourceBudgetBytes` (64 MiB — fifteen to thirty phone
  photos) drops the oldest source first and that layer resizes from its own
  pixels. Measured on the Simulator with worst-case noise JPEGs (15.4 MB each;
  a real photo is 3-4 MB), six placed 12 MP photos retain 61.5 MB of sources —
  four of the six, the budget having let two go — where they retained 292.6 MB.
- Sources are still not written into the `.photoslop` package. The
  "Consequences" bullet above stands as the remaining work; the package format
  is unchanged.

Two more decisions from the same audit live here because they are the same
shape — bound what is retained, do not ration what the user may do:

- **Undo records only what a step changed
  ([#351](https://github.com/CryptoJones/Photoslop/issues/351)).** An undo step
  used to pin the whole prior `[RasterLayer]`. Most steps shared their bitmaps
  with the document and cost nothing; the four whole-document geometry steps
  (Canvas Size, Crop, Resize Document, place-expanding-canvas) replaced every
  bitmap and pinned one old document per step — 32 of them on a 10-layer
  document is multiple GB. `UndoRecord` now holds the changed layers by id
  plus order, active layer and canvas size, and a step that replaced more than
  one layer's pixels packs them with `lzfse` off the main thread. `lzfse` on
  the raw premultiplied rows rather than PNG because PNG stores straight alpha
  and a semi-transparent pixel comes back a shade off, and an undo that returns
  *almost* the pixels is not an undo. Drawn, text and flat layers pack one to
  two orders of magnitude smaller; a photograph barely packs, which is what
  lossless means, and the lossless inverse for the grow-only steps (crop back)
  is the next refinement if the photo case needs one.
- **Strokes render over their own bounds and compare by revision
  ([#355](https://github.com/CryptoJones/Photoslop/issues/355)).** Each
  stroke-bearing layer's `PKDrawing` was rasterised at canvas size per
  composite pass; it is now rasterised over `drawing.bounds ∩ canvas`, per-layer
  pooled. Change detection compared `dataRepresentation()` on both sides in
  `setDrawing` and again in `PencilCanvas.configure`; it now compares a
  `DrawingKey` (layer id + a revision every assignment bumps) and, where the
  canvas reports strokes back, `DrawingChange.differs`, which walks stroke
  metadata (`path.count`, `creationDate`, `renderBounds`, `transform`,
  `maskedPathRanges`, ink) and never serialises.

---

## DD-012 — A canvas overlay lives inside the canvas's coordinate space, not above it

**Decision.** Anything drawn *about* the document — the crop rectangle, the
placement box, and whatever comes next — is hosted inside the canvas scroll
view's content view, in document pixels. It is not floated above the canvas in
screen points and told where the canvas is.

**The problem this ends.** `CanvasHostView`'s `contentView` is exactly the
document: its frame is `(0, 0, canvasWidth, canvasHeight)` and the scroll view
applies zoom and pan as a transform on top. So a view placed inside it is
already in the document's units. A view placed *above* it is not, and has to be
told the canvas's on-screen rectangle and convert — a conversion that depends on
zoom scale, content inset and content offset, all of which change under the
user's fingers and are published asynchronously from UIKit while the model
updates synchronously.

That conversion produced three separate user-visible bugs in a fortnight, each
diagnosed and fixed on its own before the pattern was recognised:

- **#260** — the crop took a region nobody chose, because the overlay guessed
  the canvas's position by fitting and centring, which is right only before the
  first pinch.
- **#268** — a second crop divided the new, smaller canvas by the old, larger
  drawn rectangle, because the two arrived out of order.
- **#270** — pinch and zoom died during a crop, because suspending drawing meant
  switching off hit-testing for the whole scroll view; a floating overlay is not
  in the scroll view, so its touches never reach the scroll view's recognisers.

**Consequences.**
- `CropOverlay` became `CanvasBox`, which takes its rectangle in document pixels
  and does no conversion at all. The readout is the truth rather than a
  rendering of it, and the applied operation is exactly what the readout said.
- `PencilCanvas` is generic over its overlay and hosts it through a
  `UIHostingController` whose view sits in `contentView`.
- The canvas publishes only its **zoom scale**, and only so an overlay can keep
  handles and labels finger-sized: divide chrome by the zoom, leave everything
  about the document alone. `onCanvasRectChanged` is gone.
- Suspending drawing is now done to `PKCanvasView` alone. While a box is up, one
  finger drags it and two fingers pan, the way two fingers already panned while
  drawing; the pinch recogniser is never touched.
- The cost is that a handle can be scrolled out of view, since it lives in the
  scrolling content. That is the correct behaviour — it is attached to a place
  in the picture — and it is why the box may be zoomed and panned at all.

---

## DD-013 — iOS pixel operations go through one borrowed buffer, in the desktop's byte order

**Status: Accepted (2026-09-02).**

The paint bucket ([#325](https://github.com/CryptoJones/Photoslop/issues/325)),
the magic wand (#326) and the filter library (#327) all need to read and write
a layer's pixels on iOS, and nothing in `ipados/` could: drawing is PencilKit,
which is vector strokes, and a layer is a `UIImage`, which is immutable. The
question was how to give them pixels without giving every operation its own
bitmap plumbing, and without handing the app a second full-size buffer per layer.

**The decision: one seam, `PixelBuffer` ([#324](https://github.com/CryptoJones/Photoslop/issues/324)).**
An operation borrows the layer's pixels as a premultiplied ARGB32 buffer,
rewrites them, and the store puts the result back as the layer image in one
undo step (`EditorStore.applyPixelOperation`). Nothing is resident between
operations; the buffer lives for the call.

**Byte order is the desktop's, deliberately.** The buffer is a `CGContext`
with `byteOrder32Little | premultipliedFirst`: B, G, R, A in memory, read as a
little-endian `UInt32` it is `0xAARRGGBB` premultiplied — bit for bit the word
`npimage.view_u32` reads from a `QImage.Format_ARGB32_Premultiplied`. That is
what lets a desktop algorithm be *ported* rather than *re-derived*: the flood
fill's tolerance test compares the same channels of the same word on both
platforms, and a fixture the desktop writes is an assertion the iOS tests can
make verbatim. The alternative, RGBA in memory with a translation at the edge,
would have been one more place for the two editions to quietly disagree.

**Memory, per DD-001.** A buffer is one canvas-sized bitmap and the result is
another until undo takes the old image, so the store budgets a pixel operation
with the same `canAffordLayer` check import uses (#354) and refuses with the
same notice. Inside an operation, work is banded in 256 rows — the desktop's
`CHUNK_ROWS` — under an autorelease pool per band, so a per-row transient is
sized to a band, never to the picture. The seam does not pay for undo by the
tile the way the desktop does; that is the existing store's whole-state undo,
and shrinking it is #351's work, not this seam's.

**Consequences.**
- An operation sees the layer *as drawn*: bounded layers are padded to the
  canvas and PencilKit strokes are baked into the pixels first, because a fill
  inside a drawn outline has to stop at the outline. Strokes are pixels from
  then on, as after Merge Down; the import source is dropped so a later resize
  cannot re-render the operation away. Undo restores all of it.
- Text layers are refused. Their pixels are re-rendered from the words on
  every edit, so a pixel operation on one would not survive Edit Text. Fill a
  paint layer instead.
- The desktop's `flood_fill` is now `FloodFill.swift`, fixture-proven
  identical (`scripts/gen-flood-fill-fixture.py`). The wand is the same flood
  with the write swapped for a mask; the filters (#327) are
  `applyPixelOperation` calls with a banded body. Each is a port, not a
  design — and the filters showed what a port has to carry to stay one:
  the desktop's `float32` arithmetic in the same order, Qt's fixed-point
  nearest-neighbour sampling grid, and NumPy's `SeedSequence` + `PCG64`
  (`NumpyRandom.swift`), each fixture-proven word for word
  (`scripts/gen-filter-fixture.py`). A filter that needs full-size working
  planes (Denoise, Datamosh) declares them so `canAffordLayers` counts them.
- Selections are not consulted, because iOS has none yet. When #326 adds a
  selection model, it enters `FloodFill.mask` as the `sel_mask` intersection
  the desktop already has, and nothing else in the seam moves.

## DD-014 — iOS effects are rendered from the layer every composite, never cached

**Status: Accepted (2026-09-03).**

Coloured shadows and embossing on text
([#316](https://github.com/CryptoJones/Photoslop/issues/316)) put the
desktop's appearance stack on iOS. The desktop keeps a per-layer `fx_cache`
keyed by the image's `cacheKey` and the stack, so a Move drag never re-blurs;
the question was whether iOS should keep one too. It costs one premultiplied
bitmap per effect plane per layer, resident for as long as the layer is —
which is the shape of allocation the memory work of #309/#311 spent three
releases removing.

**The decision: no effect cache.** `EditorStore.render` asks
`AppearanceRenderer.planes(for:)` for a layer's planes, draws them under and
over the fill, and lets them go inside the composite's autorelease pool. The
model is data on every layer (`RasterLayer.effects`), the renderer is
layer-agnostic, and the UI is text-first, because text is where the trade-off
is cheap.

**Why it is cheap for text.** A bounded text layer (#309) is its glyph box,
not the canvas. The alpha plane is cropped to the opaque bounding box plus
twice the stack's reach, so a 40-point word with a 10-pixel shadow blurs a
few hundred pixels a side, in float32, three cumulative-sum passes — well
under a millisecond, and freed before the next layer draws. Re-rendering per
composite is therefore invisible next to the composite itself, and there is no
cache to invalidate when the words, the anchor or the stack change: they are
inputs, and the output follows.

**Why it is not yet cheap for photos, and what that defers.** The same crop
on a photo layer is the whole canvas. A 4K layer with a shadow is a
4096×2160 float32 plane and its blur scratch, per effect, per composite —
tens of megabytes on a device where a drag already runs at the jetsam line.
The renderer is banded-ready in principle (`PixelBuffer.bandRows`, a
`radius`-row halo), but nothing forces that design before the sheet is
exposed on raster layers, so the Effects… button lives in the text tool and
the raster entry point, with the banding it needs, is
[#372](https://github.com/CryptoJones/Photoslop/issues/372).

**Parity is by port, proven by fixture.** `AppearanceRenderer` is
`appearance.render` line for line — the desktop's `_box_blur_plane` as
sequential float32 cumulative sums, the same truncating colourise, the same
`np.gradient` lighting — and `scripts/gen-appearance-fixture.py` writes what
the desktop produced for a text-shaped mask as float32 bit patterns and ARGB32
words that `AppearanceParityTests` compares with no tolerance. Where the port
found the two disagree, the iOS side is wrong by definition.

**Consequences:**

- Effects are never baked. Flatten, export and the package preview draw them
  through the same composite; a layer's `image` is untouched by the stack, and
  Edit Text, Fit Text and Move Text keep it.
- The `.photoslop` manifest (version 4) stores the desktop's normalised effect
  objects verbatim, the JSON an `.ora`'s `photoslop-effects` attribute holds,
  so a future ORA round trip on iOS copies the field rather than translating
  it. Unknown effect kinds are dropped on read and unknown keys are kept under
  `extensions`, the desktop's `normalize_effects` rule.
- Gaussian blur and feather, which on the desktop replace the fill rather than
  add a plane, are carried but not drawn; the sheet says so. Fill opacity is
  not modelled. Both are in #372.
- Preview while the sheet is open is `EditorStore.previewEffects`, the
  non-undoable substitution `previewSuppressedLayerID` already established;
  Apply is one `Change Effects` undo step.

---

## DD-015 — iOS strokes through a selection are clipped on the canvas and baked by weight

**Status: Accepted (2026-09-03).**

The selection model (#326, DD-013's last consequence) gave the bucket and
Delete Selection an edge to stop at. The brushes had none
([#370](https://github.com/CryptoJones/Photoslop/issues/370)): a PencilKit
stroke is a vector the canvas owns, drawn wherever the finger goes and kept
as a stroke on the layer until something bakes it. The desktop is simpler —
every brush is a `QPainter` with the selection set as its clip. The question
was how to get the same effect on a canvas that is not ours to paint, without
breaking #309's memory discipline: no extra document-sized bitmaps per
refresh, and strokes rasterised per layer, once (2.20.4).

**The decision: clip the live stroke on the canvas layer, then bake the
committed stroke into pixels through the selection's weights.**

- *While drawing*, the `PKCanvasView` is masked by a `CAShapeLayer` built
  from the selection (`SelectionMask.fillPath`, one rectangle per run of
  selected pixels, merged into bands). The mask is a path, not a bitmap; it
  is cached per selection id and rebuilt only when the selection changes.
  The finger sees ink stop at the edge as it draws.
- *On commit*, the stroke PencilKit reports is rasterised over its own
  bounding box — never the canvas — into premultiplied words, scaled per
  pixel by the selection's weight, and composited source-over onto the
  layer's pixels through `applyPixelOperation` (DD-013): one undo step
  ("Draw"), the layer's earlier strokes baked with it. Ink outside the
  selection is weighted to zero and never reaches the layer, the composite
  or the document; a stroke that lands nothing registers no step.
- *Between the two*, the canvas view holds no strokes. Under a selection the
  active layer's stored strokes are drawn into the composite instead of the
  live canvas (so the clip cannot hide them), and the canvas shows an empty
  drawing under a *suspended* key — a negative revision no layer ever takes,
  stepped when the composite carrying a stroke's pixels lands. That is what
  keeps a stroke on screen from the finger lifting to the refresh arriving;
  without it every stroke blinked once.

**The eraser becomes a pixel eraser under a selection.** PencilKit's bitmap
eraser erases strokes, and there are none by then — they are pixels. So with
a selection up the eraser is a pen of the eraser's width in a frosted ink
(`BrushTool.selectionEraserInk`), and at commit the stroke is re-inked opaque
black and its coverage taken out of the layer's alpha, by weight. It erases
a photograph inside a selection as readily as it erases a stroke, which the
stroke eraser never could; the desktop's eraser is a pixel eraser too.

**Feathering is the same weight plane.** `SelectionMask.feathered(by:)` is
`npimage.feathered_weights` ported (three truncated box-blur passes on the
hard mask, normalised against the same blur of a ones plane), quantised to a
`UInt8` per pixel, computed in one float plane of the canvas and kept as one
byte per pixel. Delete Selection, the bucket and the stroke bake all read
`weight(at:)`; the ants stay on the hard edge, as they do on the desktop.
The desktop consumes the feather only in its filters; iOS consumes it in
everything that goes through a selection, which is what a user would
expect the word to mean, and the difference is written down in
`docs/v1/ipados.md`.

**Memory, per DD-001 and #309.** The clip is a path. The per-stroke raster
is the stroke's box, under an autorelease pool, gone when the operation
returns. The bake goes through the one borrowed buffer. The feather's float
plane lives for the call, and its `UInt8` result is the only thing kept. No
refresh allocates anything it did not before.

**Consequences.**
- Under a selection, strokes are pixels immediately, not strokes — as they
  would be after Merge Down or a bucket fill. Undo restores them as pixels.
- Text layers refuse strokes under a selection, as they refuse every pixel
  operation (DD-013); the canvas simply discards the stroke.
- The marquee and lasso (#370) are `SelectionMask.rectangle` and
  `SelectionMask.polygon`, the latter an exact emulation of Qt's aliased
  odd-even scanline rasteriser so `scripts/gen-selection-fixture.py` can
  assert the iOS mask pixel for pixel against the desktop's. The shape is
  previewed as a hairline and committed on release; the desktop rebuilds the
  selection per mouse move, which would be a mask per sample here.
- The wand and the bucket are unchanged from #326 (2.22.0 as shipped).

---

*New decisions get the next DD number. Reversing one requires a new entry
that names the entry it supersedes — history is append-only.*

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

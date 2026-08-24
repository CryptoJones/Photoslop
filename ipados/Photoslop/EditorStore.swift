// SPDX-License-Identifier: Apache-2.0
import Foundation
import PencilKit
import SwiftUI
import UIKit
import UniformTypeIdentifiers
import os

struct RasterLayer: Identifiable, @unchecked Sendable {
  let id: UUID
  var name: String
  var image: UIImage
  var drawing: PKDrawing
  var isVisible: Bool
  var opacity: Double
  /// Set on text layers. The image is rendered from this, so keeping it is what
  /// lets the words be re-edited and the text be moved after it is placed.
  var text: TextContent?
  /// The imported pixels at their own resolution, kept so a layer can be
  /// resized repeatedly without resampling a resample.
  ///
  /// Without this, scaling a layer down and back up again would go through the
  /// canvas-sized bitmap twice and lose detail it never needed to lose. Held in
  /// memory only for now — persisting it is DD-011's compressed-source work,
  /// and a reopened document falls back to treating the layer's own pixels as
  /// the source, which is correct but not lossless across sessions.
  var source: UIImage?
  /// Where `source` sits on the canvas, in canvas pixels. Nil means it fills
  /// the canvas, which is what every layer did before layers could be placed.
  var placement: CGRect?
  /// Where this layer's `image` sits on the canvas, in canvas pixels.
  ///
  /// `.zero` with a canvas-sized image is what every layer was until #309: the
  /// archive required `image.size == canvasSize` exactly, so a caption costing
  /// four words was stored as a full-canvas bitmap — 12.58 MB on the standard
  /// canvas, against the ~72 KB the desktop build spends on the same words at
  /// its own extent. ORA stores per-layer offsets too; iOS was the odd one out.
  ///
  /// Only text layers are produced at a bounded extent today. Raster operations
  /// that have not been taught about origins call `expandedToCanvas` first, so
  /// a bounded layer is always safe to hand to them.
  var origin: CGPoint = .zero

  var isText: Bool { text != nil }

  /// The rectangle this layer occupies on the canvas.
  var frame: CGRect { CGRect(origin: origin, size: image.size) }

  /// True when the layer already fills the canvas from the top-left, which is
  /// the shape every raster operation in this file expects.
  func fillsCanvas(_ canvas: CGSize) -> Bool {
    origin == .zero && image.size == canvas
  }

  /// The same layer as a canvas-sized bitmap anchored at the origin.
  ///
  /// The compatibility shim for #309's bounded extents: any operation that has
  /// not been taught to respect `origin` — resize, canvas resize, transform,
  /// masks, painting — calls this first and then works on the familiar shape.
  /// It costs a full-canvas allocation, which is exactly what bounded extents
  /// avoid, so it is deliberately not on the compositing path.
  func expandedToCanvas(_ canvas: CGSize) -> RasterLayer {
    guard !fillsCanvas(canvas) else { return self }
    var copy = self
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    copy.image = UIGraphicsImageRenderer(size: canvas, format: format).image { _ in
      image.draw(at: origin)
    }
    copy.origin = .zero
    return copy
  }

  init(
    id: UUID = UUID(),
    name: String,
    image: UIImage,
    drawing: PKDrawing = PKDrawing(),
    isVisible: Bool = true,
    opacity: Double = 1,
    text: TextContent? = nil,
    source: UIImage? = nil,
    placement: CGRect? = nil,
    origin: CGPoint = .zero
  ) {
    self.id = id
    self.name = name
    self.image = image
    self.drawing = drawing
    self.isVisible = isVisible
    self.opacity = opacity
    self.text = text
    self.source = source
    self.placement = placement
    self.origin = origin
  }
}

struct EditorState: @unchecked Sendable {
  var layers: [RasterLayer]
  var activeLayerID: UUID?
  var canvasSize: CGSize
}

final class EditorStore: ReferenceFileDocument, @unchecked Sendable {
  typealias Snapshot = ProjectSnapshot

  static var readableContentTypes: [UTType] { [.photoslopProject] }
  static var writableContentTypes: [UTType] { [.photoslopProject] }

  @Published private(set) var layers: [RasterLayer] = []
  @Published var activeLayerID: UUID?
  @Published private(set) var canvasSize = EditorStore.defaultCanvasSize
  @Published private(set) var canvasBackground = UIImage()

  weak var undoManager: UndoManager? {
    didSet { undoManager?.levelsOfUndo = Self.undoDepth }
  }
  private var mutationRevision = 0
  /// State from before the current drag, so the gesture undoes as one step.
  private var textMoveOrigin: EditorState?
  private var renderRevision = 0
  private var renderTask: Task<Void, Never>?
  private let renderGeneration = RenderGeneration()

  /// How many steps of undo a document keeps.
  ///
  /// `UndoManager` defaults to 0, which means *unlimited*. Every step pins the
  /// `[RasterLayer]` array it superseded, so a deleted layer's bitmap stays
  /// resident for as long as the step that removed it does — without a bound,
  /// for the life of the document. 32 is deep enough that nobody reaches the
  /// end by hand and shallow enough to bound the worst case (#309).
  static let undoDepth = 32

  /// A generation counter the off-main render can read.
  ///
  /// Deliberately tiny: `Task.detached` inherits neither actor nor
  /// cancellation, so this is the only channel through which queued render work
  /// can learn that it has already been superseded.
  final class RenderGeneration: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0
    func set(_ new: Int) {
      lock.lock()
      value = new
      lock.unlock()
    }
    func get() -> Int {
      lock.lock()
      defer { lock.unlock() }
      return value
    }
  }

  /// The size a document starts at when nobody has said otherwise.
  static let defaultCanvasSize = CGSize(width: 2048, height: 1536)

  /// True for a document that has never had its canvas size chosen, so the
  /// editor offers the choice on first appearance instead of silently settling
  /// for the default.
  @Published private(set) var awaitingCanvasSizeChoice = false

  init() {
    installNewDocument(size: Self.defaultCanvasSize)
    awaitingCanvasSizeChoice = true
    observeMemoryPressure()
  }

  deinit {
    renderTask?.cancel()
    if let memoryWarningObserver {
      NotificationCenter.default.removeObserver(memoryWarningObserver)
    }
  }

  private var memoryWarningObserver: NSObjectProtocol?

  /// Listen for the one warning iOS gives before jetsam.
  ///
  /// Nothing in the target observed it (#309). That notification is the app's
  /// only chance to give memory back voluntarily; ignoring it means the first
  /// thing the app learns about memory pressure is `SIGKILL`.
  private func observeMemoryPressure() {
    memoryWarningObserver = NotificationCenter.default.addObserver(
      forName: UIApplication.didReceiveMemoryWarningNotification,
      object: nil,
      queue: .main
    ) { [weak self] _ in
      MainActor.assumeIsolated { self?.shedMemory() }
    }
  }

  /// Set when memory had to be given back, so the editor can say so (#311).
  ///
  /// Silently dropping undo history is worse than it sounds: the next tap on
  /// Undo does nothing, with no explanation, and the app looks broken rather
  /// than careful.
  @Published var memoryPressureNotice: String?

  /// Give back everything that is not the document itself.
  ///
  /// Undo history is the largest droppable thing the store owns: each step pins
  /// the layer array it replaced. Losing history is a real cost, and it is a
  /// smaller one than losing the document to a kill.
  func shedMemory() {
    renderTask?.cancel()
    let hadHistory = undoManager?.canUndo ?? false
    undoManager?.removeAllActions()
    memoryPressureNotice =
      hadHistory
      ? "This device is low on memory, so undo history was released to keep "
        + "the document open. The picture itself is untouched."
      : "This device is low on memory. Adding more or larger layers may not "
        + "be possible until something else is closed."
  }

  /// Bytes this process may still allocate before jetsam takes an interest.
  ///
  /// The honest number, measured at runtime, instead of a hardcoded device cap:
  /// the phone in #309 has 6 GB and an M5 iPad has 12-16 GB, so any constant is
  /// wrong on one of them, and wrong again on the next device Apple ships.
  static func availableMemoryBytes() -> Int {
    Int(os_proc_available_memory())
  }

  /// Whether one more canvas-sized layer is affordable right now.
  ///
  /// Doubled because a layer costs its own bitmap plus the transient the
  /// compositor builds, and reserved above that so the app still has room to
  /// composite, save, and show the user why it stopped rather than dying while
  /// explaining itself.
  static func canAffordLayer(canvas: CGSize, reserve: Int = 192 * 1_024 * 1_024) -> Bool {
    canAffordLayers(1, canvas: canvas, reserve: reserve)
  }

  /// `canAffordLayer` for operations that rebuild `count` layers at once —
  /// Canvas Size, Resize Document, place-expanding-canvas — where the old and
  /// new documents coexist until the mutation lands.
  static func canAffordLayers(
    _ count: Int, canvas: CGSize, reserve: Int = 192 * 1_024 * 1_024
  ) -> Bool {
    let available = availableMemoryBytes()
    // 0 means the platform declined to answer; do not refuse work over that.
    guard available > 0 else { return true }
    let layerBytes = Int(canvas.width.rounded()) * Int(canvas.height.rounded()) * 4
    return available > layerBytes * (count + 1) + reserve
  }

  /// The refusal shown when a memory budget check says no (#354): the same
  /// honest stop the batch importer makes, for every other allocation door.
  static let memoryRefusal =
    "There is not enough free memory for that right now. "
    + "Close other apps or documents and try again."

  /// Called once the choice has been offered, so it is not asked again when the
  /// view reappears after a sheet, a rotation, or a return from the background.
  func canvasSizeChoiceOffered() {
    awaitingCanvasSizeChoice = false
  }

  required init(configuration: ReadConfiguration) throws {
    defer { observeMemoryPressure() }
    let state = try ProjectArchive.decode(configuration.file)
    layers = state.layers
    activeLayerID = state.activeLayerID
    canvasSize = state.canvasSize
    if activeLayerID == nil || !layers.contains(where: { $0.id == activeLayerID }) {
      activeLayerID = layers.last?.id
    }
    refreshCanvas()
    awaitingCanvasSizeChoice = Self.isUntouchedNewDocument(state)
  }

  /// Whether a decoded document is indistinguishable from one `init()` just
  /// made, and so has never had its size chosen.
  ///
  /// The editor is not handed the store `init()` built. Creating a document —
  /// from the launch scene or from the browser — writes it to disk and reopens
  /// it through this initialiser, so a flag set in `init()` is spent on a store
  /// that never reaches the screen. That is why the launch scene's Create
  /// Document stopped asking: nothing was wrong with the flag, it was simply
  /// set on the wrong instance. Recognising the shape of a brand-new document
  /// is what survives the round trip.
  ///
  /// The cost is that reopening a still-blank default document asks again. It is
  /// a blank canvas either way and Cancel keeps the size, so asking twice is
  /// harmless where never asking was not.
  static func isUntouchedNewDocument(_ state: EditorState) -> Bool {
    guard state.canvasSize == defaultCanvasSize, state.layers.count == 1,
      let only = state.layers.first
    else { return false }
    // The name is part of the test: renaming the layer is an edit, and an
    // edited document has been accepted at the size it already has.
    return only.name == "Background" && only.drawing.strokes.isEmpty && only.text == nil
      && only.isVisible && only.opacity == 1
  }

  func snapshot(contentType: UTType) throws -> ProjectSnapshot {
    if Thread.isMainThread {
      return try ProjectArchive.snapshot(state: currentState())
    }
    return try DispatchQueue.main.sync {
      try ProjectArchive.snapshot(state: currentState())
    }
  }

  func fileWrapper(
    snapshot: ProjectSnapshot,
    configuration: WriteConfiguration
  ) throws -> FileWrapper {
    try ProjectArchive.encode(snapshot)
  }

  var activeLayer: RasterLayer? {
    guard let activeLayerID else { return nil }
    return layers.first { $0.id == activeLayerID }
  }

  var canDeleteLayer: Bool { layers.count > 1 }

  var canMergeDown: Bool {
    guard let activeLayerID, let index = layers.firstIndex(where: { $0.id == activeLayerID })
    else { return false }
    return index > 0
  }

  func newDocument(size: CGSize = EditorStore.defaultCanvasSize) {
    guard ProjectArchive.isValidCanvas(size) else { return }
    mutate(actionName: "New Document") { installNewDocument(size: size) }
  }

  /// Pad or crop the canvas to `size`, keeping existing artwork centred.
  ///
  /// This is canvas resizing, not scaling: pixels keep their size and the
  /// border grows or is trimmed around them. The centred anchor matches
  /// `photoslop-cli --canvas-size`, which offsets content by half the
  /// difference, so a document resized either way lands identically.
  func resizeCanvas(to size: CGSize) {
    guard ProjectArchive.isValidCanvas(size), size != canvasSize else { return }
    guard Self.canAffordLayers(layers.count, canvas: size) else {
      memoryPressureNotice = Self.memoryRefusal
      return
    }
    let offset = CGPoint(
      x: ((size.width - canvasSize.width) / 2).rounded(),
      y: ((size.height - canvasSize.height) / 2).rounded()
    )
    recanvas(to: size, offset: offset, actionName: "Canvas Size")
  }

  /// Crop to `rect`, given in canvas pixels.
  ///
  /// This is `resizeCanvas` with a chosen origin rather than a centred one, and
  /// it deliberately shares that implementation: the part which is easy to get
  /// wrong is not the arithmetic but remembering that a layer is pixels *and*
  /// PencilKit strokes *and* possibly a text anchor, all of which have to move
  /// together. A second code path here would be a second chance to forget one.
  ///
  /// Agrees with `photoslop-cli --crop X,Y,W,H` for the same rectangle.
  func crop(to rect: CGRect) {
    let bounded = rect.intersection(CGRect(origin: .zero, size: canvasSize)).integral
    let size = bounded.size
    guard ProjectArchive.isValidCanvas(size), bounded != CGRect(origin: .zero, size: canvasSize)
    else { return }
    recanvas(
      to: size, offset: CGPoint(x: -bounded.origin.x, y: -bounded.origin.y), actionName: "Crop")
  }

  /// Scale the whole document to `size`, resampling every layer.
  ///
  /// The third of the three operations that change a document's dimensions, and
  /// the one that was missing (#269). Canvas Size pads or crops around content
  /// that keeps its pixel size; Crop takes a region and discards the rest; this
  /// resamples, so nothing is lost and nothing is padded — the picture simply
  /// becomes the size asked for.
  ///
  /// Mirrors `photoslop-cli --resize WxH`.
  func scaleDocument(to size: CGSize) {
    guard ProjectArchive.isValidCanvas(size), size != canvasSize else { return }
    guard Self.canAffordLayers(layers.count, canvas: size) else {
      memoryPressureNotice = Self.memoryRefusal
      return
    }
    let sx = size.width / canvasSize.width
    let sy = size.height / canvasSize.height
    let transform = CGAffineTransform(scaleX: sx, y: sy)
    let previousCanvas = canvasSize
    mutate(actionName: "Resize Document") {
      canvasSize = size
      layers = layers.map { original in
        // Geometry works on canvas-sized pixels; a bounded layer (#309) is
        // expanded first so this arithmetic stays the arithmetic it always was.
        let layer = original.expandedToCanvas(previousCanvas)
        var scaled = layer
        scaled.image = Self.scaled(layer.image, to: size)
        // Strokes are vectors and have to travel with the pixels, exactly as
        // they do for Canvas Size and Crop.
        scaled.drawing = layer.drawing.transformed(using: transform)
        if var text = scaled.text {
          text.x *= Double(sx)
          text.y *= Double(sy)
          // Type scales with the picture, or a resized document would keep its
          // captions at the old size and reflow.
          text.fontSize *= Double(min(sx, sy))
          scaled.text = text
        }
        if let placed = scaled.placement {
          scaled.placement = placed.applying(transform)
        }
        return scaled
      }
    }
  }

  /// Draw `image` scaled to fill `size` exactly.
  private static func scaled(_ image: UIImage, to size: CGSize) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: size, format: format).image { _ in
      image.draw(in: CGRect(origin: .zero, size: size))
    }
  }

  private func recanvas(to size: CGSize, offset: CGPoint, actionName: String) {
    let translation = CGAffineTransform(translationX: offset.x, y: offset.y)
    let previousCanvas = canvasSize
    mutate(actionName: actionName) {
      canvasSize = size
      layers = layers.map { original in
        let layer = original.expandedToCanvas(previousCanvas)
        var resized = layer
        resized.image = Self.recanvased(layer.image, to: size, offset: offset)
        resized.drawing = layer.drawing.transformed(using: translation)
        // The stored anchor has to travel with the pixels. Leaving it behind
        // would look right until the text was next edited, at which point it
        // would jump back to where the old canvas put it.
        if var text = resized.text {
          text.x += Double(offset.x)
          text.y += Double(offset.y)
          resized.text = text
        }
        return resized
      }
    }
  }

  /// Draw `image` onto a transparent canvas of `size` at `offset`.
  private static func recanvased(_ image: UIImage, to size: CGSize, offset: CGPoint) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: size, format: format).image { _ in
      image.draw(at: offset)
    }
  }

  /// Add rasterised text as its own layer, mirroring `photoslop-cli --text`.
  ///
  /// The text becomes pixels immediately, exactly as it does on the desktop op
  /// this matches; the layer is not re-editable afterwards. Returns false when
  /// there was nothing to draw, so the caller can say so rather than silently
  /// adding an empty layer.
  @discardableResult
  func addTextLayer(
    _ text: String,
    fontSize: CGFloat,
    color: UIColor,
    at anchor: CGPoint,
    fontFamily: String? = nil
  ) -> Bool {
    let content = TextContent(
      string: text, fontSize: fontSize, color: color, anchor: anchor, fontFamily: fontFamily)
    guard let rendered = Self.renderTextLayer(content, canvasSize: canvasSize) else { return false }
    mutate(actionName: "Add Text") {
      let layer = RasterLayer(
        name: TextLayerRenderer.layerName(for: text), image: rendered.image, text: content,
        origin: rendered.origin)
      layers.append(layer)
      activeLayerID = layer.id
    }
    return true
  }

  /// Re-render a text layer from new words, size, or colour.
  ///
  /// The layer keeps its identity, position in the stack, visibility, and
  /// opacity; only the pixels and the stored source change. Returns false when
  /// the layer is not a text layer or the new text is blank, so the caller can
  /// say so rather than silently blanking a layer.
  @discardableResult
  func updateTextLayer(
    _ id: UUID,
    string: String,
    fontSize: CGFloat,
    color: UIColor,
    fontFamily: String? = nil
  ) -> Bool {
    guard let existing = layers.first(where: { $0.id == id })?.text else { return false }
    var content = TextContent(
      string: string, fontSize: fontSize, color: color, anchor: existing.anchor,
      fontFamily: fontFamily)
    // The wrap survives an edit: the words still live in their fitted box.
    // The size chosen in the sheet is explicit and is honoured exactly, even
    // past the canvas edge — whether to accept the cut-off or shrink to fit
    // is asked in the sheet before this is called (#298), because a store
    // that silently second-guesses an explicit size is a different foot-gun.
    content.wrapWidth = existing.wrapWidth
    guard let rendered = Self.renderTextLayer(content, canvasSize: canvasSize) else { return false }
    mutate(actionName: "Edit Text") {
      update(id) {
        $0.image = rendered.image
        $0.origin = rendered.origin
        $0.text = content
        $0.name = TextLayerRenderer.layerName(for: string)
      }
    }
    return true
  }

  /// Move a text layer's anchor, re-rendering at the new position.
  ///
  /// Dragging emits a stream of these, so `coalesce` keeps the whole gesture as
  /// a single undo step instead of one per touch sample.
  @discardableResult
  func moveTextLayer(_ id: UUID, to anchor: CGPoint, coalesce: Bool = false) -> Bool {
    guard let existing = layers.first(where: { $0.id == id })?.text else { return false }
    var content = existing
    content.x = Double(anchor.x)
    content.y = Double(anchor.y)
    guard let rendered = Self.renderTextLayer(content, canvasSize: canvasSize) else { return false }

    // One undo step for the whole gesture, which means the state to return to
    // is the one from before the *first* sample. Registering on the last sample
    // instead would only ever undo the final pixel of the drag.
    let origin = textMoveOrigin ?? currentState()
    if coalesce { textMoveOrigin = origin }

    objectWillChange.send()
    update(id) {
      $0.image = rendered.image
      $0.origin = rendered.origin
      $0.text = content
    }
    mutationRevision += 1
    if !coalesce {
      textMoveOrigin = nil
      registerUndo(previous: origin, actionName: "Move Text")
    }
    refreshCanvas()
    return true
  }

  private static func renderText(_ content: TextContent, canvasSize: CGSize) -> UIImage? {
    TextLayerRenderer.render(
      text: content.string,
      fontSize: CGFloat(content.fontSize),
      color: content.color,
      at: content.anchor,
      canvasSize: canvasSize,
      fontFamily: content.fontFamily,
      wrapWidth: content.wrapWidth.map { CGFloat($0) }
    )
  }

  /// A text layer's bitmap and where it sits, at the extent the words need.
  ///
  /// The whole point of #309's format change: the same caption that cost a
  /// full canvas-sized bitmap (12.58 MB on the standard canvas) costs the box
  /// around the glyphs. Falls back to the canvas-sized rendering when the tight
  /// one cannot be produced or would not fit, so a text layer always renders.
  private static func renderTextLayer(
    _ content: TextContent, canvasSize: CGSize
  ) -> (image: UIImage, origin: CGPoint)? {
    let anchor = CGPoint(x: content.anchor.x.rounded(), y: content.anchor.y.rounded())
    if let tight = TextLayerRenderer.glyphs(
      text: content.string,
      fontSize: CGFloat(content.fontSize),
      color: content.color,
      fontFamily: content.fontFamily,
      wrapWidth: content.wrapWidth.map { CGFloat($0) }
    ),
      ProjectArchive.isLayerFrameValid(
        CGRect(origin: anchor, size: tight.size), canvas: canvasSize)
    {
      return (tight, anchor)
    }
    guard let full = renderText(content, canvasSize: canvasSize) else { return nil }
    return (full, .zero)
  }

  /// Replace the document's contents with an image, fitted to the canvas.
  ///
  /// This used to take the canvas from the image — `canvasSize = normalized.size`
  /// — which threw away the size the person chose when they created the
  /// document. Importing a photo into a 1920x1080 canvas silently produced a
  /// 4032x3024 one. The canvas someone picked is the canvas they keep; the photo
  /// is scaled to fit it and centred (#258).
  /// How an image whose size disagrees with the canvas becomes the document.
  ///
  /// Nothing here decides silently — the choice belongs to the person
  /// importing, asked in a dialog when the sizes differ (#293). `fit` is what
  /// every import used to do without asking.
  enum ImportSizing {
    /// The canvas becomes the image's own size; every pixel arrives.
    case expandCanvas
    /// The image lands centred at its own size; whatever overhangs is cut.
    case cropToCanvas
    /// The image is scaled to fit inside the canvas, losing nothing but scale.
    case fit
  }

  func importImage(
    data: Data, suggestedName: String? = nil, sizing: ImportSizing = .fit
  ) throws {
    // Refuse before decoding: the decode IS the allocation that kills (#309).
    // The canvas this import must afford is the source's own size when the
    // canvas will grow to it, and the current canvas otherwise.
    let decodedSize = ProjectArchive.imageSize(of: data)
    let demand = sizing == .expandCanvas ? (decodedSize ?? canvasSize) : canvasSize
    guard Self.canAffordLayer(canvas: demand) else {
      throw ImportError.resourceLimit(Self.memoryRefusal)
    }
    let name = suggestedName ?? "Imported image"
    if sizing == .fit {
      // Decode straight to the fitted extent (#309): the full-resolution
      // bitmap is never materialised. The other sizings genuinely need every
      // source pixel, so they keep the full decode below.
      let fitted = try ProjectArchive.decodeImage(data, fittingInto: canvasSize)
      mutate(actionName: "Import Image") {
        let layer = RasterLayer(name: name, image: Self.fitted(fitted, into: canvasSize))
        layers = [layer]
        activeLayerID = layer.id
      }
      return
    }
    let normalized = try ProjectArchive.decodeImage(data)
    switch sizing {
    case .expandCanvas:
      guard ProjectArchive.isValidCanvas(normalized.size) else {
        throw ImportError.resourceLimit(
          "That image is \(Int(normalized.size.width)) × \(Int(normalized.size.height)) px, "
            + "which is more than a canvas can be.")
      }
      mutate(actionName: "Import Image") {
        canvasSize = normalized.size
        let layer = RasterLayer(name: name, image: normalized)
        layers = [layer]
        activeLayerID = layer.id
      }
    case .cropToCanvas:
      mutate(actionName: "Import Image") {
        let offset = CGRect(
          origin: CGPoint(
            x: ((canvasSize.width - normalized.size.width) / 2).rounded(),
            y: ((canvasSize.height - normalized.size.height) / 2).rounded()),
          size: normalized.size)
        let layer = RasterLayer(
          name: name, image: Self.drawn(normalized, in: offset, canvas: canvasSize))
        layers = [layer]
        activeLayerID = layer.id
      }
    case .fit:
      // handled above with a size-bounded decode
      break
    }
  }

  /// The decoded size of an image about to be imported, so the caller can ask
  /// how to handle a size disagreement before anything is committed.
  static func importedImageSize(of data: Data) -> CGSize? {
    // Read the header rather than decoding the picture: this is asked before
    // anything is committed, and the old path materialised a full-resolution
    // bitmap just to read `.size` off it (#309).
    ProjectArchive.imageSize(of: data)
  }

  /// Add each image as its own layer, on top of the stack, as one undo step.
  ///
  /// Distinct from `importImage`, which replaces the document: that is how an
  /// image becomes a document, this is how one joins the document already open.
  /// Doing a double exposure needs the second behaviour and only had the first.
  ///
  /// Images are scaled to fit the canvas and centred, never cropped. A layer
  /// image has to be exactly canvas-sized — `ProjectArchive.snapshot` enforces
  /// it — so an image of a different aspect ratio has to lose something: either
  /// the parts outside the canvas, or the space at the edges. Transparent edges
  /// are recoverable and cropped pixels are not, and a portrait photo dropped
  /// into a landscape canvas would lose most of itself to a crop.
  @discardableResult
  func addImageLayers(_ images: [(name: String, image: UIImage)]) throws -> Int {
    guard !images.isEmpty else { return 0 }
    guard layers.count + images.count <= ProjectArchive.maximumLayers else {
      throw ImportError.resourceLimit(
        "A project holds \(ProjectArchive.maximumLayers) layers. "
          + "This document has \(layers.count) and \(images.count) more were chosen.")
    }

    let canvas = canvasSize
    // An image that is already canvas-sized is one the caller fitted while
    // streaming the import, and re-fitting it would allocate a second
    // canvas-sized bitmap per photo for no change in pixels (#309). Callers
    // that hand over raw sources still get fitted here, as they always did.
    let prepared = images.map {
      (name: $0.name, image: $0.image.size == canvas ? $0.image : Self.fitted($0.image, into: canvas))
    }
    mutate(actionName: prepared.count == 1 ? "New Layer from Photo" : "New Layers from Photos") {
      for entry in prepared {
        let layer = RasterLayer(name: uniqueName(base: entry.name), image: entry.image)
        layers.append(layer)
        activeLayerID = layer.id
      }
    }
    return prepared.count
  }

  /// Add one image as a layer at its **own** size, centred, ready to be placed.
  ///
  /// `addImageLayers` scales an import to fit the canvas, which is right when
  /// several photos arrive at once and nobody wants to place each one. It is
  /// wrong for a single deliberate import: the picture arrives already resized
  /// with no way back, and choosing how big it should be is most of the point
  /// (#266). This keeps the original pixels as the layer's `source` so the
  /// placement box can resize it as many times as it likes without compounding
  /// resampling loss.
  ///
  /// Returns the new layer's id and the rectangle it landed in, which is where
  /// the placement box opens.
  @discardableResult
  func addPlaceableLayer(name: String, image: UIImage) throws -> (id: UUID, rect: CGRect) {
    guard layers.count < ProjectArchive.maximumLayers else {
      throw ImportError.resourceLimit(
        "A project holds \(ProjectArchive.maximumLayers) layers and this document has "
          + "\(layers.count).")
    }
    // A placed layer costs its canvas-sized bitmap plus the retained source
    // (DD-011), so the budget question is asked about the larger of the two.
    let demand = CGSize(
      width: max(canvasSize.width, image.size.width),
      height: max(canvasSize.height, image.size.height))
    guard Self.canAffordLayer(canvas: demand) else {
      throw ImportError.resourceLimit(Self.memoryRefusal)
    }
    let normalized = Self.normalizedImage(image)
    let rect = Self.centredRect(for: normalized.size, in: canvasSize)
    let layer = RasterLayer(
      name: uniqueName(base: name),
      image: Self.drawn(normalized, in: rect, canvas: canvasSize),
      source: normalized,
      placement: rect)
    mutate(actionName: "New Layer from Image") {
      layers.append(layer)
      activeLayerID = layer.id
    }
    return (layer.id, rect)
  }

  /// The rectangle an image occupies when it arrives at its own size, centred.
  ///
  /// Deliberately **not** scaled to fit: an image larger than the canvas hangs
  /// over the edges, which is visible in the placement box and is exactly the
  /// starting point for scaling it down by eye. What it must not do is grow the
  /// canvas, which is the bug this replaces.
  static func centredRect(for size: CGSize, in canvas: CGSize) -> CGRect {
    CGRect(
      x: ((canvas.width - size.width) / 2).rounded(),
      y: ((canvas.height - size.height) / 2).rounded(),
      width: size.width,
      height: size.height)
  }

  /// Where a layer's placement box should open.
  ///
  /// A layer imported this session knows where its source sits. One restored
  /// from a file does not, so its own pixels are the source and they fill the
  /// canvas — resizing from there still works, it just starts from the whole
  /// layer rather than from the picture inside it.
  func placementRect(for id: UUID) -> CGRect {
    layers.first(where: { $0.id == id })?.placement
      ?? CGRect(origin: .zero, size: canvasSize)
  }

  /// Draw a layer's source into `rect`, as one undo step.
  ///
  /// This is how a placed layer is both positioned and resized — one gesture,
  /// one operation, whether it is a brand-new import being put where it belongs
  /// (#266) or an existing layer that came in the wrong size (#262).
  func placeLayer(_ id: UUID, in rect: CGRect, actionName: String = "Resize Layer") {
    guard let layer = layers.first(where: { $0.id == id }) else { return }
    guard rect.width >= 1, rect.height >= 1 else { return }
    // A layer restored from a file has no separate source, so its own pixels
    // are it, and they cover the canvas.
    let source = layer.source ?? layer.image
    let drawn = Self.drawn(source, in: rect, canvas: canvasSize)
    mutate(actionName: actionName) {
      update(id) {
        $0.image = drawn
        // `drawn` is canvas-sized, so a layer that had been bounded (#309) is
        // back to filling the canvas and must stop claiming an offset.
        $0.origin = .zero
        $0.source = source
        $0.placement = rect
      }
    }
  }

  /// Place a layer whose rectangle overhangs the canvas by growing the canvas
  /// to hold every pixel — placement and expansion as one undo step (#293).
  ///
  /// The canvas grows to the union of itself and the rectangle; everything
  /// already in the document shifts by the union's origin so nothing moves on
  /// screen, and the placed layer lands at the shifted rectangle in full.
  @discardableResult
  func placeLayerExpandingCanvas(_ id: UUID, in rect: CGRect) -> Bool {
    guard let layer = layers.first(where: { $0.id == id }) else { return false }
    guard rect.width >= 1, rect.height >= 1 else { return false }
    let union = rect.union(CGRect(origin: .zero, size: canvasSize)).integral
    guard ProjectArchive.isValidCanvas(union.size) else { return false }
    guard Self.canAffordLayers(layers.count, canvas: union.size) else {
      memoryPressureNotice = Self.memoryRefusal
      return false
    }
    let offset = CGPoint(x: -union.origin.x, y: -union.origin.y)
    let translation = CGAffineTransform(translationX: offset.x, y: offset.y)
    let source = layer.source ?? layer.image
    let target = rect.offsetBy(dx: offset.x, dy: offset.y)
    let previousCanvas = canvasSize
    mutate(actionName: "Expand Canvas") {
      canvasSize = union.size
      layers = layers.map { original in
        let existing = original.expandedToCanvas(previousCanvas)
        var moved = existing
        if existing.id == id {
          moved.image = Self.drawn(source, in: target, canvas: union.size)
          moved.source = source
          moved.placement = target
          return moved
        }
        moved.image = Self.recanvased(existing.image, to: union.size, offset: offset)
        moved.drawing = existing.drawing.transformed(using: translation)
        if var text = moved.text {
          text.x += Double(offset.x)
          text.y += Double(offset.y)
          moved.text = text
        }
        if let placed = moved.placement {
          moved.placement = placed.applying(translation)
        }
        return moved
      }
    }
    return true
  }

  /// Draw `image` into `rect` on a transparent canvas-sized bitmap. Anything
  /// outside the canvas is simply not drawn, which is what "hanging over the
  /// edge" means once it is committed.
  static func drawn(_ image: UIImage, in rect: CGRect, canvas: CGSize) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: canvas, format: format).image { _ in
      image.draw(in: rect)
    }
  }

  /// Fit a text layer to `rect`: the anchor moves to its corner, the words
  /// wrap at the box's width, and the type takes the largest size whose
  /// wrapped layout fits the box (#261, #296).
  ///
  /// Text was placed and then stuck — dropped on the canvas at whatever size
  /// the sheet asked for, with no way to fit it to what is underneath. Two
  /// earlier attempts under-delivered: scaling by width alone made a taller
  /// box a no-op, and scaling without wrapping kept a long caption as one
  /// tiny strip across a box that had room for five lines. The explicit size
  /// in the Edit Text sheet still overrides a fit afterwards.
  @discardableResult
  func fitTextLayer(_ id: UUID, to rect: CGRect) -> Bool {
    guard let existing = layers.first(where: { $0.id == id })?.text else { return false }
    guard
      let fitted = TextLayerRenderer.fittingFontSize(
        text: existing.string, fontFamily: existing.fontFamily, in: rect.size)
    else { return false }
    var content = existing
    content.fontSize = Double(fitted)
    content.wrapWidth = Double(rect.width)
    content.x = Double(rect.minX)
    content.y = Double(rect.minY)
    guard let rendered = Self.renderTextLayer(content, canvasSize: canvasSize) else { return false }
    mutate(actionName: "Fit Text") {
      update(id) {
        $0.image = rendered.image
        $0.origin = rendered.origin
        $0.text = content
      }
    }
    return true
  }

  /// The box a text layer currently occupies, for the placement box to open on.
  func textRect(for id: UUID) -> CGRect? {
    guard let content = layers.first(where: { $0.id == id })?.text else { return nil }
    let measured = TextLayerRenderer.measure(
      text: content.string, fontSize: CGFloat(content.fontSize),
      fontFamily: content.fontFamily,
      wrapWidth: content.wrapWidth.map { CGFloat($0) })
    return CGRect(origin: content.anchor, size: measured)
  }

  /// Draw `image` centred on a transparent canvas-sized bitmap, scaled down to
  /// fit if it is larger. Smaller images are left at their own size rather than
  /// stretched, because upscaling invents detail that was never photographed.
  static func fitted(_ image: UIImage, into canvas: CGSize) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: canvas, format: format).image { _ in
      // Fits in both directions. This was clamped with `min(1, ...)` so an
      // image smaller than the canvas kept its own size, on the reasoning that
      // upscaling invents detail that was never captured (#234). True, but it
      // made one action behave two ways depending on the size of the photo
      // picked, which is harder to predict than a rule that always fits. The
      // cost is a softer result when scaling up; the benefit is that "scaled to
      // fit and centred" means what it says (#258).
      let scale = min(canvas.width / image.size.width, canvas.height / image.size.height)
      let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
      image.draw(
        in: CGRect(
          x: ((canvas.width - size.width) / 2).rounded(),
          y: ((canvas.height - size.height) / 2).rounded(),
          width: size.width,
          height: size.height))
    }
  }

  func select(_ id: UUID) {
    guard layers.contains(where: { $0.id == id }) else { return }
    activeLayerID = id
    refreshCanvas()
  }

  func setDrawing(_ drawing: PKDrawing) {
    guard drawing.dataRepresentation() != activeLayer?.drawing.dataRepresentation() else { return }
    mutate(actionName: "Draw") { updateActive { $0.drawing = drawing } }
  }

  func addLayer() {
    guard Self.canAffordLayer(canvas: canvasSize) else {
      memoryPressureNotice = Self.memoryRefusal
      return
    }
    mutate(actionName: "Add Layer") {
      let image = Self.solidImage(size: canvasSize, color: .clear)
      let layer = RasterLayer(name: uniqueName(base: "Paint Layer"), image: image)
      layers.append(layer)
      activeLayerID = layer.id
    }
  }

  func duplicateActiveLayer() {
    guard let id = activeLayerID, let index = layers.firstIndex(where: { $0.id == id })
    else { return }
    mutate(actionName: "Duplicate Layer") {
      let source = layers[index]
      let copy = RasterLayer(
        name: uniqueName(base: "\(source.name) copy"),
        image: source.image,
        drawing: source.drawing,
        isVisible: source.isVisible,
        opacity: source.opacity
      )
      layers.insert(copy, at: index + 1)
      activeLayerID = copy.id
    }
  }

  /// Remove a named layer, whether or not it is the active one.
  ///
  /// Used when an import is cancelled from the placement box: the layer was
  /// added so it could be seen while it was positioned, and declining the
  /// placement declines the layer.
  func deleteLayer(_ id: UUID) {
    guard canDeleteLayer, let index = layers.firstIndex(where: { $0.id == id }) else { return }
    mutate(actionName: "Delete Layer") {
      layers.remove(at: index)
      if activeLayerID == id {
        activeLayerID = layers[min(index, layers.count - 1)].id
      }
    }
  }

  func deleteActiveLayer() {
    guard canDeleteLayer, let id = activeLayerID,
      let index = layers.firstIndex(where: { $0.id == id })
    else { return }
    mutate(actionName: "Delete Layer") {
      layers.remove(at: index)
      activeLayerID = layers[min(index, layers.count - 1)].id
    }
  }

  func clearActiveLayer() {
    mutate(actionName: "Clear Layer") {
      updateActive { layer in
        layer.image = Self.solidImage(size: canvasSize, color: .clear)
        layer.origin = .zero
        layer.drawing = PKDrawing()
      }
    }
  }

  func mergeActiveDown() {
    guard let id = activeLayerID, let index = layers.firstIndex(where: { $0.id == id }),
      index > 0
    else { return }
    let expectedRevision = mutationRevision
    let lower = layers[index - 1]
    let upper = layers[index]
    let size = canvasSize
    Task { @MainActor [weak self] in
      let merged = await Task.detached(priority: .userInitiated) {
        Self.render(layers: [lower, upper], size: size)
      }.value
      guard let self, mutationRevision == expectedRevision,
        index < layers.count, layers[index - 1].id == lower.id, layers[index].id == upper.id
      else { return }
      mutate(actionName: "Merge Layer Down") {
        let replacement = RasterLayer(name: lower.name, image: merged)
        layers.replaceSubrange((index - 1)...index, with: [replacement])
        activeLayerID = replacement.id
      }
    }
  }

  func moveLayers(fromOffsets offsets: IndexSet, toOffset destination: Int) {
    let selected = activeLayerID
    mutate(actionName: "Reorder Layers") {
      layers.move(fromOffsets: offsets, toOffset: destination)
      activeLayerID = selected
    }
  }

  func setVisible(_ visible: Bool, for id: UUID) {
    guard layers.contains(where: { $0.id == id }) else { return }
    mutate(actionName: visible ? "Show Layer" : "Hide Layer") {
      update(id) { $0.isVisible = visible }
    }
  }

  func setOpacity(_ opacity: Double, for id: UUID) {
    guard layers.contains(where: { $0.id == id }) else { return }
    mutate(actionName: "Layer Opacity") {
      update(id) { $0.opacity = min(1, max(0, opacity)) }
    }
  }

  func rename(_ name: String, for id: UUID) {
    let cleaned = name.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !cleaned.isEmpty, layers.contains(where: { $0.id == id }) else { return }
    mutate(actionName: "Rename Layer", refresh: false) { update(id) { $0.name = cleaned } }
  }

  func exportPNG() async -> Data? {
    await exportImage(format: .png)
  }

  /// Render the flattened composite and encode it in `format`, off the main
  /// actor so a large canvas does not stall the UI.
  ///
  /// `onWhite` flattens transparent areas onto white even for formats that
  /// could keep them — chosen in the export sheet, because a PNG whose
  /// transparency silently became black in another viewer read as "the export
  /// doesn't look like Photoslop" (#300).
  func exportImage(
    format: ExportFormat, quality: CGFloat = 0.9, onWhite: Bool = false
  ) async -> Data? {
    let capturedLayers = layers
    let capturedSize = canvasSize
    return await Task.detached(priority: .userInitiated) {
      format.encode(
        Self.render(layers: capturedLayers, size: capturedSize), quality: quality,
        flattenToWhite: onWhite)
    }.value
  }

  /// Collapse every visible layer into one, exactly as the canvas composites
  /// them — opacity applied, strokes baked in, transparency kept. The iPad
  /// mirror of `photoslop-cli --flatten` and the desktop's Document.flatten
  /// (#300): "I couldn't make the text and background with opacity one image
  /// manually."
  func flattenImage() {
    guard layers.count > 1 else { return }
    let flattened = Self.render(layers: layers, size: canvasSize)
    mutate(actionName: "Flatten Image") {
      let layer = RasterLayer(name: "Flattened", image: flattened)
      layers = [layer]
      activeLayerID = layer.id
    }
  }

  /// A layer the composite leaves out while the placement box draws it live.
  ///
  /// Not part of `EditorState` and so not undoable, because it is not an edit —
  /// it is the difference between where a layer *is* and where a finger is
  /// currently dragging it to. Without it the layer would appear twice during a
  /// placement: once committed underneath, once following the box.
  @Published var previewSuppressedLayerID: UUID? {
    didSet { if oldValue != previewSuppressedLayerID { refreshCanvas() } }
  }

  func refreshCanvas() {
    renderRevision += 1
    let expectedRevision = renderRevision
    let capturedLayers = layers.filter { $0.id != previewSuppressedLayerID }
    let capturedSize = canvasSize
    let excludedID = activeLayerID

    // Publish the generation *before* the work is queued, so a render that has
    // already been superseded can decline to start.
    //
    // The revision guard below always dropped stale results, but only after the
    // render had run and allocated a canvas-sized bitmap. A burst of mutations
    // therefore stacked concurrent full-canvas renders, each holding the whole
    // layer array alive for its duration (#309). `Task.detached` does not
    // inherit cancellation from its parent, so cancelling `renderTask` alone
    // would not stop the render — the generation box is what the detached work
    // can actually see.
    let generation = renderGeneration
    generation.set(expectedRevision)

    renderTask?.cancel()
    renderTask = Task { @MainActor [weak self] in
      let image = await Task.detached(priority: .userInitiated) { () -> UIImage? in
        guard generation.get() == expectedRevision else { return nil }
        return Self.render(
          layers: capturedLayers,
          size: capturedSize,
          excludingDrawingFor: excludedID
        )
      }.value
      guard let self, let image, renderRevision == expectedRevision else { return }
      canvasBackground = image
    }
  }

  static func render(
    layers: [RasterLayer],
    size: CGSize,
    excludingDrawingFor excludedID: UUID? = nil
  ) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let bounds = CGRect(origin: .zero, size: size)
    return UIGraphicsImageRenderer(size: size, format: format).image { context in
      context.cgContext.interpolationQuality = .high
      for layer in layers where layer.isVisible && layer.opacity > 0 {
        // A layer occupies its own frame, which is the whole canvas for every
        // layer that predates bounded extents (#309) and a tight box around the
        // glyphs for a text layer. Drawing into `bounds` unconditionally would
        // stretch a bounded layer across the canvas.
        layer.image.draw(in: layer.frame, blendMode: .normal, alpha: layer.opacity)
        if layer.id != excludedID, !layer.drawing.strokes.isEmpty {
          layer.drawing.image(from: bounds, scale: 1).draw(
            in: bounds,
            blendMode: .normal,
            alpha: layer.opacity
          )
        }
      }
    }
  }

  static func solidImage(size: CGSize, color: UIColor) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = color.cgColor.alpha == 1
    return UIGraphicsImageRenderer(size: size, format: format).image { context in
      color.setFill()
      context.fill(CGRect(origin: .zero, size: size))
    }
  }

  static func normalizedImage(_ image: UIImage) -> UIImage {
    // Already normalised — decoded PNGs and ImageIO thumbnails land here.
    // Redrawing would allocate a second full-size bitmap for zero pixel change.
    if image.imageOrientation == .up, image.scale == 1, image.cgImage != nil {
      return image
    }
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: image.size, format: format).image { _ in
      image.draw(in: CGRect(origin: .zero, size: image.size))
    }
  }

  private func installNewDocument(size: CGSize) {
    canvasSize = size
    let background = Self.solidImage(size: size, color: .white)
    let layer = RasterLayer(name: "Background", image: background)
    layers = [layer]
    activeLayerID = layer.id
    refreshCanvas()
  }

  private func currentState() -> EditorState {
    EditorState(layers: layers, activeLayerID: activeLayerID, canvasSize: canvasSize)
  }

  private func restore(_ state: EditorState, actionName: String) {
    let redo = currentState()
    layers = state.layers
    activeLayerID = state.activeLayerID
    canvasSize = state.canvasSize
    mutationRevision += 1
    registerUndo(previous: redo, actionName: actionName)
    refreshCanvas()
  }

  private func mutate(
    actionName: String,
    refresh: Bool = true,
    _ operation: () -> Void
  ) {
    let previous = currentState()
    objectWillChange.send()
    operation()
    mutationRevision += 1
    registerUndo(previous: previous, actionName: actionName)
    if refresh { refreshCanvas() }
  }

  private func registerUndo(previous: EditorState, actionName: String) {
    guard let undoManager else { return }
    undoManager.registerUndo(withTarget: self) { target in
      target.restore(previous, actionName: actionName)
    }
    undoManager.setActionName(actionName)
  }

  private func updateActive(_ operation: (inout RasterLayer) -> Void) {
    guard let id = activeLayerID else { return }
    update(id, operation)
  }

  private func update(_ id: UUID, _ operation: (inout RasterLayer) -> Void) {
    guard let index = layers.firstIndex(where: { $0.id == id }) else { return }
    operation(&layers[index])
  }

  private func uniqueName(base: String) -> String {
    let names = Set(layers.map(\.name))
    guard names.contains(base) else { return base }
    var number = 2
    while names.contains("\(base) \(number)") { number += 1 }
    return "\(base) \(number)"
  }

  enum ImportError: LocalizedError {
    case invalidImage
    case resourceLimit(String)

    var errorDescription: String? {
      switch self {
      case .invalidImage:
        return "The selected file is not a readable image."
      case .resourceLimit(let message):
        return message
      }
    }
  }
}

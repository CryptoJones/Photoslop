// SPDX-License-Identifier: Apache-2.0
import Foundation
import PencilKit
import SwiftUI
import UIKit
import UniformTypeIdentifiers

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

  var isText: Bool { text != nil }

  init(
    id: UUID = UUID(),
    name: String,
    image: UIImage,
    drawing: PKDrawing = PKDrawing(),
    isVisible: Bool = true,
    opacity: Double = 1,
    text: TextContent? = nil,
    source: UIImage? = nil,
    placement: CGRect? = nil
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

  weak var undoManager: UndoManager?
  private var mutationRevision = 0
  /// State from before the current drag, so the gesture undoes as one step.
  private var textMoveOrigin: EditorState?
  private var renderRevision = 0

  /// The size a document starts at when nobody has said otherwise.
  static let defaultCanvasSize = CGSize(width: 2048, height: 1536)

  /// True for a document that has never had its canvas size chosen, so the
  /// editor offers the choice on first appearance instead of silently settling
  /// for the default.
  @Published private(set) var awaitingCanvasSizeChoice = false

  init() {
    installNewDocument(size: Self.defaultCanvasSize)
    awaitingCanvasSizeChoice = true
  }

  /// Called once the choice has been offered, so it is not asked again when the
  /// view reappears after a sheet, a rotation, or a return from the background.
  func canvasSizeChoiceOffered() {
    awaitingCanvasSizeChoice = false
  }

  required init(configuration: ReadConfiguration) throws {
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
    let sx = size.width / canvasSize.width
    let sy = size.height / canvasSize.height
    let transform = CGAffineTransform(scaleX: sx, y: sy)
    mutate(actionName: "Resize Document") {
      canvasSize = size
      layers = layers.map { layer in
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
    mutate(actionName: actionName) {
      canvasSize = size
      layers = layers.map { layer in
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
    at anchor: CGPoint
  ) -> Bool {
    let content = TextContent(string: text, fontSize: fontSize, color: color, anchor: anchor)
    guard let image = Self.renderText(content, canvasSize: canvasSize) else { return false }
    mutate(actionName: "Add Text") {
      let layer = RasterLayer(
        name: TextLayerRenderer.layerName(for: text), image: image, text: content)
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
    color: UIColor
  ) -> Bool {
    guard let existing = layers.first(where: { $0.id == id })?.text else { return false }
    let content = TextContent(
      string: string, fontSize: fontSize, color: color, anchor: existing.anchor)
    guard let image = Self.renderText(content, canvasSize: canvasSize) else { return false }
    mutate(actionName: "Edit Text") {
      update(id) {
        $0.image = image
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
    guard let image = Self.renderText(content, canvasSize: canvasSize) else { return false }

    // One undo step for the whole gesture, which means the state to return to
    // is the one from before the *first* sample. Registering on the last sample
    // instead would only ever undo the final pixel of the drag.
    let origin = textMoveOrigin ?? currentState()
    if coalesce { textMoveOrigin = origin }

    objectWillChange.send()
    update(id) {
      $0.image = image
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
      canvasSize: canvasSize
    )
  }

  /// Replace the document's contents with an image, fitted to the canvas.
  ///
  /// This used to take the canvas from the image — `canvasSize = normalized.size`
  /// — which threw away the size the person chose when they created the
  /// document. Importing a photo into a 1920x1080 canvas silently produced a
  /// 4032x3024 one. The canvas someone picked is the canvas they keep; the photo
  /// is scaled to fit it and centred (#258).
  func importImage(data: Data, suggestedName: String? = nil) throws {
    let normalized = try ProjectArchive.decodeImage(data)
    mutate(actionName: "Import Image") {
      let layer = RasterLayer(
        name: suggestedName ?? "Imported image",
        image: Self.fitted(normalized, into: canvasSize))
      layers = [layer]
      activeLayerID = layer.id
    }
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
    let prepared = images.map {
      (name: $0.name, image: Self.fitted($0.image, into: canvas))
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
        $0.source = source
        $0.placement = rect
      }
    }
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

  /// Fit a text layer to `rect`: the anchor moves to its corner and the type
  /// scales to the largest size that still fits inside the box.
  ///
  /// Text was placed and then stuck — dropped on the canvas at whatever size
  /// the sheet asked for, with no way to fit it to what is underneath (#261).
  /// The box is a container: type keeps its own shape, so it scales by
  /// whichever axis of the box runs out first. A first version scaled by
  /// width alone, which made a box dragged taller a silent no-op — reported
  /// as "fit text can't be resized".
  @discardableResult
  func fitTextLayer(_ id: UUID, to rect: CGRect) -> Bool {
    guard let existing = layers.first(where: { $0.id == id })?.text else { return false }
    let measured = TextLayerRenderer.measure(
      text: existing.string, fontSize: CGFloat(existing.fontSize))
    guard measured.width > 1, measured.height > 1 else { return false }
    var content = existing
    let scale = min(rect.width / measured.width, rect.height / measured.height)
    content.fontSize = Double(max(1, CGFloat(existing.fontSize) * scale))
    content.x = Double(rect.minX)
    content.y = Double(rect.minY)
    guard let image = Self.renderText(content, canvasSize: canvasSize) else { return false }
    mutate(actionName: "Fit Text") {
      update(id) {
        $0.image = image
        $0.text = content
      }
    }
    return true
  }

  /// The box a text layer currently occupies, for the placement box to open on.
  func textRect(for id: UUID) -> CGRect? {
    guard let content = layers.first(where: { $0.id == id })?.text else { return nil }
    let measured = TextLayerRenderer.measure(
      text: content.string, fontSize: CGFloat(content.fontSize))
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
  func exportImage(format: ExportFormat, quality: CGFloat = 0.9) async -> Data? {
    let capturedLayers = layers
    let capturedSize = canvasSize
    return await Task.detached(priority: .userInitiated) {
      format.encode(
        Self.render(layers: capturedLayers, size: capturedSize), quality: quality)
    }.value
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
    Task { @MainActor [weak self] in
      let image = await Task.detached(priority: .userInitiated) {
        Self.render(
          layers: capturedLayers,
          size: capturedSize,
          excludingDrawingFor: excludedID
        )
      }.value
      guard let self, renderRevision == expectedRevision else { return }
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
        layer.image.draw(in: bounds, blendMode: .normal, alpha: layer.opacity)
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

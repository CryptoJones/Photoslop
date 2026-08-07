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

  var isText: Bool { text != nil }

  init(
    id: UUID = UUID(),
    name: String,
    image: UIImage,
    drawing: PKDrawing = PKDrawing(),
    isVisible: Bool = true,
    opacity: Double = 1,
    text: TextContent? = nil
  ) {
    self.id = id
    self.name = name
    self.image = image
    self.drawing = drawing
    self.isVisible = isVisible
    self.opacity = opacity
    self.text = text
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
  @Published private(set) var canvasSize = CGSize(width: 2048, height: 1536)
  @Published private(set) var canvasBackground = UIImage()

  weak var undoManager: UndoManager?
  private var mutationRevision = 0
  /// State from before the current drag, so the gesture undoes as one step.
  private var textMoveOrigin: EditorState?
  private var renderRevision = 0

  init() {
    installNewDocument(size: CGSize(width: 2048, height: 1536))
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

  func newDocument(size: CGSize = CGSize(width: 2048, height: 1536)) {
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
    let translation = CGAffineTransform(translationX: offset.x, y: offset.y)
    mutate(actionName: "Canvas Size") {
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

  func importImage(data: Data, suggestedName: String? = nil) throws {
    let normalized = try ProjectArchive.decodeImage(data)
    mutate(actionName: "Import Image") {
      canvasSize = normalized.size
      let layer = RasterLayer(name: suggestedName ?? "Imported image", image: normalized)
      layers = [layer]
      activeLayerID = layer.id
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

  func refreshCanvas() {
    renderRevision += 1
    let expectedRevision = renderRevision
    let capturedLayers = layers
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

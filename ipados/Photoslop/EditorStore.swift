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

  init(
    id: UUID = UUID(),
    name: String,
    image: UIImage,
    drawing: PKDrawing = PKDrawing(),
    isVisible: Bool = true,
    opacity: Double = 1
  ) {
    self.id = id
    self.name = name
    self.image = image
    self.drawing = drawing
    self.isVisible = isVisible
    self.opacity = opacity
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
    let capturedLayers = layers
    let capturedSize = canvasSize
    return await Task.detached(priority: .userInitiated) {
      Self.render(layers: capturedLayers, size: capturedSize).pngData()
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

// SPDX-License-Identifier: Apache-2.0
import PencilKit
import SwiftUI
import UIKit

struct RasterLayer: Identifiable {
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

@MainActor
final class EditorStore: ObservableObject {
  @Published private(set) var layers: [RasterLayer] = []
  @Published var activeLayerID: UUID?
  @Published private(set) var canvasSize = CGSize(width: 2048, height: 1536)
  @Published private(set) var canvasBackground = UIImage()

  init() {
    newDocument()
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
    canvasSize = size
    let background = Self.solidImage(size: size, color: .white)
    let layer = RasterLayer(name: "Background", image: background)
    layers = [layer]
    activeLayerID = layer.id
    refreshCanvas()
  }

  func importImage(data: Data, suggestedName: String? = nil) throws {
    guard let source = UIImage(data: data) else { throw ImportError.invalidImage }
    let normalized = Self.normalizedImage(source)
    guard normalized.size.width >= 1, normalized.size.height >= 1 else {
      throw ImportError.invalidImage
    }
    canvasSize = normalized.size
    let layer = RasterLayer(name: suggestedName ?? "Imported image", image: normalized)
    layers = [layer]
    activeLayerID = layer.id
    refreshCanvas()
  }

  func select(_ id: UUID) {
    guard layers.contains(where: { $0.id == id }) else { return }
    activeLayerID = id
    refreshCanvas()
  }

  func setDrawing(_ drawing: PKDrawing) {
    updateActive { $0.drawing = drawing }
  }

  func addLayer() {
    let image = Self.solidImage(size: canvasSize, color: .clear)
    let layer = RasterLayer(name: uniqueName(base: "Paint Layer"), image: image)
    layers.append(layer)
    activeLayerID = layer.id
    refreshCanvas()
  }

  func duplicateActiveLayer() {
    guard let id = activeLayerID, let index = layers.firstIndex(where: { $0.id == id })
    else { return }
    var copy = layers[index]
    copy = RasterLayer(
      name: uniqueName(base: "\(copy.name) copy"),
      image: copy.image,
      drawing: copy.drawing,
      isVisible: copy.isVisible,
      opacity: copy.opacity
    )
    layers.insert(copy, at: index + 1)
    activeLayerID = copy.id
    refreshCanvas()
  }

  func deleteActiveLayer() {
    guard canDeleteLayer, let id = activeLayerID,
      let index = layers.firstIndex(where: { $0.id == id })
    else { return }
    layers.remove(at: index)
    activeLayerID = layers[min(index, layers.count - 1)].id
    refreshCanvas()
  }

  func clearActiveLayer() {
    updateActive { layer in
      layer.image = Self.solidImage(size: canvasSize, color: .clear)
      layer.drawing = PKDrawing()
    }
    refreshCanvas()
  }

  func mergeActiveDown() {
    guard let id = activeLayerID, let index = layers.firstIndex(where: { $0.id == id }),
      index > 0
    else { return }
    let lower = layers[index - 1]
    let upper = layers[index]
    let merged = Self.render(layers: [lower, upper], size: canvasSize)
    let replacement = RasterLayer(name: lower.name, image: merged)
    layers.replaceSubrange((index - 1)...index, with: [replacement])
    activeLayerID = replacement.id
    refreshCanvas()
  }

  func moveLayers(fromOffsets offsets: IndexSet, toOffset destination: Int) {
    let selected = activeLayerID
    layers.move(fromOffsets: offsets, toOffset: destination)
    activeLayerID = selected
    refreshCanvas()
  }

  func setVisible(_ visible: Bool, for id: UUID) {
    update(id) { $0.isVisible = visible }
    refreshCanvas()
  }

  func setOpacity(_ opacity: Double, for id: UUID) {
    update(id) { $0.opacity = min(1, max(0, opacity)) }
    refreshCanvas()
  }

  func rename(_ name: String, for id: UUID) {
    let cleaned = name.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !cleaned.isEmpty else { return }
    update(id) { $0.name = cleaned }
  }

  func exportPNG() -> Data? {
    Self.render(layers: layers, size: canvasSize).pngData()
  }

  func refreshCanvas() {
    canvasBackground = Self.render(
      layers: layers,
      size: canvasSize,
      excludingDrawingFor: activeLayerID
    )
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

  static func solidImage(size: CGSize, color: UIColor) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = color.cgColor.alpha == 1
    return UIGraphicsImageRenderer(size: size, format: format).image { context in
      color.setFill()
      context.fill(CGRect(origin: .zero, size: size))
    }
  }

  private static func normalizedImage(_ image: UIImage) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: image.size, format: format).image { _ in
      image.draw(in: CGRect(origin: .zero, size: image.size))
    }
  }

  enum ImportError: LocalizedError {
    case invalidImage

    var errorDescription: String? { "The selected file is not a readable image." }
  }
}

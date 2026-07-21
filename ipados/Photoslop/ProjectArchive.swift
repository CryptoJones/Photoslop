// SPDX-License-Identifier: Apache-2.0
import ImageIO
import PencilKit
import UIKit
import UniformTypeIdentifiers

extension UTType {
  static let photoslopProject = UTType(
    exportedAs: "io.ronin48.photoslop.project",
    conformingTo: .package
  )
}

struct ProjectManifest: Codable {
  static let currentVersion = 1

  var version: Int
  var canvas: PixelSize
  var activeLayerID: UUID?
  var layers: [LayerRecord]

  struct PixelSize: Codable {
    var width: Int
    var height: Int
  }

  struct LayerRecord: Codable {
    var id: UUID
    var name: String
    var isVisible: Bool
    var opacity: Double
  }
}

struct ProjectLayerPayload: @unchecked Sendable {
  var image: UIImage
  var drawing: PKDrawing
}

struct ProjectSnapshot: @unchecked Sendable {
  var manifest: ProjectManifest
  var layers: [UUID: ProjectLayerPayload]
}

enum ProjectArchiveError: LocalizedError {
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

enum ProjectArchive {
  static let maximumDimension = 16_384
  static let maximumPixels = 100_000_000
  static let maximumLayers = 2_048
  static let maximumManifestBytes = 16 * 1_024 * 1_024
  static let maximumLayerBytes = 256 * 1_024 * 1_024
  static let maximumProjectBytes = 1 * 1_024 * 1_024 * 1_024

  static func snapshot(state: EditorState) throws -> ProjectSnapshot {
    let ids = Set(state.layers.map(\.id))
    guard isValidCanvas(state.canvasSize), !state.layers.isEmpty,
      state.layers.count <= maximumLayers, ids.count == state.layers.count,
      state.activeLayerID.map(ids.contains) ?? false,
      state.layers.allSatisfy({
        $0.image.size == state.canvasSize && $0.name.count <= 4_096
          && $0.opacity.isFinite && (0...1).contains($0.opacity)
      })
    else {
      throw ProjectArchiveError.resourceLimit("The project exceeds iPad resource limits.")
    }
    let manifest = ProjectManifest(
      version: ProjectManifest.currentVersion,
      canvas: .init(width: Int(state.canvasSize.width), height: Int(state.canvasSize.height)),
      activeLayerID: state.activeLayerID,
      layers: state.layers.map {
        .init(
          id: $0.id,
          name: $0.name,
          isVisible: $0.isVisible,
          opacity: $0.opacity
        )
      }
    )
    var payloads: [UUID: ProjectLayerPayload] = [:]
    for layer in state.layers {
      payloads[layer.id] = ProjectLayerPayload(image: layer.image, drawing: layer.drawing)
    }
    return ProjectSnapshot(manifest: manifest, layers: payloads)
  }

  static func encode(_ snapshot: ProjectSnapshot) throws -> FileWrapper {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    let manifestData = try encoder.encode(snapshot.manifest)
    guard manifestData.count <= maximumManifestBytes else {
      throw CocoaError(.fileWriteOutOfSpace)
    }
    var total = manifestData.count
    var layerFolders: [String: FileWrapper] = [:]
    for record in snapshot.manifest.layers {
      guard let payload = snapshot.layers[record.id] else {
        throw CocoaError(.fileWriteUnknown)
      }
      guard let imagePNG = payload.image.pngData(), imagePNG.count <= maximumLayerBytes else {
        throw CocoaError(.fileWriteOutOfSpace)
      }
      let drawing = payload.drawing.dataRepresentation()
      guard drawing.count <= maximumLayerBytes else { throw CocoaError(.fileWriteOutOfSpace) }
      total += imagePNG.count + drawing.count
      guard total <= maximumProjectBytes else { throw CocoaError(.fileWriteOutOfSpace) }
      layerFolders[record.id.uuidString] = FileWrapper(directoryWithFileWrappers: [
        "image.png": FileWrapper(regularFileWithContents: imagePNG),
        "drawing.data": FileWrapper(regularFileWithContents: drawing),
      ])
    }
    return FileWrapper(directoryWithFileWrappers: [
      "manifest.json": FileWrapper(regularFileWithContents: manifestData),
      "layers": FileWrapper(directoryWithFileWrappers: layerFolders),
    ])
  }

  static func decode(_ wrapper: FileWrapper) throws -> EditorState {
    guard wrapper.isDirectory, let root = wrapper.fileWrappers,
      let manifestData = root["manifest.json"]?.regularFileContents,
      manifestData.count <= maximumManifestBytes,
      let layerFolders = root["layers"]?.fileWrappers
    else { throw CocoaError(.fileReadCorruptFile) }

    let manifest = try JSONDecoder().decode(ProjectManifest.self, from: manifestData)
    guard manifest.version == ProjectManifest.currentVersion,
      !manifest.layers.isEmpty, manifest.layers.count <= maximumLayers
    else { throw CocoaError(.fileReadUnsupportedScheme) }
    let size = CGSize(width: manifest.canvas.width, height: manifest.canvas.height)
    guard isValidCanvas(size) else {
      throw ProjectArchiveError.resourceLimit("The project canvas exceeds iPad limits.")
    }

    var total = manifestData.count
    var seen = Set<UUID>()
    var layers: [RasterLayer] = []
    for record in manifest.layers {
      guard seen.insert(record.id).inserted,
        record.name.count <= 4_096,
        record.opacity.isFinite, (0...1).contains(record.opacity),
        let files = layerFolders[record.id.uuidString]?.fileWrappers,
        let imageData = files["image.png"]?.regularFileContents,
        let drawingData = files["drawing.data"]?.regularFileContents,
        imageData.count <= maximumLayerBytes, drawingData.count <= maximumLayerBytes
      else { throw CocoaError(.fileReadCorruptFile) }
      total += imageData.count + drawingData.count
      guard total <= maximumProjectBytes else {
        throw ProjectArchiveError.resourceLimit("The project exceeds the 1 GiB limit.")
      }
      let image = try decodeImage(imageData)
      guard image.size == size else { throw CocoaError(.fileReadCorruptFile) }
      let drawing = try PKDrawing(data: drawingData)
      layers.append(RasterLayer(
        id: record.id,
        name: record.name,
        image: image,
        drawing: drawing,
        isVisible: record.isVisible,
        opacity: record.opacity
      ))
    }
    if let activeLayerID = manifest.activeLayerID, !seen.contains(activeLayerID) {
      throw CocoaError(.fileReadCorruptFile)
    }
    return EditorState(
      layers: layers,
      activeLayerID: manifest.activeLayerID,
      canvasSize: size
    )
  }

  static func decodeImage(_ data: Data) throws -> UIImage {
    guard data.count <= maximumLayerBytes,
      let source = CGImageSourceCreateWithData(data as CFData, nil),
      let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
      let width = properties[kCGImagePropertyPixelWidth] as? Int,
      let height = properties[kCGImagePropertyPixelHeight] as? Int,
      isValidCanvas(CGSize(width: width, height: height)),
      let image = UIImage(data: data)
    else { throw ProjectArchiveError.invalidImage }
    return EditorStore.normalizedImage(image)
  }

  static func isValidCanvas(_ size: CGSize) -> Bool {
    guard size.width.isFinite, size.height.isFinite,
      size.width >= 1, size.height >= 1,
      size.width.rounded() == size.width, size.height.rounded() == size.height,
      size.width <= CGFloat(maximumDimension), size.height <= CGFloat(maximumDimension)
    else { return false }
    return Int(size.width) * Int(size.height) <= maximumPixels
  }
}

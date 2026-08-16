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

/// A text layer's source, kept so the words stay editable and movable.
///
/// The rendered pixels are derived from this; without it a text layer is
/// indistinguishable from any other raster once written to disk.
struct TextContent: Codable, Equatable {
  var string: String
  var fontSize: Double
  /// Nil means the system font — which is also what every document written
  /// before this field existed decodes to, the optional itself being the
  /// version gate, exactly as `LayerRecord.text` was for manifest v2.
  var fontFamily: String?
  /// The width the words wrap at, set when the layer has been fitted to a
  /// box (#296). Nil — every earlier document — lays out to the canvas edge.
  var wrapWidth: Double?
  var red: Double
  var green: Double
  var blue: Double
  var alpha: Double
  var x: Double
  var y: Double

  var anchor: CGPoint { CGPoint(x: x, y: y) }
  var color: UIColor {
    UIColor(red: red, green: green, blue: blue, alpha: alpha)
  }

  init(
    string: String, fontSize: CGFloat, color: UIColor, anchor: CGPoint,
    fontFamily: String? = nil
  ) {
    self.fontFamily = fontFamily
    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 1
    color.getRed(&r, green: &g, blue: &b, alpha: &a)
    self.string = string
    self.fontSize = Double(fontSize)
    self.red = Double(r)
    self.green = Double(g)
    self.blue = Double(b)
    self.alpha = Double(a)
    self.x = Double(anchor.x)
    self.y = Double(anchor.y)
  }
}

struct ProjectManifest: Codable {
  /// Version 2 added `LayerRecord.text`. Version 1 documents still open: the
  /// field is optional, so they decode with no text layers, which is exactly
  /// what they had. Readers accept anything up to this; a bump that rejected
  /// older files would strand every project already on a device.
  static let currentVersion = 2
  static let oldestReadableVersion = 1

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
    /// Present only on text layers. Absent in version 1 documents.
    var text: TextContent?
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
          opacity: $0.opacity,
          text: $0.text
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
    var root: [String: FileWrapper] = [
      "manifest.json": FileWrapper(regularFileWithContents: manifestData),
      "layers": FileWrapper(directoryWithFileWrappers: layerFolders),
    ]
    if let preview = previewPNG(for: snapshot), total + preview.count <= maximumProjectBytes {
      root["preview.png"] = FileWrapper(regularFileWithContents: preview)
    }
    return FileWrapper(directoryWithFileWrappers: root)
  }

  /// The document's face in the Files app.
  ///
  /// Files shows a generic icon for every `.photoslop` package because nothing
  /// inside one is a picture a thumbnail extension could cheaply reach — the
  /// layers are separate PNGs plus PencilKit data, and compositing them is the
  /// editor's job, not something to do in an extension's memory budget (#267).
  /// So the composite is flattened here, at save time, where it is already
  /// paid for, and bounded to 1024 pixels on the long side. `decode` never
  /// looks for it: a document without one (anything saved before 2.9.x) still
  /// opens, and simply has no preview until its next save.
  static let previewMaximumDimension: CGFloat = 1_024

  private static func previewPNG(for snapshot: ProjectSnapshot) -> Data? {
    let layers = snapshot.manifest.layers.compactMap { record -> RasterLayer? in
      guard let payload = snapshot.layers[record.id] else { return nil }
      return RasterLayer(
        id: record.id,
        name: record.name,
        image: payload.image,
        drawing: payload.drawing,
        isVisible: record.isVisible,
        opacity: record.opacity,
        text: record.text
      )
    }
    let size = CGSize(
      width: CGFloat(snapshot.manifest.canvas.width),
      height: CGFloat(snapshot.manifest.canvas.height)
    )
    let composite = EditorStore.render(layers: layers, size: size)
    let scale = min(1, previewMaximumDimension / max(size.width, size.height))
    guard scale < 1 else { return composite.pngData() }
    let target = CGSize(
      width: max(1, (size.width * scale).rounded()),
      height: max(1, (size.height * scale).rounded())
    )
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let preview = UIGraphicsImageRenderer(size: target, format: format).image { context in
      context.cgContext.interpolationQuality = .high
      composite.draw(in: CGRect(origin: .zero, size: target))
    }
    return preview.pngData()
  }

  static func decode(_ wrapper: FileWrapper) throws -> EditorState {
    guard wrapper.isDirectory, let root = wrapper.fileWrappers,
      let manifestData = root["manifest.json"]?.regularFileContents,
      manifestData.count <= maximumManifestBytes,
      let layerFolders = root["layers"]?.fileWrappers
    else { throw CocoaError(.fileReadCorruptFile) }

    let manifest = try JSONDecoder().decode(ProjectManifest.self, from: manifestData)
    guard (ProjectManifest.oldestReadableVersion...ProjectManifest.currentVersion)
      .contains(manifest.version),
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
        opacity: record.opacity,
        text: record.text
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

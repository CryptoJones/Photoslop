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
  ///
  /// Version 3 added `LayerRecord.origin` and relaxed the rule that every layer
  /// image is exactly canvas-sized (#309). A version 1 or 2 layer has no origin
  /// and must still fill the canvas, which is precisely what those files
  /// contain, so they decode unchanged.
  ///
  /// Version 4 added `LayerRecord.effects`, the live appearance stack (#316).
  /// The records are the desktop's normalised effect objects verbatim — the
  /// same JSON `photoslop-effects` carries in an `.ora` — so a future ORA
  /// round trip is a copy, not a translation. A version 3 document has none
  /// and decodes with an empty stack, which is what it showed.
  static let currentVersion = 4
  static let oldestReadableVersion = 1

  var version: Int
  var canvas: PixelSize
  var activeLayerID: UUID?
  var layers: [LayerRecord]

  struct PixelSize: Codable {
    var width: Int
    var height: Int
  }

  struct PixelPoint: Codable {
    var x: Int
    var y: Int
  }

  struct LayerRecord: Codable {
    var id: UUID
    var name: String
    var isVisible: Bool
    var opacity: Double
    /// Present only on text layers. Absent in version 1 documents.
    var text: TextContent?
    /// Where the layer's image sits on the canvas. Absent before version 3,
    /// where every layer image was required to be exactly canvas-sized and so
    /// always sat at the top-left.
    var origin: PixelPoint?
    /// The layer's live effects, absent when it has none and before version 4.
    var effects: EffectStack?
  }

  /// A layer's effect list as the manifest carries it, read leniently: an
  /// entry the app cannot make sense of is dropped rather than failing the
  /// document, which is `appearance.normalize_effects`' rule too.
  struct EffectStack: Codable, Equatable {
    var effects: [LayerEffect]

    init(_ effects: [LayerEffect]) { self.effects = effects }

    init(from decoder: Decoder) throws {
      effects = LayerEffect.normalized(try [JSONValue](from: decoder))
    }

    func encode(to encoder: Encoder) throws {
      try effects.encode(to: encoder)
    }
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
        // A layer no longer has to BE the canvas — it has to FIT it (#309).
        // The bound is what keeps a corrupt or hostile document from
        // describing a layer far outside the canvas it claims to belong to.
        isLayerFrameValid($0.frame, canvas: state.canvasSize) && $0.name.count <= 4_096
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
          text: $0.text,
          origin: $0.origin == .zero
            ? nil
            : .init(x: Int($0.origin.x.rounded()), y: Int($0.origin.y.rounded())),
          effects: $0.effects.isEmpty ? nil : .init($0.effects)
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
      // Pooled per layer: pngData()'s CoreGraphics intermediates are
      // autoreleased, and without a drain here every layer's encoding scratch
      // stays alive until the whole document is encoded (#349).
      try autoreleasepool {
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
        text: record.text,
        // The origin was left out when #309 introduced it, so a bounded text
        // layer's preview drew it at the top-left wherever it sat (#316).
        origin: record.origin.map { CGPoint(x: CGFloat($0.x), y: CGFloat($0.y)) } ?? .zero,
        effects: record.effects?.effects ?? []
      )
    }
    let size = CGSize(
      width: CGFloat(snapshot.manifest.canvas.width),
      height: CGFloat(snapshot.manifest.canvas.height)
    )
    let scale = min(1, previewMaximumDimension / max(size.width, size.height))
    guard scale < 1 else { return EditorStore.render(layers: layers, size: size).pngData() }
    // Rendered straight at preview size: compositing at full document size
    // first would cost one extra canvas-sized buffer (plus one per
    // stroke-bearing layer) purely to throw the pixels away in the downscale.
    let target = CGSize(
      width: max(1, (size.width * scale).rounded()),
      height: max(1, (size.height * scale).rounded())
    )
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let bounds = CGRect(origin: .zero, size: size)
    let preview = UIGraphicsImageRenderer(size: target, format: format).image { context in
      context.cgContext.interpolationQuality = .high
      context.cgContext.scaleBy(x: scale, y: scale)
      for layer in layers where layer.isVisible && layer.opacity > 0 {
        autoreleasepool {
          // Effects at 1x through the scaled context: the planes are the
          // layer's size, not the preview's, and the transform shrinks them.
          let rendered = layer.hasRenderableEffects
            ? AppearanceRenderer.planes(for: layer) : ([], .zero)
          AppearanceRenderer.draw(
            planes: rendered.planes, under: true, origin: rendered.origin,
            layerOpacity: layer.opacity)
          layer.image.draw(in: layer.frame, blendMode: .normal, alpha: layer.opacity)
          AppearanceRenderer.draw(
            planes: rendered.planes, under: false, origin: rendered.origin,
            layerOpacity: layer.opacity)
          if !layer.drawing.strokes.isEmpty {
            // Rasterised at the preview's own scale — a preview-sized bitmap,
            // not a canvas-sized one.
            layer.drawing.image(from: bounds, scale: scale).draw(
              in: bounds, blendMode: .normal, alpha: layer.opacity)
          }
        }
      }
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
      // Pooled per layer: decoding runs a full-bitmap UIImage(data:) whose
      // CoreGraphics scratch is autoreleased; without a drain the transients
      // for every layer coexist until the loop ends (#349).
      let decoded: RasterLayer = try autoreleasepool {
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
        // Before version 3 a layer image WAS the canvas, and a file claiming
        // otherwise is corrupt. From version 3 a layer carries an origin and only
        // has to fit (#309).
        let origin: CGPoint
        if let recorded = record.origin, manifest.version >= 3 {
          origin = CGPoint(x: CGFloat(recorded.x), y: CGFloat(recorded.y))
        } else {
          origin = .zero
        }
        guard manifest.version >= 3 ? true : image.size == size,
          isLayerFrameValid(CGRect(origin: origin, size: image.size), canvas: size)
        else { throw CocoaError(.fileReadCorruptFile) }
        let drawing = try PKDrawing(data: drawingData)
        return RasterLayer(
          id: record.id,
          name: record.name,
          image: image,
          drawing: drawing,
          isVisible: record.isVisible,
          opacity: record.opacity,
          text: record.text,
          origin: origin,
          // Effects arrived with version 4; an older manifest carrying the
          // key is not one this app wrote, so the key is ignored as `origin`
          // is above.
          effects: manifest.version >= 4 ? record.effects?.effects ?? [] : []
        )
      }
      layers.append(decoded)
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

  /// Decode `data` no larger than it needs to be to fill `canvas`.
  ///
  /// The batch importer fits every photo to the canvas, so decoding a source at
  /// full resolution and *then* scaling it down is pure waste — and it is the
  /// waste that killed the app (#309). A 12 MP phone photo costs 48.8 MB as a
  /// bitmap; the canvas-sized layer it becomes costs 12.6 MB. On device the
  /// full-size intermediates for a batch reached a 2.44 GB footprint and jetsam
  /// killed the frontmost process with `vm-pageshortage`.
  ///
  /// ImageIO can decode straight to the size we want, so the 12 MP bitmap is
  /// never created at all. Three details matter and each is a bug if missed:
  ///
  /// * `kCGImageSourceThumbnailMaxPixelSize` bounds the **longest side**. Sizing
  ///   it to the canvas's longest side would leave an aspect-mismatched photo
  ///   smaller than the canvas, and `fitted` would then upscale it — softer
  ///   output than today. So the bound is computed from the fitted extent.
  /// * `...WithTransform` applies the EXIF orientation. Without it a photo taken
  ///   in portrait decodes on its side, which the old `UIImage(data:)` path
  ///   handled for us.
  /// * The scale is clamped at 1, because a source smaller than the canvas
  ///   should be decoded at its own size and left for `fitted` to enlarge —
  ///   decoding "up" would allocate more than the file contains.
  static func decodeImage(_ data: Data, fittingInto canvas: CGSize) throws -> UIImage {
    guard data.count <= maximumLayerBytes,
      let source = CGImageSourceCreateWithData(data as CFData, nil),
      let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
      let width = properties[kCGImagePropertyPixelWidth] as? Int,
      let height = properties[kCGImagePropertyPixelHeight] as? Int,
      width > 0, height > 0,
      isValidCanvas(CGSize(width: width, height: height)),
      canvas.width > 0, canvas.height > 0
    else { throw ProjectArchiveError.invalidImage }

    let fit = min(canvas.width / CGFloat(width), canvas.height / CGFloat(height))
    let longestSide = CGFloat(max(width, height)) * min(fit, 1)
    let limit = max(1, Int(longestSide.rounded(.up)))

    guard
      let thumbnail = CGImageSourceCreateThumbnailAtIndex(
        source, 0,
        [
          kCGImageSourceCreateThumbnailFromImageAlways: true,
          kCGImageSourceThumbnailMaxPixelSize: limit,
          kCGImageSourceCreateThumbnailWithTransform: true,
          kCGImageSourceShouldCacheImmediately: true,
        ] as CFDictionary)
    else { throw ProjectArchiveError.invalidImage }
    return UIImage(cgImage: thumbnail)
  }

  /// The pixel dimensions of an encoded image, without decoding it.
  ///
  /// `CGImageSourceCopyPropertiesAtIndex` reads the header. The old path built
  /// a whole `UIImage` — a full-resolution bitmap — purely to ask for `.size`,
  /// which on a 12 MP photo is 48.8 MB to answer a question the first few bytes
  /// of the file already contain.
  static func imageSize(of data: Data) -> CGSize? {
    guard data.count <= maximumLayerBytes,
      let source = CGImageSourceCreateWithData(data as CFData, nil),
      let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
      let width = properties[kCGImagePropertyPixelWidth] as? Int,
      let height = properties[kCGImagePropertyPixelHeight] as? Int
    else { return nil }
    // EXIF orientations 5-8 swap the axes; the decoded image is the transpose.
    let orientation = properties[kCGImagePropertyOrientation] as? Int ?? 1
    let swapped = (5...8).contains(orientation)
    return CGSize(
      width: swapped ? CGFloat(height) : CGFloat(width),
      height: swapped ? CGFloat(width) : CGFloat(height))
  }

  /// Whether a layer's frame is a sane place to be on `canvas`.
  ///
  /// A bounded layer may hang over an edge — that is what placement has always
  /// allowed — but it must intersect the canvas, be finite, sit on whole
  /// pixels, and stay within the same pixel budget a canvas does. Without this
  /// a document could describe a layer at an absurd offset and cost an
  /// unbounded allocation on open.
  static func isLayerFrameValid(_ frame: CGRect, canvas: CGSize) -> Bool {
    guard frame.origin.x.isFinite, frame.origin.y.isFinite,
      frame.width >= 1, frame.height >= 1,
      frame.origin.x.rounded() == frame.origin.x,
      frame.origin.y.rounded() == frame.origin.y,
      frame.width <= CGFloat(maximumDimension), frame.height <= CGFloat(maximumDimension),
      Int(frame.width) * Int(frame.height) <= maximumPixels
    else { return false }
    return frame.intersects(CGRect(origin: .zero, size: canvas))
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

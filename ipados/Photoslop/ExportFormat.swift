// SPDX-License-Identifier: Apache-2.0
import ImageIO
import UIKit
import UniformTypeIdentifiers

/// Image formats the flattened composite can be exported to.
///
/// Encoding goes through ImageIO rather than the `UIImage` convenience methods,
/// which only cover PNG and JPEG.
enum ExportFormat: String, CaseIterable, Identifiable {
  case png
  case jpeg
  case heic
  case tiff
  case gif
  case bmp

  var id: String { rawValue }

  var displayName: String {
    switch self {
    case .png: "PNG"
    case .jpeg: "JPEG"
    case .heic: "HEIC"
    case .tiff: "TIFF"
    case .gif: "GIF"
    case .bmp: "BMP"
    }
  }

  var utType: UTType {
    switch self {
    case .png: .png
    case .jpeg: .jpeg
    case .heic: .heic
    case .tiff: .tiff
    case .gif: .gif
    case .bmp: .bmp
    }
  }

  var fileExtension: String { utType.preferredFilenameExtension ?? rawValue }

  /// Whether the encoder preserves an alpha channel.
  ///
  /// JPEG and BMP have none, and GIF carries only a single fully transparent
  /// palette index rather than the smooth alpha a painted layer produces. All
  /// three are flattened onto white first, so transparent areas export white
  /// rather than the black an unflattened alpha channel collapses to.
  var preservesTransparency: Bool {
    switch self {
    case .png, .heic, .tiff: true
    case .jpeg, .gif, .bmp: false
    }
  }

  /// Whether `quality` affects the encoded output.
  var isLossy: Bool {
    switch self {
    case .jpeg, .heic: true
    case .png, .tiff, .gif, .bmp: false
    }
  }

  /// Encode `image`, flattening it first when the format cannot store alpha.
  func encode(_ image: UIImage, quality: CGFloat = 0.9) -> Data? {
    let source = preservesTransparency ? image : Self.flattenedOntoWhite(image)
    guard let cgImage = source.cgImage else { return nil }

    let container = NSMutableData()
    guard
      let destination = CGImageDestinationCreateWithData(
        container, utType.identifier as CFString, 1, nil)
    else { return nil }

    var options: [CFString: Any] = [:]
    if isLossy {
      options[kCGImageDestinationLossyCompressionQuality] = quality
    }
    CGImageDestinationAddImage(destination, cgImage, options as CFDictionary)
    guard CGImageDestinationFinalize(destination) else { return nil }
    return container as Data
  }

  private static func flattenedOntoWhite(_ image: UIImage) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = image.scale
    format.opaque = true
    let bounds = CGRect(origin: .zero, size: image.size)
    return UIGraphicsImageRenderer(size: image.size, format: format).image { context in
      UIColor.white.setFill()
      context.fill(bounds)
      image.draw(in: bounds)
    }
  }
}

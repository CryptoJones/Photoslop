// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import Foundation

/// Starting canvas sizes offered when creating a document.
///
/// Print sizes are given in pixels at 300 DPI, the usual print resolution, so
/// the numbers can be handed straight to a fixed-pixel canvas.
enum CanvasPreset: String, CaseIterable, Identifiable {
  case standard
  case square
  case hd
  case uhd4K
  case a4
  case usLetter
  case photo6x4
  case custom

  var id: String { rawValue }

  var displayName: String {
    switch self {
    case .standard: "Standard"
    case .square: "Square"
    case .hd: "HD"
    case .uhd4K: "4K UHD"
    case .a4: "A4 at 300 DPI"
    case .usLetter: "US Letter at 300 DPI"
    case .photo6x4: "Photo 6 by 4 at 300 DPI"
    case .custom: "Custom"
    }
  }

  /// Nil for `.custom`, whose dimensions come from the caller.
  var size: CGSize? {
    switch self {
    case .standard: CGSize(width: 2048, height: 1536)
    case .square: CGSize(width: 2048, height: 2048)
    case .hd: CGSize(width: 1920, height: 1080)
    case .uhd4K: CGSize(width: 3840, height: 2160)
    case .a4: CGSize(width: 2480, height: 3508)
    case .usLetter: CGSize(width: 2550, height: 3300)
    case .photo6x4: CGSize(width: 1800, height: 1200)
    case .custom: nil
    }
  }

  var subtitle: String {
    guard let size else { return "Enter any size" }
    return "\(Int(size.width)) by \(Int(size.height)) px"
  }

  /// Clamp a requested canvas to what a project can actually hold.
  ///
  /// The per-side and total-pixel caps are the archive's, so a size accepted
  /// here is a size the document can be saved at. Returns nil when the request
  /// cannot be satisfied at all, which the sheet surfaces rather than silently
  /// creating a different canvas than the one asked for.
  static func validated(width: Int, height: Int) -> CGSize? {
    guard width > 0, height > 0 else { return nil }
    guard
      width <= ProjectArchive.maximumDimension,
      height <= ProjectArchive.maximumDimension,
      width * height <= ProjectArchive.maximumPixels
    else { return nil }
    let size = CGSize(width: width, height: height)
    return ProjectArchive.isValidCanvas(size) ? size : nil
  }
}

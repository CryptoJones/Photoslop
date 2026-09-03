// SPDX-License-Identifier: Apache-2.0
import PencilKit
import UIKit

/// Drawing tools offered by the canvas tool strip.
///
/// PencilKit ink types differ in which Apple Pencil inputs they react to.
/// `.pen` varies with force alone, so a tilted Pencil draws exactly the same
/// stroke as an upright one. `.pencil` and `.marker` additionally read the
/// altitude and azimuth of a tilted Pencil, which is what gives them a
/// broader stroke as the Pencil lies down.
///
/// The bucket is the one tool that is not a PencilKit ink: it fills the
/// tapped region of the layer's pixels through the `PixelBuffer` seam (#325),
/// so it takes the ink colour and opacity but no width, and a tolerance
/// instead.
enum BrushTool: String, CaseIterable, Identifiable {
  case pen
  case pencil
  case marker
  case eraser
  case bucket

  var id: String { rawValue }

  var displayName: String {
    switch self {
    case .pen: "Pen"
    case .pencil: "Pencil"
    case .marker: "Marker"
    case .eraser: "Eraser"
    case .bucket: "Bucket"
    }
  }

  var symbolName: String {
    switch self {
    case .pen: "pencil.tip"
    case .pencil: "pencil"
    case .marker: "highlighter"
    case .eraser: "eraser"
    case .bucket: "drop.fill"
    }
  }

  /// Whether the ink colour and opacity controls apply to this tool.
  var usesInk: Bool { inkType != nil || fillsOnTap }

  /// Whether the brush width control applies to this tool.
  var usesWidth: Bool { inkType != nil }

  /// Whether a tap on the canvas fills instead of a stroke painting.
  var fillsOnTap: Bool { self == .bucket }

  /// Whether the stroke shape changes with how far the Pencil is tilted.
  var respondsToTilt: Bool {
    switch self {
    case .pencil, .marker: true
    case .pen, .eraser, .bucket: false
    }
  }

  private var inkType: PKInkingTool.InkType? {
    switch self {
    case .pen: .pen
    case .pencil: .pencil
    case .marker: .marker
    case .eraser, .bucket: nil
    }
  }

  /// The PencilKit tool this brush installs on the canvas.
  ///
  /// The bucket installs a pen it never uses: the canvas view is disabled for
  /// as long as a tap tool is armed, so no stroke can reach it.
  func pkTool(color: UIColor, width: CGFloat) -> PKTool {
    if fillsOnTap { return PKInkingTool(.pen, color: color, width: width) }
    guard let inkType else { return PKEraserTool(.bitmap) }
    return PKInkingTool(inkType, color: color, width: width)
  }
}

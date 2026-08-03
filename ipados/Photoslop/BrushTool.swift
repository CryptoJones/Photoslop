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
enum BrushTool: String, CaseIterable, Identifiable {
  case pen
  case pencil
  case marker
  case eraser

  var id: String { rawValue }

  var displayName: String {
    switch self {
    case .pen: "Pen"
    case .pencil: "Pencil"
    case .marker: "Marker"
    case .eraser: "Eraser"
    }
  }

  var symbolName: String {
    switch self {
    case .pen: "pencil.tip"
    case .pencil: "pencil"
    case .marker: "highlighter"
    case .eraser: "eraser"
    }
  }

  /// Whether the ink color and width controls apply to this tool.
  var usesInk: Bool { inkType != nil }

  /// Whether the stroke shape changes with how far the Pencil is tilted.
  var respondsToTilt: Bool {
    switch self {
    case .pencil, .marker: true
    case .pen, .eraser: false
    }
  }

  private var inkType: PKInkingTool.InkType? {
    switch self {
    case .pen: .pen
    case .pencil: .pencil
    case .marker: .marker
    case .eraser: nil
    }
  }

  /// The PencilKit tool this brush installs on the canvas.
  func pkTool(color: UIColor, width: CGFloat) -> PKTool {
    guard let inkType else { return PKEraserTool(.bitmap) }
    return PKInkingTool(inkType, color: color, width: width)
  }
}

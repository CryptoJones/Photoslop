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
/// The bucket and the wand are the tools that are not a PencilKit ink: a tap
/// finds the region of similar colour under it through the `PixelBuffer`
/// seam, and the bucket fills it (#325) while the wand selects it (#326). Both
/// take a tolerance instead of a width; only the bucket uses the ink.
enum BrushTool: String, CaseIterable, Identifiable {
  case pen
  case pencil
  case marker
  case eraser
  case bucket
  case wand

  var id: String { rawValue }

  var displayName: String {
    switch self {
    case .pen: "Pen"
    case .pencil: "Pencil"
    case .marker: "Marker"
    case .eraser: "Eraser"
    case .bucket: "Bucket"
    case .wand: "Magic Wand"
    }
  }

  var symbolName: String {
    switch self {
    case .pen: "pencil.tip"
    case .pencil: "pencil"
    case .marker: "highlighter"
    case .eraser: "eraser"
    case .bucket: "drop.fill"
    case .wand: "wand.and.rays"
    }
  }

  /// Whether the ink colour and opacity controls apply to this tool.
  var usesInk: Bool { inkType != nil || fillsOnTap }

  /// Whether the brush width control applies to this tool.
  var usesWidth: Bool { inkType != nil }

  /// Whether a tap on the canvas fills instead of a stroke painting.
  var fillsOnTap: Bool { self == .bucket }

  /// Whether a tap on the canvas selects instead of a stroke painting.
  var selectsOnTap: Bool { self == .wand }

  /// Whether the tool acts on a tap rather than a stroke, so the canvas is
  /// told to hand taps over and hold strokes back.
  var actsOnTap: Bool { fillsOnTap || selectsOnTap }

  /// Whether the colour tolerance control applies to this tool.
  var usesTolerance: Bool { actsOnTap }

  /// Whether the stroke shape changes with how far the Pencil is tilted.
  var respondsToTilt: Bool {
    switch self {
    case .pencil, .marker: true
    case .pen, .eraser, .bucket, .wand: false
    }
  }

  private var inkType: PKInkingTool.InkType? {
    switch self {
    case .pen: .pen
    case .pencil: .pencil
    case .marker: .marker
    case .eraser, .bucket, .wand: nil
    }
  }

  /// The PencilKit tool this brush installs on the canvas.
  ///
  /// A tap tool installs a pen it never uses: the canvas view is disabled for
  /// as long as one is armed, so no stroke can reach it.
  func pkTool(color: UIColor, width: CGFloat) -> PKTool {
    if actsOnTap { return PKInkingTool(.pen, color: color, width: width) }
    guard let inkType else { return PKEraserTool(.bitmap) }
    return PKInkingTool(inkType, color: color, width: width)
  }
}

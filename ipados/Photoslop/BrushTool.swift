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
/// take a tolerance instead of a width; only the bucket uses the ink. The
/// marquee and the lasso (#370) are not inks either: a drag draws the shape
/// that becomes the selection when the finger lifts.
enum BrushTool: String, CaseIterable, Identifiable {
  case pen
  case pencil
  case marker
  case eraser
  case bucket
  case wand
  case rectSelect
  case lasso

  var id: String { rawValue }

  var displayName: String {
    switch self {
    case .pen: "Pen"
    case .pencil: "Pencil"
    case .marker: "Marker"
    case .eraser: "Eraser"
    case .bucket: "Bucket"
    case .wand: "Magic Wand"
    case .rectSelect: "Rectangle Select"
    case .lasso: "Lasso Select"
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
    case .rectSelect: "rectangle.dashed"
    case .lasso: "lasso"
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

  /// Whether a one-finger drag draws a selection shape instead of a stroke
  /// (#370). The canvas treats it like an overlay: drawing is suspended and
  /// two fingers pan.
  var selectsByDrag: Bool { self == .rectSelect || self == .lasso }

  /// Whether the tool produces a selection, so the combine mode applies.
  var selects: Bool { selectsOnTap || selectsByDrag }

  /// Whether the colour tolerance control applies to this tool.
  var usesTolerance: Bool { actsOnTap }

  /// Whether the stroke shape changes with how far the Pencil is tilted.
  var respondsToTilt: Bool {
    switch self {
    case .pencil, .marker: true
    case .pen, .eraser, .bucket, .wand, .rectSelect, .lasso: false
    }
  }

  private var inkType: PKInkingTool.InkType? {
    switch self {
    case .pen: .pen
    case .pencil: .pencil
    case .marker: .marker
    case .eraser, .bucket, .wand, .rectSelect, .lasso: nil
    }
  }

  /// What the eraser shows while it is a pixel eraser under a selection: a
  /// frosted stroke over the picture, replaced by the pixels' absence when
  /// the finger lifts.
  static let selectionEraserInk = UIColor(white: 1, alpha: 0.6)

  /// The PencilKit tool this brush installs on the canvas.
  ///
  /// A tap or drag tool installs a pen it never uses: the canvas view is
  /// disabled for as long as one is armed, so no stroke can reach it.
  ///
  /// With `clippedToSelection` (#370) the eraser is not PencilKit's stroke
  /// eraser — the strokes it would erase are pixels by then — but a pen of
  /// the fixed-width bitmap eraser's default width (the plain bitmap eraser
  /// reports none) whose coverage is taken out of the layer's pixels when
  /// the stroke is committed, so it erases a photograph as readily as a
  /// stroke.
  func pkTool(color: UIColor, width: CGFloat, clippedToSelection: Bool = false) -> PKTool {
    if actsOnTap || selectsByDrag { return PKInkingTool(.pen, color: color, width: width) }
    guard let inkType else {
      if clippedToSelection {
        return PKInkingTool(
          .pen, color: Self.selectionEraserInk,
          width: PKEraserTool.EraserType.fixedWidthBitmap.defaultWidth)
      }
      return PKEraserTool(.bitmap)
    }
    return PKInkingTool(inkType, color: color, width: width)
  }
}

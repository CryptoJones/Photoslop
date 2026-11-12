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
  case eyedropper

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
    case .eyedropper: "Eyedropper"
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
    case .eyedropper: "eyedropper"
    }
  }

  /// The tool's name as a caption, for the places that have room for one.
  ///
  /// Shorter than `displayName`, which stays the name the accessibility tree
  /// and the tests use. "Magic Wand" and "Rectangle Select" are the two that
  /// do not fit under an icon without shrinking to nothing, and the caption is
  /// decoration: the button still announces and identifies itself by the full
  /// name.
  var caption: String {
    switch self {
    case .pen: "Pen"
    case .pencil: "Pencil"
    case .marker: "Marker"
    case .eraser: "Eraser"
    case .bucket: "Bucket"
    case .wand: "Wand"
    case .rectSelect: "Rect"
    case .lasso: "Lasso"
    case .eyedropper: "Eyedropper"
    }
  }

  /// What the tool does with a finger, in one line.
  ///
  /// The hardest thing to learn in a drawing app on a touch screen is which
  /// tools answer a tap and which answer a drag: the bucket, the wand and the
  /// eyedropper all take a tap, everything else takes a stroke, and the icons
  /// say nothing about it. So the strip that names the tool in hand also says
  /// what the finger should do.
  var usageHint: String {
    switch self {
    case .pen: "Drag to draw a line"
    case .pencil: "Drag to draw; tilt for width"
    case .marker: "Drag to draw a wide stroke"
    case .eraser: "Drag to erase"
    case .bucket: "Tap to fill this colour"
    case .wand: "Tap to select this colour"
    case .rectSelect: "Drag a box to select"
    case .lasso: "Draw a loop to select"
    case .eyedropper: "Tap to pick up a colour"
    }
  }

  /// The job a tool does, so the palette can be grouped.
  ///
  /// Nine glyphs in a row read as nine unrelated things. Draw, fill, select and
  /// pick are four jobs, and a hairline between them says which is which
  /// without adding a single control.
  enum Family {
    case draw
    case fill
    case select
    case pick
  }

  var family: Family {
    switch self {
    case .pen, .pencil, .marker, .eraser: .draw
    case .bucket: .fill
    case .wand, .rectSelect, .lasso: .select
    case .eyedropper: .pick
    }
  }

  /// Whether the ink colour and opacity controls apply to this tool.
  ///
  /// The eyedropper paints nothing, but it is the tool that *sets* the ink,
  /// so the swatch stays on screen: it is where the sampled colour appears.
  var usesInk: Bool { inkType != nil || fillsOnTap || samplesOnTap }

  /// Whether the brush width control applies to this tool.
  var usesWidth: Bool { inkType != nil }

  /// Whether a tap on the canvas fills instead of a stroke painting.
  var fillsOnTap: Bool { self == .bucket }

  /// Whether a tap on the canvas selects instead of a stroke painting.
  var selectsOnTap: Bool { self == .wand }

  /// Whether a tap on the canvas samples the colour under it into the ink
  /// swatch, the desktop's Eyedropper (`I`).
  var samplesOnTap: Bool { self == .eyedropper }

  /// Whether the tool acts on a tap rather than a stroke, so the canvas is
  /// told to hand taps over and hold strokes back.
  var actsOnTap: Bool { fillsOnTap || selectsOnTap || samplesOnTap }

  /// Whether a one-finger drag draws a selection shape instead of a stroke
  /// (#370). The canvas treats it like an overlay: drawing is suspended and
  /// two fingers pan.
  var selectsByDrag: Bool { self == .rectSelect || self == .lasso }

  /// Whether the tool produces a selection, so the combine mode applies.
  var selects: Bool { selectsOnTap || selectsByDrag }

  /// Whether the colour tolerance control applies to this tool. The
  /// eyedropper reads the one pixel under the finger, so it has no region
  /// to grow and no tolerance to grow it by.
  var usesTolerance: Bool { fillsOnTap || selectsOnTap }

  /// Whether the stroke shape changes with how far the Pencil is tilted.
  var respondsToTilt: Bool {
    switch self {
    case .pencil, .marker: true
    case .pen, .eraser, .bucket, .wand, .rectSelect, .lasso, .eyedropper: false
    }
  }

  private var inkType: PKInkingTool.InkType? {
    switch self {
    case .pen: .pen
    case .pencil: .pencil
    case .marker: .marker
    case .eraser, .bucket, .wand, .rectSelect, .lasso, .eyedropper: nil
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

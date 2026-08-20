// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import Foundation

/// Brush width, in proportion to the canvas it paints on (#314).
///
/// Width is measured in **document pixels** and deliberately stays that way.
/// Scaling it to the view instead was considered and rejected: zooming in would
/// enlarge the brush in document terms by exactly the amount the zoom shrank it,
/// so fine detail work by zooming in — the main reason to zoom at all — would
/// become impossible, and the same slider value would lay down different strokes
/// depending on how zoomed in the user happened to be. Document-space sizing is
/// what makes zoom the fine-tuning mechanism: at 4x, finger travel maps to a
/// quarter as many document pixels and the 1 px step becomes judgeable by eye.
///
/// What *was* wrong is that the numbers never considered the canvas. A width of
/// 8 px is sensible on a small canvas and invisible on a large one: on the
/// default 2048x1536 canvas fitted to a phone (about 0.19x) an 8 px stroke lands
/// roughly 1.5 pt wide, and the slider's old ceiling of 80 reached only about
/// 15 pt. The reporter concluded finger drawing was broken; the strokes had been
/// landing the whole time, too thin to see.
///
/// Both fractions below are the old constants generalised — they reproduce 8 and
/// 80 almost exactly at the default canvas, so a default document behaves as it
/// always did and only larger canvases change.
enum BrushMetrics {
  /// 1536 * 0.005 = 7.68, which rounds to the 8 that used to be hardcoded.
  static let defaultFraction: Double = 0.005
  /// 1536 * 0.05 = 76.8, close to the 80 that used to be hardcoded.
  static let maximumFraction: Double = 0.05
  /// Never offer a narrower range than the app shipped with.
  static let smallestMaximum: Double = 80
  static let minimumWidth: Double = 1

  /// The shorter side is what a stroke has to be visible against.
  private static func reference(_ canvas: CGSize) -> Double {
    let side = Double(min(canvas.width, canvas.height))
    return side.isFinite && side > 0 ? side : 0
  }

  /// The width a fresh document starts at.
  static func defaultWidth(for canvas: CGSize) -> Double {
    let side = reference(canvas)
    guard side > 0 else { return 8 }
    return max(minimumWidth, (side * defaultFraction).rounded())
  }

  /// The widest stroke the slider offers.
  static func maximumWidth(for canvas: CGSize) -> Double {
    let side = reference(canvas)
    guard side > 0 else { return smallestMaximum }
    return max(smallestMaximum, (side * maximumFraction).rounded())
  }

  /// A width carried across a canvas resize, keeping its apparent weight.
  ///
  /// CryptoJones chose scaling over leaving it alone (2026-08-19): resizing the
  /// document should keep the brush looking the same size against the picture,
  /// rather than silently becoming a hairline on a bigger canvas — which is the
  /// very failure this issue is about.
  static func rescaled(_ width: Double, from old: CGSize, to new: CGSize) -> Double {
    let before = reference(old)
    let after = reference(new)
    guard before > 0, after > 0, width.isFinite else { return width }
    let scaled = (width * after / before).rounded()
    return min(max(scaled, minimumWidth), maximumWidth(for: new))
  }
}

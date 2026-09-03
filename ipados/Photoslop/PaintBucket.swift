// SPDX-License-Identifier: Apache-2.0
import UIKit

/// What a bucket tap did, so the view can say why nothing happened.
enum PaintBucketOutcome: Equatable {
  /// The region was filled and one undo step registered.
  case filled
  /// The tap was off the canvas, or the region already holds the ink.
  case unchanged
  /// The active layer is a text layer, whose pixels are re-rendered from the
  /// words on every edit; a fill would not survive the next Edit Text.
  case textLayer
  /// The pixel buffer is not affordable right now; the memory notice is up.
  case refused
}

extension EditorStore {
  /// The desktop bucket's default tolerance (`ToolOptions.tolerance`), 0...255.
  static let defaultBucketTolerance = 32

  /// Tap-to-fill on the active layer (#325): the region of similar colour
  /// connected to `point` (in canvas pixels) takes the ink, premultiplied the
  /// way the desktop bucket premultiplies its foreground colour, so the same
  /// tap with the same ink writes the same word on both platforms.
  ///
  /// Inside a selection (#326) the fill stops at the selection's edge, and a
  /// tap outside it fills nothing — the desktop's `sel_mask`. With nothing
  /// selected a fill runs to the region's edge.
  @discardableResult
  func paintBucket(at point: CGPoint, tolerance: Int, color: UIColor, opacity: CGFloat)
    -> PaintBucketOutcome
  {
    guard let layer = activeLayer else { return .unchanged }
    if layer.isText { return .textLayer }
    let x = Int(point.x.rounded(.down))
    let y = Int(point.y.rounded(.down))
    guard x >= 0, y >= 0, x < Int(canvasSize.width), y < Int(canvasSize.height) else {
      return .unchanged
    }
    guard Self.canAffordLayer(canvas: canvasSize) else {
      memoryPressureNotice = Self.memoryRefusal
      return .refused
    }
    let ink = PixelBuffer.premultipliedWord(color: color, opacity: opacity)
    let within = selection?.bits
    let filled = applyPixelOperation(to: layer.id, actionName: "Paint Bucket") { buffer in
      FloodFill.fill(&buffer, x: x, y: y, color: ink, tolerance: tolerance, selection: within)
        != nil
    }
    return filled ? .filled : .unchanged
  }
}

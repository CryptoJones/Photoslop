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
  /// selected a fill runs to the region's edge. Through a feathered
  /// selection (#370) the region is found across the whole layer, as a
  /// desktop filter's is, and the ink lands by weight — full inside, fading
  /// over the ramp either side of the hard edge, none beyond it — the way
  /// Delete Selection and the brushes fade.
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
      guard let selection, let weights = selection.weights else {
        return FloodFill.fill(
          &buffer, x: x, y: y, color: ink, tolerance: tolerance, selection: within) != nil
      }
      // The desktop bucket writes its word outright; a feathered one is the
      // unclipped region blended in by weight (`npimage.blend_by_weights`,
      // as `_apply_filter` does with `mask=None` and the weights).
      let width = buffer.width, height = buffer.height
      guard
        let (region, _) = buffer.withWords({ words in
          FloodFill.mask(
            words: words, width: width, height: height, x: x, y: y, tolerance: tolerance)
        })
      else { return false }
      var changed = false
      buffer.withMutableWords { words in
        for i in 0..<words.count where region[i] {
          let out = PixelBuffer.blend(words[i], toward: ink, weight: weights[i])
          if out != words[i] {
            words[i] = out
            changed = true
          }
        }
      }
      return changed
    }
    return filled ? .filled : .unchanged
  }
}

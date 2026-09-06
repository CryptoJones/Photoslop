// SPDX-License-Identifier: Apache-2.0
import UIKit

/// What Fill Selection did, so the view can say why nothing happened.
enum FillSelectionOutcome: Equatable {
  /// The selected pixels took the ink, one undo step.
  case filled
  /// Nothing is selected, there is no active layer, or the selection already
  /// holds the ink.
  case unchanged
  /// The active layer is a text layer: its pixels are re-rendered from the
  /// words on every edit, so paint laid over them would not survive Edit Text.
  case textLayer
  /// The pixel buffer is not affordable right now; the memory notice is up.
  case refused
}

extension EditorStore {
  /// Fill the selection with a flat colour (#393): every selected pixel of the
  /// active layer takes the ink, one undo step. The desktop's Fill Layer
  /// (`Alt+Backspace`) confined to the selection, which is what
  /// `docs/v1/selections.md` has always said fills do.
  ///
  /// This is the bucket without the flood: the bucket grows a region of
  /// *similar colour* from the tap and stops at the selection's edge, so a
  /// selection spanning several colours takes the ink only where the tap
  /// reached. Filling a wand or lasso selection outright had no route on iOS
  /// at all — the shape was selectable, deletable and copyable, but not
  /// paintable.
  ///
  /// The ink is premultiplied the way the bucket premultiplies it, so the same
  /// swatch writes the same word through either route. Through a feathered
  /// selection (#370) a pixel takes the ink by its weight, so the fill fades
  /// over the ramp exactly as Delete Selection fades.
  @discardableResult
  func fillSelection(color: UIColor, opacity: CGFloat) -> FillSelectionOutcome {
    guard let layer = activeLayer, let selection else { return .unchanged }
    if layer.isText { return .textLayer }
    guard Self.canAffordLayer(canvas: canvasSize) else {
      memoryPressureNotice = Self.memoryRefusal
      return .refused
    }
    let ink = PixelBuffer.premultipliedWord(color: color, opacity: opacity)
    let filled = applyPixelOperation(to: layer.id, actionName: "Fill Selection") { buffer in
      // `borrowPixels` hands back a canvas-sized buffer, which is the frame the
      // selection is in; anything else would index the mask off its own end.
      guard buffer.width == selection.width, buffer.height == selection.height else { return false }
      var changed = false
      buffer.withMutableWords { words in
        for i in 0..<words.count {
          let weight = selection.weight(at: i)
          guard weight != 0 else { continue }
          let out = PixelBuffer.blend(words[i], toward: ink, weight: weight)
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

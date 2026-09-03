// SPDX-License-Identifier: Apache-2.0
import UIKit

/// What a wand tap did, so the view can say why nothing happened.
enum MagicWandOutcome: Equatable {
  /// The selection changed.
  case selected
  /// The tap was off the canvas, there is no active layer, or a subtract
  /// found no selection to cut from.
  case unchanged
  /// The pixel buffer is not affordable right now; the memory notice is up.
  case refused
}

/// What Delete Selection did.
enum DeleteSelectionOutcome: Equatable {
  /// The selected pixels of the active layer were cleared, one undo step.
  case deleted
  /// Nothing is selected, or there is no active layer.
  case unchanged
  /// The active layer is a text layer: its pixels are re-rendered from the
  /// words on every edit, so a hole cut in them would not survive Edit Text.
  case textLayer
  /// The pixel buffer is not affordable right now; the memory notice is up.
  case refused
}

extension EditorStore {
  /// Tap-to-select on the active layer (#326): the region of colour similar
  /// to the pixel under `point` (in canvas pixels) becomes the selection —
  /// the pixels connected to the tap when `contiguous`, every pixel in the
  /// layer within tolerance when not (the desktop's colour-range mode). The
  /// desktop's `MagicWandTool.press` with the Shift and Alt clicks made into
  /// a choice: `combine` says whether the region replaces, joins or is cut
  /// from the selection already there.
  ///
  /// The wand reads the layer as the canvas shows it — strokes included — but
  /// writes nothing, so a text layer is fine to select on and no undo step is
  /// registered. The region is found over the whole layer regardless of what
  /// is already selected, as the desktop wand does; it is the bucket that
  /// stays inside the selection, not the wand.
  @discardableResult
  func magicWand(
    at point: CGPoint, tolerance: Int, contiguous: Bool, combine: SelectionCombine
  ) -> MagicWandOutcome {
    guard let layer = activeLayer else { return .unchanged }
    let x = Int(point.x.rounded(.down))
    let y = Int(point.y.rounded(.down))
    let width = Int(canvasSize.width), height = Int(canvasSize.height)
    guard x >= 0, y >= 0, x < width, y < height else { return .unchanged }
    guard Self.canAffordLayer(canvas: canvasSize) else {
      memoryPressureNotice = Self.memoryRefusal
      return .refused
    }
    guard let buffer = borrowPixels(of: layer) else { return .unchanged }
    let found = buffer.withWords { words in
      contiguous
        ? FloodFill.mask(words: words, width: width, height: height, x: x, y: y, tolerance: tolerance)
        : FloodFill.globalMask(
          words: words, width: width, height: height, x: x, y: y, tolerance: tolerance)
    }
    guard let (mask, _) = found else { return .unchanged }
    let region = SelectionMask(width: width, height: height, bits: mask)
    switch combine {
    case .replace:
      setSelection(region)
    case .add:
      setSelection(selection.map { $0.united(with: region) } ?? region)
    case .subtract:
      guard let current = selection else { return .unchanged }
      setSelection(current.subtracting(region))
    }
    return .selected
  }

  /// The desktop's Select All.
  func selectAll() {
    setSelection(SelectionMask.all(width: Int(canvasSize.width), height: Int(canvasSize.height)))
  }

  /// The desktop's Deselect.
  func deselect() {
    setSelection(nil)
  }

  /// Every unselected pixel selected and vice versa. With nothing selected
  /// this is Select All, so the marching ants never simply vanish.
  func invertSelection() {
    guard let selection else { return selectAll() }
    setSelection(selection.inverted())
  }

  /// The desktop's Delete Selection: clear the selected pixels of the active
  /// layer to transparent, one undo step. With the wand this is how a
  /// background comes off a photo — tap it, delete it. Through a feathered
  /// selection (#370) a pixel is cleared by its weight, so the edge fades
  /// rather than cuts.
  @discardableResult
  /// `actionName` is the undo step's label: Delete Selection names itself,
  /// and Cut passes its own so the copy-then-clear reads as one "Cut" (#374),
  /// the desktop's `beginMacro("Cut")`.
  func deleteSelection(actionName: String = "Delete Selection") -> DeleteSelectionOutcome {
    guard let layer = activeLayer, let selection else { return .unchanged }
    if layer.isText { return .textLayer }
    guard Self.canAffordLayer(canvas: canvasSize) else {
      memoryPressureNotice = Self.memoryRefusal
      return .refused
    }
    let cleared = applyPixelOperation(to: layer.id, actionName: actionName) { buffer in
      var changed = false
      buffer.withMutableWords { words in
        for i in 0..<words.count where words[i] != 0 {
          let weight = selection.weight(at: i)
          guard weight != 0 else { continue }
          let out = PixelBuffer.blend(words[i], toward: 0, weight: weight)
          if out != words[i] {
            words[i] = out
            changed = true
          }
        }
      }
      return changed
    }
    return cleared ? .deleted : .unchanged
  }
}

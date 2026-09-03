// SPDX-License-Identifier: Apache-2.0
import UIKit

/// The marquee, the lasso and the feather (#370): the desktop's
/// `RectSelectTool`, `LassoTool` and Select ▸ Feather on the store.
extension EditorStore {
  /// The desktop's feather dialogue offers `max(1, feather) or 8` — 8 px for a
  /// selection that has none yet.
  static let defaultFeather = 8
  /// The desktop's `QInputDialog.getInt` bounds for the feather, in pixels.
  static let featherRange = 0...100

  /// Rectangle Select: a drag from `a` to `b`, in canvas pixels, combined
  /// with the selection that is there. A drag under 2 px in both directions
  /// is a click, which on the desktop clears the selection; here it clears
  /// under New Selection and does nothing under Add or Subtract.
  func selectRectangle(from a: CGPoint, to b: CGPoint, combine: SelectionCombine) {
    let width = Int(canvasSize.width), height = Int(canvasSize.height)
    guard abs(b.x - a.x) >= 2 || abs(b.y - a.y) >= 2 else { return combineShape(nil, combine) }
    combineShape(SelectionMask.rectangle(from: a, to: b, width: width, height: height), combine)
  }

  /// Lasso Select: the polygon through `points` (canvas pixels), closed back
  /// to the first, under the desktop's odd-even rule. Fewer than three points
  /// enclose nothing, and count as a click.
  func selectLasso(_ points: [CGPoint], combine: SelectionCombine) {
    let width = Int(canvasSize.width), height = Int(canvasSize.height)
    guard points.count >= 3 else { return combineShape(nil, combine) }
    combineShape(SelectionMask.polygon(points, width: width, height: height), combine)
  }

  /// The wand's New / Add / Subtract, for a shape. A shape that selects
  /// nothing — off the canvas, degenerate — is a click for this purpose.
  private func combineShape(_ region: SelectionMask?, _ combine: SelectionCombine) {
    let region = region.flatMap { $0.isEmpty ? nil : $0 }
    switch combine {
    case .replace:
      setSelection(region)
    case .add:
      guard let region else { return }
      setSelection(selection.map { $0.united(with: region) } ?? region)
    case .subtract:
      guard let region, let current = selection else { return }
      setSelection(current.subtracting(region))
    }
  }

  /// Select ▸ Feather: soften the current selection's edge by `radius`
  /// pixels (0 for a hard edge again) — `Document.selection_feather`. Not an
  /// undo step, like the selection itself. Computing the weights costs one
  /// float plane of the canvas, so it is refused like a layer would be when
  /// that is not affordable (#354).
  func setFeather(_ radius: Int) {
    guard let selection else { return }
    let radius = min(max(radius, Self.featherRange.lowerBound), Self.featherRange.upperBound)
    guard radius != selection.feather else { return }
    guard radius == 0 || Self.canAffordLayer(canvas: canvasSize) else {
      memoryPressureNotice = Self.memoryRefusal
      return
    }
    setSelection(selection.feathered(by: radius))
  }
}

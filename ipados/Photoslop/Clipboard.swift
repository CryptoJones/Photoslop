import PencilKit
import SwiftUI
import UIKit

/// What a Copy did, so the caller can say so.
enum CopyOutcome: Equatable {
  case copied
  /// Nothing to copy: no active layer, or a layer with no pixels.
  case unchanged
  case refused
}

/// What a Cut did. Cut is Copy plus Delete Selection, so it can fail either
/// half's way.
enum CutOutcome: Equatable {
  case cut
  /// The desktop's "Cut needs a selection" status message.
  case needsSelection
  /// Text layers are edited as text; the desktop refuses pixel edits on them
  /// too.
  case textLayer
  case unchanged
  case refused
}

/// What a Paste did.
enum PasteOutcome: Equatable {
  case pasted
  /// The pasteboard holds nothing this app can place.
  case empty
  case refused
}

/// Cut, Copy and Paste over a selection (#374).
///
/// The desktop's `action_copy` / `action_cut` / `action_paste` are the
/// reference. Two things it does that matter here: a copy is cropped to the
/// selection's bounds and remembers where it came from, so pasting puts the
/// pixels back where they were rather than at the origin; and a copy made in
/// another app has no such origin and lands at the top-left.
///
/// Where this deliberately differs from the desktop: the desktop clips a copy
/// with a hard `setClipPath`, because on the desktop the feather radius is
/// read only by filters. On iOS the feather is read by everything that writes
/// through a selection (#370), so a copy is weighted by the same mask Delete
/// Selection reads. That is what makes Cut and Paste a round trip: what Paste
/// puts back is exactly what Cut took away, soft edge included.
extension EditorStore {
  /// The selected pixels of the active layer onto the system pasteboard,
  /// cropped to the selection's bounds and faded by its weights. With no
  /// selection this copies the whole layer, as the desktop does.
  ///
  /// Text layers are copied as the pixels they render to — a picture of the
  /// words, which is what the desktop puts on the clipboard as well.
  func copySelection() -> CopyOutcome {
    guard let layer = activeLayer else { return .unchanged }
    guard Self.canAffordLayer(canvas: canvasSize) else {
      memoryPressureNotice = Self.memoryRefusal
      return .refused
    }
    guard let source = borrowPixels(of: layer) else { return .unchanged }

    // With no selection the whole layer goes, at the canvas origin.
    let region: PixelRect
    if let selection, let bounds = selection.bounds {
      guard selection.width == source.width, selection.height == source.height else {
        return .unchanged
      }
      region = bounds
    } else {
      region = PixelRect(x: 0, y: 0, width: source.width, height: source.height)
    }
    guard region.width > 0, region.height > 0 else { return .unchanged }

    var words = [UInt32](repeating: 0, count: region.width * region.height)
    source.withWords { src in
      for row in 0..<region.height {
        let sy = region.y + row
        guard sy >= 0, sy < source.height else { continue }
        let sourceRow = sy * source.width
        let destinationRow = row * region.width
        for column in 0..<region.width {
          let sx = region.x + column
          guard sx >= 0, sx < source.width else { continue }
          let index = sourceRow + sx
          // No selection is full coverage; a feathered one fades at the edge
          // exactly as Delete Selection does.
          let weight = selection?.weight(at: index) ?? 255
          words[destinationRow + column] = PixelBuffer.scaled(src[index], by: weight)
        }
      }
    }

    let buffer = PixelBuffer(width: region.width, height: region.height, words: words)
    guard let image = buffer.makeImage() else { return .unchanged }
    UIPasteboard.general.image = image
    // The desktop's `_clip_from_us`: only a copy this app made knows where it
    // belongs, and only until something else writes to the pasteboard.
    rememberPasteOrigin(CGPoint(x: region.x, y: region.y))
    return .copied
  }

  /// Copy, then clear the selected pixels, as one undo step named "Cut" — the
  /// desktop's `beginMacro("Cut")` around `action_delete_selection`.
  func cutSelection() -> CutOutcome {
    guard selection != nil else { return .needsSelection }
    guard let layer = activeLayer else { return .unchanged }
    if layer.isText { return .textLayer }
    switch copySelection() {
    case .refused: return .refused
    case .unchanged: return .unchanged
    case .copied: break
    }
    switch deleteSelection(actionName: "Cut") {
    case .deleted: return .cut
    case .textLayer: return .textLayer
    case .refused: return .refused
    case .unchanged: return .unchanged
    }
  }

  /// The pasteboard's image as a new layer above the active one, one undo step.
  ///
  /// A copy this app made goes back where it came from; anything else — a
  /// screenshot, a photo copied in another app — lands at the top-left, as it
  /// does on the desktop. A remembered origin that no longer touches the
  /// canvas (the document was resized or replaced since) also falls back to
  /// the top-left rather than pasting off-screen.
  func paste() -> PasteOutcome {
    guard let image = UIPasteboard.general.image else { return .empty }
    guard Self.canAffordLayer(canvas: canvasSize) else {
      memoryPressureNotice = Self.memoryRefusal
      return .refused
    }
    var origin = ownedPasteOrigin ?? .zero
    let canvas = CGRect(origin: .zero, size: canvasSize)
    if !CGRect(origin: origin, size: image.size).intersects(canvas) {
      origin = .zero
    }
    let placed = Self.drawn(
      image, in: CGRect(origin: origin, size: image.size), canvas: canvasSize)
    insertLayer(image: placed, named: "Pasted", actionName: "Paste")
    return .pasted
  }

  /// Whether there is anything on the pasteboard to paste. Read by the menu so
  /// Paste is inert rather than silently doing nothing.
  var canPaste: Bool { UIPasteboard.general.hasImages }
}

// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import Foundation

/// The document's selection (#326): one flag per canvas pixel, in canvas
/// coordinates, the way the desktop's `Document.selection` is a path in
/// canvas coordinates rather than anything a layer owns.
///
/// A mask rather than a path because every producer and consumer on iOS
/// speaks pixels: the wand returns a mask, the bucket intersects one, Delete
/// Selection clears through one. The desktop converts its wand mask to a
/// `QPainterPath` and rasterises it back per operation (`npimage.mask_to_path`
/// / `selection_mask`); keeping the mask skips both trips and loses nothing,
/// since every iOS selection so far is pixel-aligned.
///
/// One byte per pixel — the `[Bool]` the flood fill already spends — so a
/// selection on the standard canvas costs 3 MiB, a quarter of one layer.
struct SelectionMask: Equatable {
  let width: Int
  let height: Int
  /// Row-major, one flag per canvas pixel.
  private(set) var bits: [Bool]
  /// The tight bounding rectangle of the selected pixels; nil when nothing is
  /// selected.
  private(set) var bounds: PixelRect?
  /// How many pixels are selected.
  private(set) var count: Int
  /// Tells one selection from another without comparing the bits: every
  /// mutation mints a new one, so a view can cache work keyed by it.
  private(set) var id = UUID()

  init(width: Int, height: Int, bits: [Bool]) {
    precondition(bits.count == width * height, "selection bits must cover the canvas")
    self.width = width
    self.height = height
    self.bits = bits
    (bounds, count) = Self.measure(bits, width: width, height: height)
  }

  /// The whole canvas, the desktop's Select All.
  static func all(width: Int, height: Int) -> SelectionMask {
    SelectionMask(width: width, height: height, bits: [Bool](repeating: true, count: width * height))
  }

  var isEmpty: Bool { count == 0 }

  func contains(x: Int, y: Int) -> Bool {
    guard x >= 0, x < width, y >= 0, y < height else { return false }
    return bits[y * width + x]
  }

  /// `QPainterPath.united`: this selection plus another.
  func united(with other: SelectionMask) -> SelectionMask {
    combined(with: other) { $0 || $1 }
  }

  /// `QPainterPath.subtracted`: this selection minus another.
  func subtracting(_ other: SelectionMask) -> SelectionMask {
    combined(with: other) { $0 && !$1 }
  }

  /// Every unselected pixel selected and vice versa.
  func inverted() -> SelectionMask {
    SelectionMask(width: width, height: height, bits: bits.map { !$0 })
  }

  private func combined(with other: SelectionMask, _ op: (Bool, Bool) -> Bool) -> SelectionMask {
    precondition(other.width == width && other.height == height, "selections must share a canvas")
    var out = bits
    for i in 0..<out.count { out[i] = op(bits[i], other.bits[i]) }
    return SelectionMask(width: width, height: height, bits: out)
  }

  private static func measure(_ bits: [Bool], width: Int, height: Int) -> (PixelRect?, Int) {
    var minX = Int.max, minY = Int.max, maxX = -1, maxY = -1, count = 0
    for y in 0..<height {
      let row = y * width
      for x in 0..<width where bits[row + x] {
        count += 1
        if x < minX { minX = x }
        if x > maxX { maxX = x }
        if y < minY { minY = y }
        if y > maxY { maxY = y }
      }
    }
    guard count > 0 else { return (nil, 0) }
    return (PixelRect(x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1), count)
  }

  // MARK: - Outline

  /// The selection's boundary as line segments in canvas pixels: every edge
  /// between a selected pixel and an unselected one (or the canvas edge),
  /// with collinear unit edges merged into one run so a straight border is
  /// one segment rather than a thousand. This is what the marching ants are
  /// drawn along.
  func outlineSegments() -> [(CGPoint, CGPoint)] {
    var segments: [(CGPoint, CGPoint)] = []
    // Horizontal edges: between row y-1 and row y, for y in 0...height.
    for y in 0...height {
      let above = y - 1, below = y
      var runStart: Int? = nil
      for x in 0...width {
        var edge = false
        if x < width {
          let top = above >= 0 && bits[above * width + x]
          let bottom = below < height && bits[below * width + x]
          edge = top != bottom
        }
        if edge, runStart == nil {
          runStart = x
        } else if !edge, let start = runStart {
          segments.append((CGPoint(x: start, y: y), CGPoint(x: x, y: y)))
          runStart = nil
        }
      }
    }
    // Vertical edges: between column x-1 and column x, for x in 0...width.
    for x in 0...width {
      let left = x - 1, right = x
      var runStart: Int? = nil
      for y in 0...height {
        var edge = false
        if y < height {
          let l = left >= 0 && bits[y * width + left]
          let r = right < width && bits[y * width + right]
          edge = l != r
        }
        if edge, runStart == nil {
          runStart = y
        } else if !edge, let start = runStart {
          segments.append((CGPoint(x: x, y: start), CGPoint(x: x, y: y)))
          runStart = nil
        }
      }
    }
    return segments
  }

  /// `outlineSegments()` as one path, ready to stroke.
  func outlinePath() -> CGPath {
    let path = CGMutablePath()
    for (a, b) in outlineSegments() {
      path.move(to: a)
      path.addLine(to: b)
    }
    return path
  }
}

/// How a new wand region meets the selection that is already there — the
/// desktop's plain / Shift / Alt click, as a choice a finger can make.
enum SelectionCombine: String, CaseIterable, Identifiable {
  case replace
  case add
  case subtract

  var id: String { rawValue }

  var displayName: String {
    switch self {
    case .replace: "New Selection"
    case .add: "Add to Selection"
    case .subtract: "Subtract from Selection"
    }
  }

  var symbolName: String {
    switch self {
    case .replace: "square.dashed"
    case .add: "plus.square.dashed"
    case .subtract: "minus.square"
    }
  }
}

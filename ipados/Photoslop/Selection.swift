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
/// selection on the standard canvas costs 3 MiB, a quarter of one layer. A
/// feathered selection (#370) keeps a second byte per pixel of coverage.
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
  /// The feather radius in pixels, the desktop's `Document.selection_feather`:
  /// 0 is a hard edge. Belongs to one selection — every producer starts at 0,
  /// as the desktop's `set_selection` resets it — and is set by
  /// `feathered(by:)`.
  private(set) var feather = 0
  /// Per-pixel coverage, 0...255, when feathered; nil for a hard edge, where
  /// `bits` is the coverage. `bits` stays the hard mask throughout: the ants
  /// walk it and the wand and bucket grow regions inside it; only what
  /// *writes* through the selection reads the weights.
  private(set) var weights: [UInt8]?

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

  /// How much of pixel `index` (row-major) an operation through this
  /// selection may touch: 255 inside a hard selection, 0 outside, and the
  /// feather's ramp in between.
  func weight(at index: Int) -> UInt8 {
    if let weights { return weights[index] }
    return bits[index] ? 255 : 0
  }

  /// This selection with a feather of `radius` pixels (0 or less for a hard
  /// edge) — the desktop's Select ▸ Feather, `Document.selection_feather`
  /// consumed through `npimage.feathered_weights`. The bits, bounds and count
  /// are unchanged: the selection is still the same pixels, only softer at
  /// the edge. Costs one float plane of the canvas while computing (#309).
  func feathered(by radius: Int) -> SelectionMask {
    var copy = self
    copy.id = UUID()
    copy.feather = max(0, radius)
    copy.weights =
      copy.feather > 0
      ? Self.featheredWeights(bits, width: width, height: height, feather: copy.feather) : nil
    return copy
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

  /// The selected pixels as filled rectangles in canvas pixels — one per run
  /// of selected pixels per row, with identical consecutive rows merged into
  /// one band, the way the desktop's `mask_to_path` builds a path from a wand
  /// mask. The rectangles are disjoint, so the path fills the same under
  /// either rule; it is what clips the live stroke (#370).
  func fillPath() -> CGPath {
    let path = CGMutablePath()
    var previous: [Range<Int>] = []
    var bandStart = 0
    func flush(before y: Int) {
      for run in previous {
        path.addRect(
          CGRect(x: run.lowerBound, y: bandStart, width: run.count, height: y - bandStart))
      }
    }
    for y in 0..<height {
      var runs: [Range<Int>] = []
      let row = y * width
      var x = 0
      while x < width {
        if bits[row + x] {
          let start = x
          while x < width, bits[row + x] { x += 1 }
          runs.append(start..<x)
        } else {
          x += 1
        }
      }
      if runs != previous {
        flush(before: y)
        previous = runs
        bandStart = y
      }
    }
    flush(before: height)
    return path
  }

  // MARK: - Marquee and lasso (#370)

  /// A rectangle selection from the two corners of a drag, in canvas pixels,
  /// the desktop's `RectSelectTool`: the corners are normalised, and the
  /// rectangle is rasterised the way Qt's aliased `fillPath` rasterises
  /// `QPainterPath.addRect`, so a fractional corner selects exactly the
  /// pixels the desktop selects (`SelectionParityTests`).
  static func rectangle(from a: CGPoint, to b: CGPoint, width: Int, height: Int) -> SelectionMask {
    let rect = CGRect(
      x: min(a.x, b.x), y: min(a.y, b.y), width: abs(b.x - a.x), height: abs(b.y - a.y))
    let corners = [
      CGPoint(x: rect.minX, y: rect.minY), CGPoint(x: rect.maxX, y: rect.minY),
      CGPoint(x: rect.maxX, y: rect.maxY), CGPoint(x: rect.minX, y: rect.maxY),
    ]
    return SelectionMask(
      width: width, height: height, bits: rasterise(corners, width: width, height: height))
  }

  /// A lasso selection: the polygon through `points` (closed back to the
  /// first), filled under the odd-even rule the desktop's `LassoTool` gets
  /// from `QPainterPath`'s default, so a self-crossing loop leaves its
  /// crossed-over pocket unselected on both editions.
  static func polygon(_ points: [CGPoint], width: Int, height: Int) -> SelectionMask {
    SelectionMask(
      width: width, height: height, bits: rasterise(points, width: width, height: height))
  }

  /// Qt's aliased polygon fill, pixel for pixel: `QRasterizer::rasterize`
  /// with antialiasing off and the odd-even rule, as `npimage.selection_mask`
  /// drives it. Vertices are snapped to 1/64 px (`QPainterPath` in 26.6
  /// fixed point); each edge walks the scanlines from the first pixel centre
  /// at or below its top to the last at or above its bottom with a Q16.16
  /// DDA whose slope is truncated, and every crossing is floored to a column;
  /// the spans between crossings are filled half-open while the winding is
  /// odd. None of this is how one would write a rasteriser from scratch; it
  /// is how one gets `SelectionFixture` to match to the pixel.
  static func rasterise(_ points: [CGPoint], width w: Int, height h: Int) -> [Bool] {
    var out = [Bool](repeating: false, count: w * h)
    guard w > 0, h > 0, points.count >= 3,
      points.allSatisfy({ $0.x.isFinite && $0.y.isFinite })
    else { return out }
    let limit: CGFloat = 1_048_576  // 2^20
    let clamped = points.map {
      CGPoint(x: min(max($0.x, -limit), limit), y: min(max($0.y, -limit), limit))
    }
    let minY = clamped.map(\.y).min()!
    let maxY = clamped.map(\.y).max()!
    let top = max(0, Int(minY + 0.5))  // Int(_:) truncates toward zero, as C does
    let bottom = min(h - 1, Int(maxY - 0.5))
    guard top <= bottom else { return out }
    let fixed = clamped.map {
      (x: Int(($0.x * 64 + 0.5).rounded(.down)), y: Int(($0.y * 64 + 0.5).rounded(.down)))
    }
    let leftFP = 0
    let rightFP = w << 16
    var nodes = [[(x: Int, winding: Int)]](repeating: [], count: h)
    for i in fixed.indices {
      var a = fixed[i]
      var b = fixed[(i + 1) % fixed.count]
      if a == b { continue }
      var winding = 1
      if a.y > b.y {
        swap(&a, &b)
        winding = -1
      }
      let iTop = max(top, (a.y + 32) >> 6)
      let iBottom = min(bottom, (b.y - 32) >> 6)
      if iTop > iBottom { continue }
      let aFP = 32768 + a.x * 1024
      var x: Int
      var delta: Int
      if b.x == a.x {
        x = min(max(aFP, leftFP), rightFP)
        delta = 0
      } else {
        let slope = Double(b.x - a.x) / Double(b.y - a.y)
        delta = Int(slope * 65536)
        let toFirstCentre = (iTop << 16) + 32768 - a.y * 1024
        let (product, overflow) = delta.multipliedReportingOverflow(by: toFirstCentre)
        // Qt multiplies in 64 bits too; an edge steep enough to overflow
        // that is all but horizontal, covers one scanline, and does not care.
        x = aFP + (overflow
          ? Int((Double(delta) * Double(toFirstCentre) / 65536).rounded(.down))
          : product >> 16)
      }
      for y in iTop...iBottom {
        let clampedX = min(max(x, leftFP), rightFP)
        nodes[y].append((x: clampedX >> 16, winding: winding))
        x += delta
      }
    }
    for y in 0..<h where !nodes[y].isEmpty {
      let row = nodes[y].sorted { $0.x < $1.x }
      var winding = 0
      var previous: Int? = nil
      for node in row {
        if winding & 1 == 1, let start = previous {
          let lo = max(start, 0)
          let hi = min(node.x, w)
          if lo < hi {
            for x in lo..<hi { out[y * w + x] = true }
          }
        }
        previous = node.x
        winding += node.winding
      }
    }
    return out
  }

  // MARK: - Feather (#370)

  /// `npimage.feathered_weights`, quantised: the hard mask as a float plane,
  /// box-blurred three times with a window of `2r + 1` truncated at the
  /// canvas edge, divided by the same blur of a plane of ones so the ramp
  /// runs 0...1 even against the edge, with `r = max(1, feather / 2 + 1)`.
  /// The ones plane is separable, so its blur is the product of two vectors
  /// rather than a second canvas; the mask's blur runs in place with a ring
  /// of `r + 1` rows, so the working set is one float plane (#309).
  static func featheredWeights(_ bits: [Bool], width: Int, height: Int, feather: Int) -> [UInt8] {
    let r = max(1, feather / 2 + 1)
    var plane = [Float](repeating: 0, count: width * height)
    for i in bits.indices where bits[i] { plane[i] = 1 }
    for _ in 0..<3 {
      boxBlurColumns(&plane, width: width, height: height, radius: r)
      boxBlurRows(&plane, width: width, height: height, radius: r)
    }
    var normX = [Float](repeating: 1, count: width)
    var normY = [Float](repeating: 1, count: height)
    for _ in 0..<3 {
      boxBlurRows(&normX, width: width, height: 1, radius: r)
      boxBlurRows(&normY, width: height, height: 1, radius: r)
    }
    var out = [UInt8](repeating: 0, count: width * height)
    for y in 0..<height {
      let row = y * width
      for x in 0..<width {
        let norm = max(normX[x] * normY[y], 1e-6)
        let weight = min(max(plane[row + x] / norm, 0), 1)
        out[row + x] = UInt8((weight * 255 + 0.5).rounded(.down))
      }
    }
    return out
  }

  /// One axis of `_box_blur_plane`, along each row: the sum of the `2r + 1`
  /// window, truncated at the ends, divided by the full `2r + 1` regardless —
  /// the desktop's cumulative-sum trick comes out the same.
  private static func boxBlurRows(_ plane: inout [Float], width: Int, height: Int, radius r: Int) {
    let k = Float(2 * r + 1)
    var original = [Float](repeating: 0, count: width)
    for y in 0..<height {
      let row = y * width
      for x in 0..<width { original[x] = plane[row + x] }
      var sum: Float = 0
      for x in 0..<min(r, width) { sum += original[x] }
      for x in 0..<width {
        if x + r < width { sum += original[x + r] }
        if x - r - 1 >= 0 { sum -= original[x - r - 1] }
        plane[row + x] = sum / k
      }
    }
  }

  /// The same down each column, in place: the rows already overwritten that
  /// the window still has to let go of are kept in a ring of `r + 1` rows.
  private static func boxBlurColumns(
    _ plane: inout [Float], width: Int, height: Int, radius r: Int
  ) {
    let k = Float(2 * r + 1)
    let slots = r + 1
    var ring = [Float](repeating: 0, count: slots * width)
    var sum = [Float](repeating: 0, count: width)
    for y in 0..<min(r, height) {
      let row = y * width
      for x in 0..<width { sum[x] += plane[row + x] }
    }
    for y in 0..<height {
      let row = y * width
      if y + r < height {
        let ahead = (y + r) * width
        for x in 0..<width { sum[x] += plane[ahead + x] }
      }
      let slot = (y % slots) * width
      if y - r - 1 >= 0 {
        for x in 0..<width { sum[x] -= ring[slot + x] }
      }
      for x in 0..<width {
        ring[slot + x] = plane[row + x]
        plane[row + x] = sum[x] / k
      }
    }
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

// SPDX-License-Identifier: Apache-2.0
import Foundation

/// The seven built-in filters of `photoslop.filters`, ported over
/// `PixelBuffer` (#327) to give the *same pixels* as the desktop and the CLI,
/// not merely the same look. `scripts/gen-filter-fixture.py` runs the desktop
/// code over small inputs and `FilterParityTests` compares every word.
///
/// Parity rests on three things a port could easily lose:
///
/// * **Arithmetic width.** The desktop works in `float32` (NEP 50 keeps
///   Python float scalars weak, so `0.299 * r` is a `float32` product).
///   Every constant here is a `Float` and the operations run in the same
///   left-to-right order. `Float(x)` truncates to `UInt32` the way
///   `.astype(np.uint32)` does; `np.round`/`np.rint` is `.toNearestOrEven`.
///   Film Negative is the exception: it is `float64` on the desktop, so it is
///   `Double` here.
/// * **Qt's nearest-neighbour `scaled`.** Pixelate and Retro Console shrink
///   and enlarge through `QImage.scaled` (fast transformation), whose sample
///   grid is the raster paint engine's 16.16 fixed-point walk. `nearestScaled`
///   reproduces that walk, so block edges land on the same source rows.
/// * **NumPy's generator.** Datamosh draws its motion field from
///   `SeedSequence` + `PCG64`, reproduced in `NumpyRandom`.
///
/// Every filter works in 256-row bands (`PixelBuffer.forEachBand`) where the
/// maths is per pixel, and the buffer stays premultiplied on both sides: the
/// unpremultiply / re-premultiply steps are ported as written, truncation
/// included, because that is what the fixture holds.
enum FilterAlgorithms {
  // MARK: - Word helpers

  @inline(__always) private static func alpha(_ word: UInt32) -> UInt32 { word >> 24 }
  @inline(__always) private static func red(_ word: UInt32) -> UInt32 { (word >> 16) & 0xFF }
  @inline(__always) private static func green(_ word: UInt32) -> UInt32 { (word >> 8) & 0xFF }
  @inline(__always) private static func blue(_ word: UInt32) -> UInt32 { word & 0xFF }

  /// `np.clip(x, 0, 255).astype(np.uint32)`: clamp, then truncate.
  @inline(__always) private static func clipWord(_ value: Float) -> UInt32 {
    UInt32(min(max(value, 0), 255))
  }

  @inline(__always) private static func pack(a: UInt32, r: UInt32, g: UInt32, b: UInt32) -> UInt32 {
    (a << 24) | (r << 16) | (g << 8) | b
  }

  /// `0.299 * r + 0.587 * g + 0.114 * b` in `float32`, left to right.
  @inline(__always) private static func luma(r: Float, g: Float, b: Float) -> Float {
    Float(0.299) * r + Float(0.587) * g + Float(0.114) * b
  }

  // MARK: - Qt nearest-neighbour scaling

  /// The sample grid `QImage.scaled(w, h)` uses with `Qt.FastTransformation`:
  /// the raster engine's `qt_scale_image_32bit`, a 16.16 fixed-point walk that
  /// starts half a source pixel in (`ceil(0.5 * step) - 1`) and truncates the
  /// step. An equal size is the identity, as `QImage.scaled` returns itself.
  struct NearestScale {
    let sourceWidth: Int
    let sourceHeight: Int
    let width: Int
    let height: Int
    private let stepX: Int
    private let stepY: Int
    private let baseX: Int
    private let baseY: Int
    let isIdentity: Bool

    init(from sourceWidth: Int, _ sourceHeight: Int, to width: Int, _ height: Int) {
      self.sourceWidth = sourceWidth
      self.sourceHeight = sourceHeight
      self.width = width
      self.height = height
      isIdentity = sourceWidth == width && sourceHeight == height
      let m11 = Double(width) / Double(sourceWidth)
      let m22 = Double(height) / Double(sourceHeight)
      let targetWidth = m11 * Double(sourceWidth)
      let targetHeight = m22 * Double(sourceHeight)
      let sx = Double(sourceWidth) / targetWidth
      let sy = Double(sourceHeight) / targetHeight
      stepX = Int(65536 * sx)
      stepY = Int(65536 * sy)
      baseX = Int((0.5 * sx * 65536).rounded(.up)) - 1
      baseY = Int((0.5 * sy * 65536).rounded(.up)) - 1
    }

    /// Source column for destination column `x`.
    @inline(__always) func sourceX(_ x: Int) -> Int {
      isIdentity ? x : min(sourceWidth - 1, (baseX + x * stepX) >> 16)
    }

    /// Source row for destination row `y`.
    @inline(__always) func sourceY(_ y: Int) -> Int {
      isIdentity ? y : min(sourceHeight - 1, (baseY + y * stepY) >> 16)
    }
  }

  /// `QImage.scaled(width, height)` over a word array.
  static func nearestScaled(
    _ source: [UInt32], width sourceWidth: Int, height sourceHeight: Int,
    to width: Int, _ height: Int
  ) -> [UInt32] {
    source.withUnsafeBufferPointer { src in
      nearestScaled(src, width: sourceWidth, height: sourceHeight, to: width, height)
    }
  }

  /// `QImage.scaled(width, height)` over borrowed words.
  static func nearestScaled(
    _ src: UnsafeBufferPointer<UInt32>, width sourceWidth: Int, height sourceHeight: Int,
    to width: Int, _ height: Int
  ) -> [UInt32] {
    let scale = NearestScale(from: sourceWidth, sourceHeight, to: width, height)
    if scale.isIdentity { return Array(src) }
    var out = [UInt32](repeating: 0, count: width * height)
    let columns = (0..<width).map(scale.sourceX)
    out.withUnsafeMutableBufferPointer { dst in
      for y in 0..<height {
        let srcRow = scale.sourceY(y) * sourceWidth
        let dstRow = y * width
        for x in 0..<width {
          dst[dstRow + x] = src[srcRow + columns[x]]
        }
      }
    }
    return out
  }

  /// Writes `small.scaled(buffer.width, buffer.height)` into `buffer`, band by
  /// band — the second half of Pixelate and Retro Console.
  private static func enlarge(
    _ small: [UInt32], width smallWidth: Int, height smallHeight: Int, into buffer: inout PixelBuffer
  ) {
    let width = buffer.width, height = buffer.height
    let scale = NearestScale(from: smallWidth, smallHeight, to: width, height)
    let columns = (0..<width).map(scale.sourceX)
    small.withUnsafeBufferPointer { src in
      buffer.withMutableWords { dst in
        PixelBuffer.forEachBand(height: height) { rows in
          for y in rows {
            let srcRow = scale.sourceY(y) * smallWidth
            let dstRow = y * width
            for x in 0..<width {
              dst[dstRow + x] = src[srcRow + columns[x]]
            }
          }
        }
      }
    }
  }

  // MARK: - Sepia

  /// `SepiaFilter`: the classic tone, alpha-aware — the red channel is capped
  /// at the pixel's premultiplied ceiling so translucent pixels stay valid.
  static func sepia(_ buffer: inout PixelBuffer, amount: Int) {
    let k = Float(Double(amount) / 100.0)
    let width = buffer.width, height = buffer.height
    buffer.withMutableWords { words in
      PixelBuffer.forEachBand(height: height) { rows in
        for index in (rows.lowerBound * width)..<(rows.upperBound * width) {
          let word = words[index]
          let a = Float(alpha(word))
          var r = Float(red(word)), g = Float(green(word)), b = Float(blue(word))
          let tone = luma(r: r, g: g, b: b)
          let scale: Float = a > 0 ? a / Float(255) : 0
          let sr = min(tone * Float(1.07), Float(255) * scale)
          let sg = tone * Float(0.89)
          let sb = tone * Float(0.62)
          r = r + (sr - r) * k
          g = g + (sg - g) * k
          b = b + (sb - b) * k
          words[index] = pack(a: alpha(word), r: clipWord(r), g: clipWord(g), b: clipWord(b))
        }
      }
    }
  }

  // MARK: - Pixelate

  /// `PixelateFilter`: shrink by `size` and enlarge back, both nearest.
  static func pixelate(_ buffer: inout PixelBuffer, size: Int) {
    let size = max(2, size)
    let width = buffer.width, height = buffer.height
    let smallWidth = max(1, width / size), smallHeight = max(1, height / size)
    let small = buffer.withWords { words in
      nearestScaled(words, width: width, height: height, to: smallWidth, smallHeight)
    }
    enlarge(small, width: smallWidth, height: smallHeight, into: &buffer)
  }

  // MARK: - Denoise (chroma)

  /// `DenoiseFilter`: luma is kept exactly; the chroma differences get three
  /// vertical then three horizontal box passes of radius `strength / 10`,
  /// each an edge-padded `float32` running sum. Two full-size `Float` planes
  /// (Cb and Cr) are the working memory.
  static func denoise(_ buffer: inout PixelBuffer, strength: Int) {
    let radius = max(1, strength / 10)
    let width = buffer.width, height = buffer.height
    let count = width * height
    var cb = [Float](repeating: 0, count: count)
    var cr = [Float](repeating: 0, count: count)
    buffer.withWords { words in
      PixelBuffer.forEachBand(height: height) { rows in
        for index in (rows.lowerBound * width)..<(rows.upperBound * width) {
          let word = words[index]
          let r = Float(red(word)), g = Float(green(word)), b = Float(blue(word))
          let y = luma(r: r, g: g, b: b)
          cb[index] = b - y
          cr[index] = r - y
        }
      }
    }
    boxBlur(&cb, width: width, height: height, radius: radius)
    boxBlur(&cr, width: width, height: height, radius: radius)
    buffer.withMutableWords { words in
      PixelBuffer.forEachBand(height: height) { rows in
        for index in (rows.lowerBound * width)..<(rows.upperBound * width) {
          let word = words[index]
          let r0 = Float(red(word)), g0 = Float(green(word)), b0 = Float(blue(word))
          let y = luma(r: r0, g: g0, b: b0)
          let r = min(max(y + cr[index], 0), 255)
          let b = min(max(y + cb[index], 0), 255)
          let g = min(max((y - Float(0.299) * r - Float(0.114) * b) / Float(0.587), 0), 255)
          words[index] = pack(a: alpha(word), r: UInt32(r), g: UInt32(g), b: UInt32(b))
        }
      }
    }
  }

  /// The desktop `box()`: three passes down the columns, then three along the
  /// rows, each `cumsum` of the edge-padded line divided by the window.
  private static func boxBlur(_ plane: inout [Float], width: Int, height: Int, radius: Int) {
    let window = 2 * radius + 1
    let divisor = Float(window)
    plane.withUnsafeMutableBufferPointer { data in
      var padded = [Float](repeating: 0, count: max(width, height) + 2 * radius)
      var out = [Float](repeating: 0, count: max(width, height))
      func pass(length: Int, load: (Int) -> Float, store: (Int, Float) -> Void) {
        for j in 0..<(length + 2 * radius) {
          padded[j] = load(min(max(j - radius, 0), length - 1))
        }
        var running: Float = 0
        for j in 0..<(length + 2 * radius) {
          running += padded[j]
          padded[j] = running
        }
        out[0] = padded[window - 1]
        if length > 1 {
          for i in 1..<length {
            out[i] = padded[i + window - 1] - padded[i - 1]
          }
        }
        for i in 0..<length {
          store(i, out[i] / divisor)
        }
      }
      for _ in 0..<3 {
        for x in 0..<width {
          pass(
            length: height, load: { data[$0 * width + x] }, store: { data[$0 * width + x] = $1 })
        }
      }
      for _ in 0..<3 {
        for y in 0..<height {
          let row = y * width
          pass(length: width, load: { data[row + $0] }, store: { data[row + $0] = $1 })
        }
      }
    }
  }

  // MARK: - Retro Console

  /// `RetroConsoleFilter._BAYER`: the 4x4 threshold matrix centred on zero.
  private static let bayer: [Float] = [
    0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5,
  ].map { (Float($0) + Float(0.5)) / Float(16) - Float(0.5) }

  /// `RetroConsoleFilter`: shrink, recover straight colour, dither and crush
  /// to `levels` per channel, re-premultiply, enlarge.
  static func retroConsole(_ buffer: inout PixelBuffer, size: Int, levels: Int, dither: Bool) {
    let size = max(1, size)
    let levels = max(2, levels)
    let width = buffer.width, height = buffer.height
    let smallWidth = max(1, width / size), smallHeight = max(1, height / size)
    var small = buffer.withWords { words in
      nearestScaled(words, width: width, height: height, to: smallWidth, smallHeight)
    }
    let step = Float(255.0 / Double(levels - 1))
    func crush(_ c: Float) -> Float {
      min(max((min(max(c, 0), 255) / step).rounded(.toNearestOrEven) * step, 0), 255)
    }
    for y in 0..<smallHeight {
      for x in 0..<smallWidth {
        let index = y * smallWidth + x
        let word = small[index]
        let a = Float(alpha(word))
        var r = Float(red(word)), g = Float(green(word)), b = Float(blue(word))
        let unpm: Float = a > 0 ? Float(255) / a : 0
        r *= unpm
        g *= unpm
        b *= unpm
        if dither {
          let bias = bayer[(y % 4) * 4 + (x % 4)] * step
          r = r + bias
          g = g + bias
          b = b + bias
        }
        r = crush(r)
        g = crush(g)
        b = crush(b)
        let af = a / Float(255)
        small[index] = pack(
          a: alpha(word), r: UInt32(r * af), g: UInt32(g * af), b: UInt32(b * af))
      }
    }
    enlarge(small, width: smallWidth, height: smallHeight, into: &buffer)
  }

  // MARK: - Pixel Sort

  /// `PixelSortFilter`: contiguous in-band runs along each row (or column)
  /// are sorted by straight luma, stably, whole pixels moving together.
  static func pixelSort(
    _ buffer: inout PixelBuffer, low: Int, high: Int, vertical: Bool, reverse: Bool
  ) {
    var low = low, high = high
    if low > high { swap(&low, &high) }
    let width = buffer.width, height = buffer.height
    let lineLength = vertical ? height : width
    let lineCount = vertical ? width : height
    var line = [UInt32](repeating: 0, count: lineLength)
    var lumas = [Float](repeating: 0, count: lineLength)
    buffer.withMutableWords { words in
      PixelBuffer.forEachBand(height: lineCount) { lines in
        for n in lines {
          for i in 0..<lineLength {
            line[i] = vertical ? words[i * width + n] : words[n * width + i]
          }
          for i in 0..<lineLength {
            let word = line[i]
            let a = Float(alpha(word))
            let unpm: Float = a > 0 ? Float(255) / max(a, 1) : 0
            lumas[i] = luma(r: Float(red(word)), g: Float(green(word)), b: Float(blue(word))) * unpm
          }
          guard sortRuns(&line, lumas: lumas, low: Float(low), high: Float(high), reverse: reverse)
          else { continue }
          for i in 0..<lineLength {
            if vertical {
              words[i * width + n] = line[i]
            } else {
              words[n * width + i] = line[i]
            }
          }
        }
      }
    }
  }

  /// `_sort_runs` for one line. Returns false when no pixel is in band.
  private static func sortRuns(
    _ line: inout [UInt32], lumas: [Float], low: Float, high: Float, reverse: Bool
  ) -> Bool {
    var touched = false
    var start = 0
    let count = line.count
    while start < count {
      guard lumas[start] >= low, lumas[start] <= high else {
        start += 1
        continue
      }
      var end = start
      while end < count, lumas[end] >= low, lumas[end] <= high { end += 1 }
      if end - start > 1 {
        // lexsort is a stable sort; the original index breaks ties.
        let order = (start..<end).sorted { p, q in
          let kp = reverse ? -lumas[p] : lumas[p]
          let kq = reverse ? -lumas[q] : lumas[q]
          return kp == kq ? p < q : kp < kq
        }
        let sorted = order.map { line[$0] }
        for (offset, word) in sorted.enumerated() { line[start + offset] = word }
      }
      touched = true
      start = end
    }
    return touched
  }

  // MARK: - Datamosh + chromatic aberration

  /// `DatamoshFilter`: displace macroblocks by seeded motion vectors that
  /// accumulate down the rows, then fringe R out and B in about the centre.
  static func datamosh(
    _ buffer: inout PixelBuffer, block: Int, amount: Int, drift: Int, aberration: Double,
    seed: Int
  ) {
    let block = max(4, block)
    let fraction = Double(amount) / 100.0
    if fraction > 0, drift > 0 {
      moshBlocks(&buffer, block: block, amount: fraction, drift: drift, seed: seed)
    }
    if aberration > 0 {
      chromaticAberration(&buffer, pixels: aberration)
    }
  }

  /// `_mosh_blocks`: three streams per block row keyed by `(seed, row)`, so
  /// every block keeps the vector its position earns whatever the canvas size.
  private static func moshBlocks(
    _ buffer: inout PixelBuffer, block: Int, amount: Double, drift: Int, seed: Int
  ) {
    let width = buffer.width, height = buffer.height
    let blockRows = (height + block - 1) / block
    let blockColumns = (width + block - 1) / block
    var vx = [Int](repeating: 0, count: blockColumns)
    var vy = [Int](repeating: 0, count: blockColumns)
    let ydrift = max(1, drift / 2)
    // the single "previous frame" every block samples from
    let source = buffer.words
    var fresh = [Bool](repeating: false, count: blockColumns)
    source.withUnsafeBufferPointer { src in
      buffer.withMutableWords { dst in
        for i in 0..<blockRows {
          var sequence = NumpyRandom.SeedSequence(entropy: [UInt64(seed), UInt64(i)])
          let children = sequence.spawn(3)
          var rf = NumpyRandom.PCG64(seed: children[0])
          var rx = NumpyRandom.PCG64(seed: children[1])
          var ry = NumpyRandom.PCG64(seed: children[2])
          for j in 0..<blockColumns { fresh[j] = rf.nextDouble() < amount }
          // np.where draws the whole row before choosing, so every column
          // consumes its draw whether or not it is fresh
          for j in 0..<blockColumns {
            let dx = rx.integer(low: -drift, high: drift + 1)
            if fresh[j] { vx[j] += dx }
          }
          for j in 0..<blockColumns {
            let dy = ry.integer(low: -ydrift, high: ydrift + 1)
            if fresh[j] { vy[j] += dy }
          }
          let y0 = i * block
          let y1 = min(y0 + block, height)
          let blockHeight = y1 - y0
          for j in 0..<blockColumns {
            let x0 = j * block
            let x1 = min(x0 + block, width)
            let blockWidth = x1 - x0
            let sy = min(max(y0 + vy[j], 0), height - blockHeight)
            let sx = min(max(x0 + vx[j], 0), width - blockWidth)
            for row in 0..<blockHeight {
              let from = (sy + row) * width + sx
              let to = (y0 + row) * width + x0
              for column in 0..<blockWidth {
                dst[to + column] = src[from + column]
              }
            }
          }
        }
      }
    }
  }

  /// `_chromatic_aberration`: R sampled from a plane scaled out by `1 + k`, B
  /// from one scaled in by `1 - k`, G and alpha untouched, all in straight
  /// colour and re-premultiplied by each pixel's own alpha.
  private static func chromaticAberration(_ buffer: inout PixelBuffer, pixels: Double) {
    let width = buffer.width, height = buffer.height
    let cx = Double(width - 1) / 2.0
    let cy = Double(height - 1) / 2.0
    var rmax = (cx * cx + cy * cy).squareRoot()
    if rmax == 0 { rmax = 1.0 }
    let k = min(pixels / rmax, 0.9)
    // `_radial_sample` works in float32 with the centre and scale cast down
    func sampleMap(length: Int, centre: Double, scale: Double) -> [Int] {
      let c = Float(centre), s = Float(scale), limit = Float(length - 1)
      return (0..<length).map { Int(min(max(c + (Float($0) - c) / s, 0), limit)) }
    }
    let redX = sampleMap(length: width, centre: cx, scale: 1.0 + k)
    let redY = sampleMap(length: height, centre: cy, scale: 1.0 + k)
    let blueX = sampleMap(length: width, centre: cx, scale: 1.0 - k)
    let blueY = sampleMap(length: height, centre: cy, scale: 1.0 - k)
    let source = buffer.words
    @inline(__always) func unpremultiplier(_ word: UInt32) -> Float {
      let a = Float(alpha(word))
      return a > 0 ? Float(255) / max(a, Float(1)) : 0
    }
    source.withUnsafeBufferPointer { src in
      buffer.withMutableWords { dst in
        PixelBuffer.forEachBand(height: height) { rows in
          for y in rows {
            let row = y * width
            let redRow = redY[y] * width
            let blueRow = blueY[y] * width
            for x in 0..<width {
              let word = src[row + x]
              let a = alpha(word)
              let g = Float(green(word)) * unpremultiplier(word)
              let redWord = src[redRow + redX[x]]
              let r = Float(red(redWord)) * unpremultiplier(redWord)
              let blueWord = src[blueRow + blueX[x]]
              let b = Float(blue(blueWord)) * unpremultiplier(blueWord)
              let af = Float(a) / Float(255)
              dst[row + x] = pack(
                a: a, r: clipWord(r * af), g: clipWord(g * af), b: clipWord(b * af))
            }
          }
        }
      }
    }
  }

  // MARK: - Film Negative

  enum FilmNegativeMode: String, CaseIterable {
    case auto, color, mono
  }

  /// `FilmNegativeFilter.MONO_CHROMA_MAX`: mean (max - min) of straight RGB
  /// at or below this reads as a greyscale scan.
  static let monoChromaMax = 24.0

  /// `FilmNegativeFilter`: a two-pass develop in reciprocal (transmittance)
  /// space — histograms of straight colour first, then per-channel lookup
  /// tables between each channel's clipped extremes. `float64` throughout,
  /// like the desktop.
  static func filmNegative(_ buffer: inout PixelBuffer, mode: FilmNegativeMode, clip: Double) {
    let width = buffer.width, height = buffer.height
    guard width > 0, height > 0 else { return }

    // Straight 0-255 channels for one pixel (`_unpremultiplied_rgb`).
    @inline(__always) func straight(_ word: UInt32) -> (Int, Int, Int) {
      let a = Int(alpha(word))
      var r = Int(red(word)), g = Int(green(word)), b = Int(blue(word))
      if a > 0, a < 255 {
        let scale = 255.0 / Double(max(a, 1))
        r = clampRint(Double(r) * scale)
        g = clampRint(Double(g) * scale)
        b = clampRint(Double(b) * scale)
      }
      return (r, g, b)
    }
    @inline(__always) func lumaOf(_ r: Int, _ g: Int, _ b: Int) -> Int {
      clampRint(0.299 * Double(r) + 0.587 * Double(g) + 0.114 * Double(b))
    }

    // Pass 1 — histograms (R, G, B, luma) and the chroma statistic.
    var hist = [[Int]](repeating: [Int](repeating: 0, count: 256), count: 4)
    var chromaSum = 0.0
    var opaqueCount = 0
    buffer.withWords { words in
      PixelBuffer.forEachBand(height: height) { rows in
        for index in (rows.lowerBound * width)..<(rows.upperBound * width) {
          let word = words[index]
          guard alpha(word) > 0 else { continue }
          let (r, g, b) = straight(word)
          hist[0][r] += 1
          hist[1][g] += 1
          hist[2][b] += 1
          hist[3][lumaOf(r, g, b)] += 1
          chromaSum += Double(max(r, g, b) - min(r, g, b))
          opaqueCount += 1
        }
      }
    }
    guard opaqueCount > 0 else { return }
    var mode = mode
    if mode == .auto {
      mode = chromaSum / Double(opaqueCount) <= monoChromaMax ? .mono : .color
    }
    let channels = mode == .mono ? [3, 3, 3] : [0, 1, 2]
    let tables = channels.map { channel -> [Int] in
      let (lo, hi) = clippedBounds(hist[channel], total: opaqueCount, clip: clip)
      return negativeLUT(lo: lo, hi: hi)
    }

    // Pass 2 — develop and re-premultiply (`_store_premultiplied`).
    buffer.withMutableWords { words in
      PixelBuffer.forEachBand(height: height) { rows in
        for index in (rows.lowerBound * width)..<(rows.upperBound * width) {
          let word = words[index]
          let a = alpha(word)
          let (r, g, b) = straight(word)
          let outR: Int, outG: Int, outB: Int
          if mode == .mono {
            let value = tables[0][lumaOf(r, g, b)]
            outR = value
            outG = value
            outB = value
          } else {
            outR = tables[0][r]
            outG = tables[1][g]
            outB = tables[2][b]
          }
          let scale = Double(a) / 255.0
          words[index] = pack(
            a: a, r: UInt32(clampRint(Double(outR) * scale)),
            g: UInt32(clampRint(Double(outG) * scale)),
            b: UInt32(clampRint(Double(outB) * scale)))
        }
      }
    }
  }

  /// `np.clip(np.rint(x), 0, 255)` as an `Int`.
  @inline(__always) private static func clampRint(_ value: Double) -> Int {
    Int(min(max(value.rounded(.toNearestOrEven), 0), 255))
  }

  /// `_clipped_bounds`: the lowest and highest values left after dropping
  /// `clip` percent of the pixels from each end of the histogram.
  static func clippedBounds(_ counts: [Int], total: Int, clip: Double) -> (Int, Int) {
    guard total > 0 else { return (0, 255) }
    let drop = Int(Double(total) * clip / 100.0)
    var cumulative = [Int](repeating: 0, count: 256)
    var running = 0
    for i in 0..<256 {
      running += counts[i]
      cumulative[i] = running
    }
    // searchsorted(side="right"): first index whose cumulative count exceeds drop
    var lo = cumulative.firstIndex { $0 > drop } ?? 256
    // searchsorted(side="left"): first index reaching total - drop
    var hi = cumulative.firstIndex { $0 >= total - drop } ?? 256
    lo = min(max(lo, 0), 255)
    hi = min(max(hi, 0), 255)
    if hi <= lo { return (0, 255) }
    return (lo, hi)
  }

  /// `_negative_lut`: scan value -> developed positive, normalised in
  /// reciprocal space between the clipped extremes.
  static func negativeLUT(lo: Int, hi: Int) -> [Int] {
    let top = 1.0 / Double(max(lo, 1))
    let bottom = 1.0 / Double(max(hi, 1))
    let span = top - bottom
    if span <= 0 { return [Int](repeating: 0, count: 256) }
    return (0..<256).map { value in
      let recip = 1.0 / Double(max(value, 1))
      let scaled = (recip - bottom) / span
      return clampRint(scaled * 255.0)
    }
  }
}

// SPDX-License-Identifier: Apache-2.0
import Foundation

/// The iOS port of `photoslop.dither` (#385), the engine behind Beam Dither.
///
/// Deliberately free of UIKit: it takes a luminance plane as `Double` in 0...1
/// and gives back a quantised plane or a beam-coverage plane, which is what
/// lets `DitherParityTests` compare it against the desktop as arithmetic
/// rather than as pixels.
///
/// Two families live here and they answer different questions. **Dithering**
/// asks which pixels to light so a coarse palette still averages out to the
/// original tone. **Beam modulation** does not try to preserve average tone at
/// all: it draws a raster of horizontal beams and lets the picture deflect
/// them, the way a CRT's vertical deflection coil is driven by a signal, so
/// bright pixels push their beam off its resting row and widen it.
///
/// Everything is `Double` because the desktop is float64 at these steps and a
/// `Float` here would disagree in the last place — which for a dither is not a
/// rounding difference but a different pixel turned on.
enum Dither {
  /// (dx, dy, weight) and the divisor, as the literature writes them.
  ///
  /// Atkinson deliberately diffuses only 6/8 of the error, which throws away
  /// contrast and is exactly why classic Macintosh dithers look crisp and a
  /// little blown out rather than flat.
  static let errorKernels: [String: (offsets: [(Int, Int, Int)], divisor: Int)] = [
    "floyd-steinberg": ([(1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)], 16),
    "atkinson": ([(1, 0, 1), (2, 0, 1), (-1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 2, 1)], 8),
    "jarvis": (
      [
        (1, 0, 7), (2, 0, 5),
        (-2, 1, 3), (-1, 1, 5), (0, 1, 7), (1, 1, 5), (2, 1, 3),
        (-2, 2, 1), (-1, 2, 3), (0, 2, 5), (1, 2, 3), (2, 2, 1),
      ], 48
    ),
    "stucki": (
      [
        (1, 0, 8), (2, 0, 4),
        (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2),
        (-2, 2, 1), (-1, 2, 2), (0, 2, 4), (1, 2, 2), (2, 2, 1),
      ], 42
    ),
    "sierra": (
      [
        (1, 0, 5), (2, 0, 3),
        (-2, 1, 2), (-1, 1, 4), (0, 1, 5), (1, 1, 4), (2, 1, 2),
        (-1, 2, 2), (0, 2, 3), (1, 2, 2),
      ], 32
    ),
    "burkes": (
      [(1, 0, 8), (2, 0, 4), (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2)], 32
    ),
  ]

  /// Python's `round()` and numpy's `rint`: to nearest, ties to **even**.
  /// A tie broken the other way flips a pixel, so this cannot be `rounded()`.
  static func rint(_ value: Double) -> Double { value.rounded(.toNearestOrEven) }

  /// The recursive Bayer threshold matrix, normalised into 0..1 exclusive.
  ///
  /// Built by the doubling recurrence rather than typed out, so 2, 4, 8 and 16
  /// all come from one rule:
  ///
  ///     M(2n) = [[4M(n),   4M(n)+2],
  ///              [4M(n)+3, 4M(n)+1]]
  static func bayerMatrix(_ size: Int) -> [Double] {
    precondition(size >= 2 && size & (size - 1) == 0, "bayer size must be a power of two >= 2")
    var side = 2
    var matrix: [Double] = [0, 2, 3, 1]
    while side < size {
      let next = side * 2
      var grown = [Double](repeating: 0, count: next * next)
      for y in 0..<side {
        for x in 0..<side {
          let value = 4 * matrix[y * side + x]
          grown[y * next + x] = value
          grown[y * next + x + side] = value + 2
          grown[(y + side) * next + x] = value + 3
          grown[(y + side) * next + x + side] = value + 1
        }
      }
      matrix = grown
      side = next
    }
    let count = Double(size * size)
    return matrix.map { ($0 + 0.5) / count }
  }

  /// Snap 0...1 values onto `levels` evenly spaced tones.
  static func quantise(_ plane: [Double], levels: Int) -> [Double] {
    let steps = Double(max(2, levels) - 1)
    return plane.map { min(1.0, max(0.0, rint($0 * steps) / steps)) }
  }

  /// Serpentine error diffusion.
  ///
  /// Serpentine — alternate rows run right to left — because a fixed scan
  /// direction lets the residual error drift the same way on every row and
  /// print as diagonal worming; reversing every other row cancels it.
  ///
  /// The loop is scalar and sequential by nature: a pixel cannot be quantised
  /// until its left neighbour has pushed error into it, so unlike every other
  /// filter here this one does not vectorise over `PixelBuffer`. The cell size
  /// is what keeps the pixel count sane.
  static func errorDiffuse(
    _ plane: [Double], width: Int, height: Int, kernel: String, levels: Int
  ) -> [Double] {
    guard let table = errorKernels[kernel], width > 0, height > 0 else { return plane }
    let steps = Double(max(2, levels) - 1)
    var work = plane
    var out = [Double](repeating: 0, count: plane.count)
    for y in 0..<height {
      let rightwards = y % 2 == 0
      let sign = rightwards ? 1 : -1
      for step in 0..<width {
        let x = rightwards ? step : width - 1 - step
        let index = y * width + x
        let old = work[index]
        var new = rint(old * steps) / steps
        new = new < 0 ? 0 : (new > 1 ? 1 : new)
        out[index] = new
        let error = old - new
        if error == 0 { continue }
        for (dx, dy, weight) in table.offsets {
          let ny = y + dy
          if ny >= height { continue }
          let nx = x + dx * sign
          if nx < 0 || nx >= width { continue }
          work[ny * width + nx] += error * Double(weight) / Double(table.divisor)
        }
      }
    }
    return out
  }

  /// Bayer ordered dithering: no neighbour memory at all, so the same tone at
  /// the same grid position always resolves the same way. That is what makes
  /// it stable and tileable where error diffusion is neither.
  static func orderedDither(
    _ plane: [Double], width: Int, height: Int, size: Int, levels: Int
  ) -> [Double] {
    let matrix = bayerMatrix(size)
    let steps = Double(max(2, levels) - 1)
    var out = [Double](repeating: 0, count: plane.count)
    for y in 0..<height {
      for x in 0..<width {
        let threshold = matrix[(y % size) * size + (x % size)]
        // Applied inside one quantisation step, so the pattern dithers
        // *between* adjacent tones rather than only between black and white.
        let nudged = plane[y * width + x] * steps + (threshold - 0.5)
        out[y * width + x] = min(1.0, max(0.0, rint(nudged) / steps))
      }
    }
    return out
  }

  /// Beam modulation: a raster of horizontal beams deflected by the picture.
  ///
  /// Two things happen at once, both driven by luminance. The beam's **phase**
  /// is advanced by `amplitude * lum`, so neighbouring columns of differing
  /// brightness light different rows and the line *bends* around whatever is
  /// in the picture — that bending, not the dot pattern, is what makes the
  /// result read as engraving. And luminance sets a **threshold** on the beam
  /// profile, so beams thicken into solid white in highlights and thin to
  /// broken dashes in shadow.
  ///
  /// The threshold runs from 1 down to `-edge` rather than to 0. Stopping at
  /// zero leaves the gap between beams permanently unlit — the profile dips to
  /// 0 there and never clears a zero threshold by the full shoulder width — so
  /// pure white would render at 83% coverage with the raster still showing
  /// through, and the top of the tonal range would simply be missing.
  static func beamMask(
    _ plane: [Double], width: Int, height: Int, pitch: Int, amplitude: Double
  ) -> [Double] {
    let pitch = Double(max(2, pitch))
    let edge = 0.12
    var out = [Double](repeating: 0, count: plane.count)
    for y in 0..<height {
      for x in 0..<width {
        let index = y * width + x
        let lum = plane[index]
        let phase = Double(y) / pitch + amplitude * lum
        // cos gives a smooth beam profile centred on the line. A square wave
        // would alias into stair steps the moment the beam bends.
        let profile = 0.5 + 0.5 * cos(2.0 * Double.pi * phase)
        let level = (1.0 - lum) * (1.0 + edge) - edge
        out[index] = min(1.0, max(0.0, (profile - level) / edge))
      }
    }
    return out
  }
}

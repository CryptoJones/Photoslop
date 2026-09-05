// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Beam Dither as the iOS filter (#385).
///
/// `DitherParityTests` proves the engine matches the desktop word for word.
/// This covers the pipeline around it — luminance, the cell-size downsample,
/// and the inking — as behaviour rather than as fixture identity, because the
/// desktop's conditioning stage works in float32 while this works in Double.
/// That difference is sub-pixel everywhere except where a conditioned value
/// lands exactly on a quantisation boundary, and claiming bit-identity for the
/// whole filter would be claiming more than has been shown.
@MainActor
final class BeamDitherFilterTests: XCTestCase {
  private func ramp(width: Int = 64, height: Int = 64, alpha: Int = 255) -> PixelBuffer {
    var words = [UInt32](repeating: 0, count: width * height)
    for y in 0..<height {
      for x in 0..<width {
        let value = Int((Double(x) / Double(width - 1) * 255).rounded())
        let premultiplied = Int((Double(value) * Double(alpha) / 255).rounded())
        words[y * width + x] =
          (UInt32(alpha) << 24) | (UInt32(premultiplied) << 16) | (UInt32(premultiplied) << 8)
          | UInt32(premultiplied)
      }
    }
    return PixelBuffer(width: width, height: height, words: words)
  }

  private func params(_ pairs: [String: FilterParamValue]) -> FilterParams {
    var out = FilterKind.beamDither.defaults
    for (key, value) in pairs { out[key] = value }
    return out
  }

  func testItIsOfferedAsAFilter() {
    XCTAssertTrue(FilterKind.allCases.contains(.beamDither))
    XCTAssertEqual(FilterKind.beamDither.rawValue, "beam-dither", "the desktop registry name")
    XCTAssertEqual(FilterKind.beamDither.label, "Beam Dither")
  }

  func testMonoOutputIsTwoTone() {
    var buffer = ramp()
    FilterKind.beamDither.apply(
      to: &buffer, params: params(["algorithm": .choice("floyd-steinberg"), "scale": .int(1)]))
    let reds = Set(buffer.words.map { ($0 >> 16) & 0xFF })
    XCTAssertEqual(reds, [0, 255], "mono should render black and white only")
  }

  func testTonalUsesExactlyTheRequestedInks() {
    var buffer = ramp()
    FilterKind.beamDither.apply(
      to: &buffer,
      params: params([
        "algorithm": .choice("floyd-steinberg"), "scale": .int(1), "mode": .choice("tonal"),
        "background": .string("#000000"), "shadows": .string("#0B3C5D"),
        "midtones": .string("#6CCFF6"), "highlights": .string("#FFFFFF"),
      ]))
    let used = Set(buffer.words.map { $0 & 0x00FF_FFFF })
    XCTAssertTrue(used.isSubset(of: [0x0000_0000, 0x000B_3C5D, 0x006C_CFF6, 0x00FF_FFFF]))
    XCTAssertTrue(used.contains(0x00FF_FFFF), "the highlights ink never appeared")
  }

  /// The cell size is what makes a dither read as chunky: at scale 4 the
  /// output must be constant within each 4x4 block.
  func testCellSizeQuantisesToBlocks() {
    var buffer = ramp()
    FilterKind.beamDither.apply(
      to: &buffer, params: params(["algorithm": .choice("bayer-4"), "scale": .int(4)]))
    for y in 4..<8 {
      for x in 4..<8 {
        XCTAssertEqual(
          buffer.words[y * 64 + x], buffer.words[4 * 64 + 4], "cell (1,1) is not uniform")
      }
    }
  }

  /// Premultiplied buffers make this silent to get wrong: a dither must not
  /// turn a half-transparent layer opaque.
  func testAlphaIsPreserved() {
    var buffer = ramp(alpha: 128)
    FilterKind.beamDither.apply(to: &buffer, params: params(["scale": .int(2)]))
    XCTAssertEqual(Set(buffer.words.map { ($0 >> 24) & 0xFF }), [128])
    // And no channel may exceed its own alpha, or the buffer is not
    // premultiplied any more and every later composite is wrong.
    for word in buffer.words {
      let a = (word >> 24) & 0xFF
      XCTAssertLessThanOrEqual((word >> 16) & 0xFF, a)
      XCTAssertLessThanOrEqual((word >> 8) & 0xFF, a)
      XCTAssertLessThanOrEqual(word & 0xFF, a)
    }
  }

  func testBeamBendsOnlyWithAmplitude() {
    var straight = ramp()
    var bent = ramp()
    FilterKind.beamDither.apply(
      to: &straight,
      params: params(["scale": .int(1), "beam_amplitude": .float(0), "beam_pitch": .int(6)]))
    FilterKind.beamDither.apply(
      to: &bent,
      params: params(["scale": .int(1), "beam_amplitude": .float(4), "beam_pitch": .int(6)]))
    XCTAssertNotEqual(straight.words, bent.words, "displacement did nothing")
  }

  func testAMalformedInkFallsBackRatherThanFailing() {
    let fallback = FilterAlgorithms.hexRGB("nonsense", fallback: (1, 2, 3))
    XCTAssertEqual(fallback.0, 1)
    XCTAssertEqual(fallback.1, 2)
    XCTAssertEqual(fallback.2, 3)
    XCTAssertEqual(FilterAlgorithms.hexRGB("#0f0", fallback: (0, 0, 0)).1, 255)
    XCTAssertEqual(FilterAlgorithms.hexRGB("6CCFF6", fallback: (0, 0, 0)).0, 108)
  }

  /// The memory budget must charge for this filter, or a large document could
  /// run it straight into a jetsam kill.
  func testItDeclaresItsWorkingBuffers() {
    XCTAssertGreaterThan(FilterKind.beamDither.transientLayers, 0)
  }
}

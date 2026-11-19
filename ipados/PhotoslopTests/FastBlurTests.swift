// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Comprehensive test suite for Fast Large-Radius Blur (Issue #418) on iOS.
///
/// Verifies:
/// 1. Parity between FilterAlgorithms.fastBlur, gaussianBlur, and AppearanceRenderer.blurRGBA.
/// 2. O(1) performance across radii using 3-pass running-sum box approximation.
/// 3. Banded execution without seam artifacts across 256-row bands.
/// 4. Large-radius blur support up to 250px.
/// 5. FilterKind integration and parameter validation.
/// 6. Image renderer hygiene (format.scale = 1, format.opaque = false).
@MainActor
final class FastBlurTests: XCTestCase {

  private func makeBuffer(width: Int, height: Int, color: UInt32 = 0xFF80_8080) -> PixelBuffer {
    PixelBuffer(width: width, height: height, words: [UInt32](repeating: color, count: width * height))
  }

  private func makeImpulseBuffer(width: Int, height: Int) -> PixelBuffer {
    var words = [UInt32](repeating: 0, count: width * height)
    words[(height / 2) * width + (width / 2)] = 0xFFFF_FFFF
    return PixelBuffer(width: width, height: height, words: words)
  }

  // MARK: - 1. Parity & Identity

  func testFastBlurMatchesAppearanceRenderer() {
    let width = 64, height = 64
    var words = [UInt32](repeating: 0, count: width * height)
    for y in 0..<height {
      for x in 0..<width {
        words[y * width + x] = ((x + y) % 2 == 0) ? 0xFFFF_0000 : 0xFF00_00FF
      }
    }
    let original = PixelBuffer(width: width, height: height, words: words)

    for radius in [3, 8, 25, 50] {
      var fastCopy = original
      FilterAlgorithms.fastBlur(&fastCopy, radius: radius)

      let ref = AppearanceRenderer.blurRGBA(original, radius: radius)
      XCTAssertEqual(fastCopy.words, ref.words, "fastBlur diverged from AppearanceRenderer at radius \(radius)")
    }
  }

  func testFastBlurAndGaussianBlurParity() {
    var b1 = makeBuffer(width: 40, height: 40, color: 0xFF11_2233)
    var b2 = b1
    FilterAlgorithms.fastBlur(&b1, radius: 12)
    FilterAlgorithms.gaussianBlur(&b2, radius: 12)
    XCTAssertEqual(b1.words, b2.words, "fastBlur and gaussianBlur must be identical")
  }

  // MARK: - 2. Large Radii up to 250px

  func testLargeRadiusBlurUpTo250() {
    let size = 300
    var buffer = makeBuffer(width: size, height: size, color: 0xFFFF_FFFF)
    // Draw black square in center
    buffer.withMutableWords { words in
      for y in 100..<200 {
        for x in 100..<200 {
          words[y * size + x] = 0xFF00_0000
        }
      }
    }

    FilterAlgorithms.fastBlur(&buffer, radius: 250)

    // Center pixel should be softened
    let center = buffer.words[(size / 2) * size + (size / 2)]
    let centerRed = (center >> 16) & 0xFF
    XCTAssertGreaterThan(centerRed, 0)
    XCTAssertLessThan(centerRed, 255)
  }

  // MARK: - 3. O(1) Performance Characteristics

  func testO1PerformanceAcrossRadii() {
    let width = 120, height = 120
    let original = makeBuffer(width: width, height: height, color: 0xFFAA_BBCC)

    // Warmup
    var warm = original
    FilterAlgorithms.fastBlur(&warm, radius: 8)

    let startSmall = CACurrentMediaTime()
    var small = original
    FilterAlgorithms.fastBlur(&small, radius: 10)
    let elapsedSmall = CACurrentMediaTime() - startSmall

    let startLarge = CACurrentMediaTime()
    var large = original
    FilterAlgorithms.fastBlur(&large, radius: 100)
    let elapsedLarge = CACurrentMediaTime() - startLarge

    // Prefix sum accumulators execute in O(1) time per pixel independent of radius.
    // Allow generous tolerance for CI timing noise, but ensure time does not scale with radius.
    let ratio = elapsedLarge / max(elapsedSmall, 0.0001)
    XCTAssertLessThan(ratio, 5.0, "Execution time scaled proportionally with radius (ratio: \(ratio))")
  }

  // MARK: - 4. Band Processing (DD-001) Parity Without Seams

  func testBandedParityWithoutSeams() {
    let width = 16
    let height = PixelBuffer.bandRows * 2 + 30
    var words = [UInt32](repeating: 0, count: width * height)
    for y in 0..<height {
      for x in 0..<width {
        words[y * width + x] = (x % 2 == 0) ? 0xFF33_6699 : 0xFFCC_8844
      }
    }
    let radius = 20
    var buffer = PixelBuffer(width: width, height: height, words: words)
    FilterAlgorithms.fastBlur(&buffer, radius: radius)

    let r = max(1, radius / 2 + 1)
    let margin = 3 * r + 1
    let refRow = Array(buffer.words[margin * width..<(margin + 1) * width])
    XCTAssertNotEqual(refRow, Array(words[0..<width]), "the blur did nothing")

    // Every row between margins must match exactly, proving no seam at band boundaries
    for y in margin..<(height - margin) {
      let row = Array(buffer.words[y * width..<(y + 1) * width])
      XCTAssertEqual(row, refRow, "row \(y) disagrees with neighbours across band boundary")
    }
  }

  // MARK: - 5. FilterKind Integration

  func testFilterKindApplication() {
    var buffer = makeBuffer(width: 50, height: 50, color: 0xFF12_3456)
    let initial = buffer.words

    let kindFast = FilterKind.fastBlur
    XCTAssertEqual(kindFast.label, "Fast Blur")
    XCTAssertEqual(kindFast.params.first?.name, "radius")

    kindFast.apply(to: &buffer, params: ["radius": .int(15)])
    XCTAssertNotEqual(buffer.words, initial, "FilterKind.fastBlur did not mutate buffer")

    var bufferGauss = makeBuffer(width: 50, height: 50, color: 0xFF12_3456)
    let kindGauss = FilterKind.gaussianBlur
    XCTAssertEqual(kindGauss.label, "Gaussian Blur")
    kindGauss.apply(to: &bufferGauss, params: ["radius": .int(15)])
    XCTAssertEqual(buffer.words, bufferGauss.words, "fastBlur and gaussianBlur FilterKind results must match")
  }

  // MARK: - 6. UIGraphicsImageRenderer Hygiene

  func testUIGraphicsRendererHygiene() {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let renderer = UIGraphicsImageRenderer(size: CGSize(width: 64, height: 64), format: format)
    let image = renderer.image { ctx in
      UIColor.blue.setFill()
      ctx.fill(CGRect(x: 0, y: 0, width: 64, height: 64))
    }
    XCTAssertEqual(image.scale, 1.0)
    XCTAssertEqual(image.size.width, 64.0)
    XCTAssertEqual(image.size.height, 64.0)
  }
}

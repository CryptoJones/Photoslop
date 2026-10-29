// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

final class PSDCodecTests: XCTestCase {
  /// `photoslop/io_psd.py` wrote this: an 8×6 canvas, opaque (10, 20, 30)
  /// background, plus a hidden 3×2 "Dot" layer at (2, 1) of (200, 100, 50)
  /// at alpha 128, opacity 0.5 and fill opacity 0.25. Decoding it here is the
  /// three-platform parity check: a desktop save opens on the iPad as the same
  /// layers.
  private static let desktopFixture = Data(
    base64Encoded:
      "OEJQUwABAAAAAAAAAAQAAAAGAAAACAAIAAMAAAAAAAAAHDhCSU0D7QAAAAAAEABIAAAAAQABAEgAAAABAAEAAAF4AAABcP/+AAAAAAAAAAAAAAAGAAAACAAE//8AAAAaAAAAAAAaAAEAAAAaAAIAAAAaOEJJTW5vcm3/AAgAAAAAOAAAAAAAAAAACkJhY2tncm91bmQAOEJJTWx1bmkAAAAYAAAACgBCAGEAYwBrAGcAcgBvAHUAbgBkAAAAAQAAAAIAAAADAAAABQAE//8AAAAKAAAAAAAKAAEAAAAKAAIAAAAKOEJJTW5vcm2AAAoAAAAAMgAAAAAAAAAAA0RvdDhCSU1sdW5pAAAACgAAAAMARABvAHQ4QklNaU9wYQAAAARAAAAAAAEAAgACAAIAAgACAAL5//n/+f/5//n/+f8AAQACAAIAAgACAAIAAvkK+Qr5CvkK+Qr5CgABAAIAAgACAAIAAgAC+RT5FPkU+RT5FPkUAAEAAgACAAIAAgACAAL5Hvke+R75Hvke+R4AAQACAAL+gP6AAAEAAgAC/sf+xwABAAIAAv5k/mQAAQACAAL+Mv4yAAAAAAABAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgAC+Qr5CvkK+Qr5CvkK+RT5FPkU+RT5FPkU+R75Hvke+R75Hvke+f/5//n/+f/5//n/"
  )!

  private func pixel(_ image: UIImage, _ x: Int, _ y: Int) -> (r: UInt32, g: UInt32, b: UInt32, a: UInt32) {
    let buffer = PixelBuffer(image: image)!
    let word = buffer.words[y * buffer.width + x]
    return (word >> 16 & 0xFF, word >> 8 & 0xFF, word & 0xFF, word >> 24)
  }

  func testOpensADesktopSaveAsTheSameLayers() throws {
    let state = try PSDCodec.decode(Self.desktopFixture)
    XCTAssertEqual(state.canvasSize, CGSize(width: 8, height: 6))
    XCTAssertEqual(state.layers.map(\.name), ["Background", "Dot"])
    let background = state.layers[0]
    XCTAssertEqual(background.origin, .zero)
    XCTAssertEqual(background.image.size, CGSize(width: 8, height: 6))
    let bg = pixel(background.image, 3, 3)
    XCTAssertEqual([bg.r, bg.g, bg.b, bg.a], [10, 20, 30, 255])
    let dot = state.layers[1]
    XCTAssertEqual(dot.origin, CGPoint(x: 2, y: 1))
    XCTAssertEqual(dot.image.size, CGSize(width: 3, height: 2))
    XCTAssertFalse(dot.isVisible)
    XCTAssertEqual(dot.opacity, 0.5, accuracy: 1.0 / 255)
    XCTAssertEqual(dot.fillOpacity, 0.25, accuracy: 1.0 / 255)
    let px = pixel(dot.image, 0, 0)
    XCTAssertEqual(px.a, 128)
    // Premultiplied: 200 × 128 / 255 ≈ 100, 100 × 128 / 255 ≈ 50, 50 × 128 / 255 ≈ 25.
    XCTAssertEqual(Int(px.r), 100, accuracy: 1)
    XCTAssertEqual(Int(px.g), 50, accuracy: 1)
    XCTAssertEqual(Int(px.b), 25, accuracy: 1)
    XCTAssertEqual(state.activeLayerID, dot.id)
  }

  func testLayeredRoundTripKeepsEveryLayer() throws {
    let canvas = CGSize(width: 12, height: 9)
    let base = RasterLayer(name: "Base", image: EditorStore.solidImage(size: canvas, color: .white))
    let swatch = EditorStore.solidImage(size: CGSize(width: 4, height: 3), color: .red)
    var top = RasterLayer(name: "Top ✓", image: swatch, isVisible: false, opacity: 0.5, fillOpacity: 0.25)
    top.origin = CGPoint(x: 5, y: 2)
    let data = try XCTUnwrap(PSDCodec.encode(layers: [base, top], canvasSize: canvas))
    XCTAssertTrue(PSDCodec.isPSD(data))

    let state = try PSDCodec.decode(data)
    XCTAssertEqual(state.canvasSize, canvas)
    XCTAssertEqual(state.layers.map(\.name), ["Base", "Top ✓"])
    let decodedTop = state.layers[1]
    XCTAssertEqual(decodedTop.origin, CGPoint(x: 5, y: 2))
    XCTAssertEqual(decodedTop.image.size, CGSize(width: 4, height: 3))
    XCTAssertFalse(decodedTop.isVisible)
    XCTAssertEqual(decodedTop.opacity, 0.5, accuracy: 1.0 / 255)
    XCTAssertEqual(decodedTop.fillOpacity, 0.25, accuracy: 1.0 / 255)
    let px = pixel(decodedTop.image, 1, 1)
    XCTAssertEqual([px.r, px.g, px.b, px.a], [255, 0, 0, 255])
    let base2 = pixel(state.layers[0].image, 0, 0)
    XCTAssertEqual([base2.r, base2.g, base2.b, base2.a], [255, 255, 255, 255])
  }

  func testPackBitsRoundTripsRunsAndLiterals() throws {
    let rows: [[UInt8]] = [
      [], [7], [1, 2, 3], [5, 5, 5, 5, 5], Array(repeating: 9, count: 300),
      (0..<300).map { UInt8($0 % 256) }, [1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 4],
    ]
    for row in rows {
      let packed = PSDCodec.packBits(row)
      XCTAssertEqual(try PSDCodec.unpackBits(packed, expected: row.count), row, "\(row.prefix(8))")
    }
  }

  func testRejectsNonPSDAndTruncatedInput() {
    XCTAssertThrowsError(try PSDCodec.decode(Data("definitely not a psd".utf8)))
    XCTAssertThrowsError(try PSDCodec.decode(Self.desktopFixture.prefix(200)))
  }
}

// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// The eyedropper (#379): `EditorStore.sampleColor` and the tool flags that
/// put it in the strip.
///
/// The load-bearing property is not any single colour — it is that the
/// sampler and the canvas agree. `sampleColor` composites one pixel through
/// the same `drawComposite` pass `render` uses for the whole canvas, so every
/// test that can be written as "the sample equals what `render` drew there"
/// is written that way: if the two ever diverge, the tool starts reporting a
/// colour the user cannot see.
@MainActor
final class EyedropperTests: XCTestCase {
  private let size = CGSize(width: 4, height: 4)

  private func solid(_ color: UIColor) -> UIImage {
    EditorStore.solidImage(size: size, color: color)
  }

  /// What `render` put at a point, as the sampler reports colours.
  private func rendered(_ layers: [RasterLayer], at point: CGPoint) -> UIColor {
    let image = EditorStore.render(layers: layers, size: size)
    let word = PixelBuffer.probe(image: image, x: Int(point.x), y: Int(point.y))
    let a = Int((word! >> 24) & 0xFF)
    guard a > 0 else { return UIColor(white: 0, alpha: 0) }
    func channel(_ shift: UInt32) -> CGFloat {
      CGFloat(min(255, Int((word! >> shift) & 0xFF) * 255 / a)) / 255
    }
    return UIColor(
      red: channel(16), green: channel(8), blue: channel(0), alpha: CGFloat(a) / 255)
  }

  private func assertSameColor(
    _ lhs: UIColor?, _ rhs: UIColor?, accuracy: CGFloat = 0.02,
    _ message: String = "", file: StaticString = #filePath, line: UInt = #line
  ) {
    guard let lhs, let rhs else { return XCTFail("nil colour. \(message)", file: file, line: line) }
    var lr: CGFloat = 0, lg: CGFloat = 0, lb: CGFloat = 0, la: CGFloat = 0
    var rr: CGFloat = 0, rg: CGFloat = 0, rb: CGFloat = 0, ra: CGFloat = 0
    lhs.getRed(&lr, green: &lg, blue: &lb, alpha: &la)
    rhs.getRed(&rr, green: &rg, blue: &rb, alpha: &ra)
    XCTAssertEqual(lr, rr, accuracy: accuracy, "red. \(message)", file: file, line: line)
    XCTAssertEqual(lg, rg, accuracy: accuracy, "green. \(message)", file: file, line: line)
    XCTAssertEqual(lb, rb, accuracy: accuracy, "blue. \(message)", file: file, line: line)
    XCTAssertEqual(la, ra, accuracy: accuracy, "alpha. \(message)", file: file, line: line)
  }

  /// The point of sampling the composite rather than the active layer: the
  /// colour on screen belongs to the top visible layer, not to whichever
  /// layer happens to be selected.
  func testSamplesTheCompositeNotTheActiveLayer() {
    let layers = [RasterLayer(name: "Red", image: solid(.red)),
                  RasterLayer(name: "Blue", image: solid(.blue))]
    let sampled = EditorStore.sampleColor(layers: layers, size: size, at: CGPoint(x: 1, y: 1))
    assertSameColor(sampled, .blue, "the top layer is what the eye sees")
    assertSameColor(sampled, rendered(layers, at: CGPoint(x: 1, y: 1)))
  }

  /// A half-opaque layer reads as the blend, to the same value the canvas
  /// drew — the sampler unpremultiplies rather than reporting a darkened one.
  func testSampleMatchesTheRenderedBlend() {
    var top = RasterLayer(name: "Blue", image: solid(.blue))
    top.opacity = 0.5
    let layers = [RasterLayer(name: "Red", image: solid(.red)), top]
    let point = CGPoint(x: 2, y: 2)
    assertSameColor(
      EditorStore.sampleColor(layers: layers, size: size, at: point),
      rendered(layers, at: point), "a blend must sample as it renders")
  }

  /// A hidden layer is not on screen, so it is not sampled either.
  func testHiddenLayerIsNotSampled() {
    var top = RasterLayer(name: "Blue", image: solid(.blue))
    top.isVisible = false
    let layers = [RasterLayer(name: "Red", image: solid(.red)), top]
    assertSameColor(
      EditorStore.sampleColor(layers: layers, size: size, at: CGPoint(x: 0, y: 0)),
      .red, "a hidden layer must not be sampled")
  }

  /// Every pixel of the canvas samples as the canvas drew it, including the
  /// far corners — the translate that moves a point onto the one-pixel
  /// context is off-by-one-prone in exactly those places.
  func testEveryPixelAgreesWithTheCanvas() {
    let layers = [RasterLayer(name: "Red", image: solid(.red)),
                  RasterLayer(name: "Green", image: solid(.green))]
    for y in 0..<Int(size.height) {
      for x in 0..<Int(size.width) {
        let point = CGPoint(x: x, y: y)
        assertSameColor(
          EditorStore.sampleColor(layers: layers, size: size, at: point),
          rendered(layers, at: point), "at (\(x), \(y))")
      }
    }
  }

  /// Off the canvas there is nothing to sample. The desktop returns None for
  /// the same case and its tool ignores it.
  func testOutsideTheCanvasIsNil() {
    let layers = [RasterLayer(name: "Red", image: solid(.red))]
    for point in [CGPoint(x: -1, y: 0), CGPoint(x: 0, y: -1),
                  CGPoint(x: 4, y: 0), CGPoint(x: 0, y: 4)] {
      XCTAssertNil(
        EditorStore.sampleColor(layers: layers, size: size, at: point),
        "\(point) is off a \(size) canvas")
    }
  }

  /// An empty stack is transparent, and reports alpha 0 rather than a colour.
  /// `sampleAtTap` is what turns that into "ignore the tap".
  func testTransparentSamplesAsZeroAlpha() {
    let sampled = EditorStore.sampleColor(layers: [], size: size, at: CGPoint(x: 1, y: 1))
    XCTAssertNotNil(sampled)
    var alpha: CGFloat = 1
    sampled?.getRed(nil, green: nil, blue: nil, alpha: &alpha)
    XCTAssertEqual(alpha, 0, accuracy: 0.01)
  }

  /// The strip flags. The eyedropper acts on a tap like the bucket and the
  /// wand, keeps the ink swatch on screen because it is what fills it, and
  /// carries neither a width nor a tolerance: it reads one pixel.
  func testToolFlags() {
    let tool = BrushTool.eyedropper
    XCTAssertTrue(tool.samplesOnTap)
    XCTAssertTrue(tool.actsOnTap)
    XCTAssertTrue(tool.usesInk, "the swatch is where the sampled colour lands")
    XCTAssertFalse(tool.usesWidth)
    XCTAssertFalse(tool.usesTolerance, "one pixel has no region to grow")
    XCTAssertFalse(tool.fillsOnTap)
    XCTAssertFalse(tool.selects)
    XCTAssertFalse(tool.selectsByDrag)
    XCTAssertFalse(tool.respondsToTilt)
    XCTAssertEqual(tool.displayName, "Eyedropper")
    XCTAssertTrue(BrushTool.allCases.contains(.eyedropper), "it must be in the strip")
  }

  /// Only the eyedropper samples, and the tap-tool flags stay disjoint — the
  /// bucket must not start sampling, nor the eyedropper filling.
  func testTapToolsStayDisjoint() {
    for tool in BrushTool.allCases {
      XCTAssertEqual(tool.samplesOnTap, tool == .eyedropper, "\(tool.displayName)")
      XCTAssertFalse(
        tool.samplesOnTap && (tool.fillsOnTap || tool.selectsOnTap), "\(tool.displayName)")
    }
  }
}

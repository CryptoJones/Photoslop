// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// A text box is held inside the canvas, so its handles can always be reached
/// (#315).
final class TextBoxWithinCanvasTests: XCTestCase {

  private let canvas = CGRect(x: 0, y: 0, width: 2048, height: 1536)

  // MARK: - The reported case

  /// Type set at 400 pt measures wider than a phone-sized canvas. Before #315
  /// the box opened at that size with its corners beyond the artwork: drawn,
  /// but off the canvas and out of reach, so it could be dragged around and
  /// never resized.
  func testABoxWiderThanTheCanvasIsBroughtInside() {
    let oversized = CGRect(x: 40, y: 40, width: 4000, height: 900)
    let result = CropGeometry.contained(oversized, within: canvas)

    XCTAssertTrue(canvas.contains(result), "every corner has to be on the canvas")
    XCTAssertLessThanOrEqual(result.width, canvas.width)
    XCTAssertLessThanOrEqual(result.height, canvas.height)
  }

  /// Shrinking must not squash: text placement locks the box to the words'
  /// aspect, so changing it here would change the type's proportions on open.
  func testShrinkingPreservesTheShape() {
    let oversized = CGRect(x: 0, y: 0, width: 4000, height: 1000)
    let result = CropGeometry.contained(oversized, within: canvas)

    let before = oversized.width / oversized.height
    let after = result.width / result.height
    XCTAssertEqual(after, before, accuracy: 0.02, "the box was squashed, not scaled")
  }

  /// A box that fits but hangs over an edge only needs sliding in.
  func testABoxThatMerelyOverhangsIsSlidInWithoutResizing() {
    let overhanging = CGRect(x: 1800, y: 1400, width: 600, height: 400)
    let result = CropGeometry.contained(overhanging, within: canvas)

    XCTAssertEqual(result.size, overhanging.size, "nothing needed shrinking here")
    XCTAssertTrue(canvas.contains(result))
    XCTAssertEqual(result.maxX, canvas.maxX, accuracy: 1)
    XCTAssertEqual(result.maxY, canvas.maxY, accuracy: 1)
  }

  /// A box already inside is left exactly alone.
  func testABoxThatAlreadyFitsIsUntouched() {
    let fine = CGRect(x: 100, y: 200, width: 400, height: 300)
    XCTAssertEqual(CropGeometry.contained(fine, within: canvas), fine)
  }

  /// Negative origins are as unreachable as oversized ones.
  func testABoxStartingOffTheTopLeftIsBroughtBack() {
    let escaped = CGRect(x: -500, y: -300, width: 400, height: 300)
    let result = CropGeometry.contained(escaped, within: canvas)

    XCTAssertEqual(result.minX, 0, accuracy: 1)
    XCTAssertEqual(result.minY, 0, accuracy: 1)
    XCTAssertTrue(canvas.contains(result))
  }

  /// Degenerate input must not crash or invent a rectangle.
  func testEmptyRectanglesAreReturnedUnchanged() {
    let empty = CGRect(x: 10, y: 10, width: 0, height: 0)
    XCTAssertEqual(CropGeometry.contained(empty, within: canvas), empty)
    XCTAssertEqual(CropGeometry.contained(empty, within: .zero), empty)
  }

  /// Whole pixels, like every other box in the editor.
  func testTheResultSitsOnWholePixels() {
    let awkward = CGRect(x: 10.4, y: 20.7, width: 3333.3, height: 777.7)
    let result = CropGeometry.contained(awkward, within: canvas)

    XCTAssertEqual(result.origin.x, result.origin.x.rounded())
    XCTAssertEqual(result.origin.y, result.origin.y.rounded())
    XCTAssertEqual(result.width, result.width.rounded())
    XCTAssertEqual(result.height, result.height.rounded())
  }

  // MARK: - The end-to-end shape of it

  /// A real text layer at a size that overflows the canvas still yields a box
  /// the canvas can hold.
  func testARealOversizedTextLayerYieldsAContainedBox() throws {
    let store = EditorStore()
    XCTAssertTrue(
      store.addTextLayer(
        "THIS IS A VERY LONG HEADLINE", fontSize: 400, color: .white,
        at: CGPoint(x: 40, y: 40)))
    let id = try XCTUnwrap(store.layers.last?.id)
    let measured = try XCTUnwrap(store.textRect(for: id))

    let bounds = CGRect(origin: .zero, size: store.canvasSize)
    XCTAssertGreaterThan(
      measured.width, bounds.width,
      "precondition: 400 pt really does overflow the default canvas")

    let opened = CropGeometry.contained(measured, within: bounds)
    XCTAssertTrue(bounds.contains(opened), "the box the user gets must be reachable")
  }
}

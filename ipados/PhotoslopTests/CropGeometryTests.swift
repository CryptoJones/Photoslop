// SPDX-License-Identifier: Apache-2.0
import XCTest

@testable import PhotoslopIPad

/// Crop rectangle arithmetic.
///
/// The drag handling is a view's problem; the clamping and the aspect
/// correction are not, and they are where a crop goes wrong — a rectangle that
/// leaves the canvas, collapses to nothing, or jumps out from under the finger
/// when a ratio is locked.
final class CropGeometryTests: XCTestCase {
  private let canvas = CGSize(width: 400, height: 300)
  private var whole: CGRect { CGRect(origin: .zero, size: canvas) }

  // MARK: free dragging

  func testDraggingAnEdgeMovesOnlyThatEdge() {
    let result = CropGeometry.resized(
      whole, handle: .left, translation: CGSize(width: 50, height: 0),
      canvas: canvas, aspect: .free)

    XCTAssertEqual(result, CGRect(x: 50, y: 0, width: 350, height: 300))
  }

  func testDraggingACornerMovesTwoEdges() {
    let result = CropGeometry.resized(
      whole, handle: .bottomRight, translation: CGSize(width: -100, height: -100),
      canvas: canvas, aspect: .free)

    XCTAssertEqual(result, CGRect(x: 0, y: 0, width: 300, height: 200))
  }

  func testTheRectangleCannotLeaveTheCanvas() {
    let result = CropGeometry.resized(
      whole, handle: .left, translation: CGSize(width: -500, height: 0),
      canvas: canvas, aspect: .free)

    XCTAssertEqual(result.minX, 0, "dragged past the left edge")
    XCTAssertLessThanOrEqual(result.maxX, canvas.width)
  }

  func testTheRectangleCannotCollapse() {
    // A crop of nothing would apply as a canvas no document could open.
    let result = CropGeometry.resized(
      whole, handle: .right, translation: CGSize(width: -1000, height: 0),
      canvas: canvas, aspect: .free)

    XCTAssertGreaterThanOrEqual(result.width, CropGeometry.minimumSide)
  }

  func testDraggingTheInteriorMovesWithoutResizing() {
    let start = CGRect(x: 50, y: 50, width: 100, height: 80)
    let result = CropGeometry.resized(
      start, handle: .interior, translation: CGSize(width: 30, height: 20),
      canvas: canvas, aspect: .free)

    XCTAssertEqual(result.size, start.size, "moving the region must not resize it")
    XCTAssertEqual(result.origin, CGPoint(x: 80, y: 70))
  }

  func testMovingTheInteriorStopsAtTheEdgeInsteadOfSlidingOutside() {
    let start = CGRect(x: 300, y: 200, width: 100, height: 100)
    let result = CropGeometry.moved(
      start, by: CGSize(width: 500, height: 500), in: whole)

    XCTAssertEqual(result, CGRect(x: 300, y: 200, width: 100, height: 100))
    XCTAssertLessThanOrEqual(result.maxX, canvas.width)
    XCTAssertLessThanOrEqual(result.maxY, canvas.height)
  }

  // MARK: locked aspect

  func testASquareLockKeepsTheRectangleSquare() {
    let start = CGRect(x: 0, y: 0, width: 200, height: 200)
    let result = CropGeometry.resized(
      start, handle: .right, translation: CGSize(width: -80, height: 0),
      canvas: canvas, aspect: .square)

    XCTAssertEqual(result.width, result.height, accuracy: 1, "square lock did not hold")
  }

  func testALockedDragKeepsTheOppositeCornerStill() {
    // Correcting the ratio by moving the anchored corner would drag the
    // rectangle out from under the finger.
    let start = CGRect(x: 100, y: 100, width: 200, height: 200)
    let result = CropGeometry.resized(
      start, handle: .bottomRight, translation: CGSize(width: -60, height: 0),
      canvas: canvas, aspect: .square)

    XCTAssertEqual(result.minX, start.minX, accuracy: 1, "the anchored left edge moved")
    XCTAssertEqual(result.minY, start.minY, accuracy: 1, "the anchored top edge moved")
  }

  func testSixteenNineProducesSixteenNine() {
    let result = CropGeometry.resized(
      whole, handle: .right, translation: CGSize(width: -80, height: 0),
      canvas: canvas, aspect: .sixteenNine)

    XCTAssertEqual(result.width / result.height, 16.0 / 9.0, accuracy: 0.05)
  }

  func testALockedRectangleStillFitsInsideTheCanvas() {
    for aspect in CropAspect.allCases {
      let result = CropGeometry.initialRect(canvas: canvas, aspect: aspect)
      XCTAssertGreaterThanOrEqual(result.minX, 0, "\(aspect.displayName) starts off-canvas")
      XCTAssertGreaterThanOrEqual(result.minY, 0, "\(aspect.displayName) starts off-canvas")
      XCTAssertLessThanOrEqual(result.maxX, canvas.width, "\(aspect.displayName) overflows")
      XCTAssertLessThanOrEqual(result.maxY, canvas.height, "\(aspect.displayName) overflows")
    }
  }

  func testOriginalMatchesTheCanvasShape() {
    let ratio = CropAspect.original.ratio(canvas: canvas)
    XCTAssertEqual(ratio ?? 0, canvas.width / canvas.height, accuracy: 0.001)
    XCTAssertNil(CropAspect.free.ratio(canvas: canvas), "Free must not constrain anything")
  }

  func testFreeIsTheOnlyUnlockedAspect() {
    XCTAssertFalse(CropAspect.free.isLocked)
    for aspect in CropAspect.allCases where aspect != .free {
      XCTAssertTrue(aspect.isLocked, "\(aspect.displayName) should report as locked")
    }
  }

  func testTheWholeCanvasIsTheStartingRectangleWhenUnlocked() {
    XCTAssertEqual(CropGeometry.initialRect(canvas: canvas, aspect: .free), whole)
  }
}

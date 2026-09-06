// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Fill Selection (#393): the selected pixels take a flat colour.
@MainActor
final class FillSelectionTests: XCTestCase {
  private func document(_ size: CGSize = CGSize(width: 16, height: 12)) -> EditorStore {
    let store = EditorStore()
    store.newDocument(size: size)
    return store
  }

  /// Paint a rectangle of the layer red, so a selection can span two colours.
  private func paintRedBox(_ store: EditorStore, _ rect: CGRect) throws {
    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(
      store.applyPixelOperation(to: layer.id, actionName: "Box") { buffer in
        let red = PixelBuffer.premultipliedWord(r: 255, g: 0, b: 0, a: 255)
        for y in Int(rect.minY)..<Int(rect.maxY) {
          for x in Int(rect.minX)..<Int(rect.maxX) { buffer.setWord(red, x: x, y: y) }
        }
        return true
      })
  }

  private func pixels(_ store: EditorStore) throws -> PixelBuffer {
    try XCTUnwrap(PixelBuffer(image: try XCTUnwrap(store.activeLayer).image))
  }

  private let blue = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 255, a: 255)

  func testTheSelectedPixelsTakeTheInkAsOneUndoStep() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    // The left half, selected by hand the way a lasso would leave it.
    store.setSelection(
      SelectionMask(
        width: 16, height: 12, bits: (0..<12).flatMap { _ in (0..<16).map { $0 < 8 } }))

    XCTAssertEqual(store.fillSelection(color: .blue, opacity: 1), .filled)
    XCTAssertEqual(undoManager.undoActionName, "Fill Selection")

    let buffer = try pixels(store)
    for y in 0..<12 {
      for x in 0..<16 {
        XCTAssertEqual(
          buffer.word(x: x, y: y), x < 8 ? blue : 0xFFFF_FFFF, "pixel (\(x), \(y))")
      }
    }

    // The selection outlives the fill, so filling the same ink again changes
    // no pixel and registers no step.
    XCTAssertNotNil(store.selection)
    XCTAssertEqual(store.fillSelection(color: .blue, opacity: 1), .unchanged)

    undoManager.undo()
    XCTAssertEqual(try pixels(store).word(x: 0, y: 0), 0xFFFF_FFFF)
  }

  /// The reason this exists beside the bucket: the bucket grows a region of
  /// *similar* colour from a tap, so on a selection spanning two colours it
  /// paints only the one it was tapped in. Fill Selection takes the shape.
  func testFillTakesTheWholeSelectionWhereTheBucketTakesOneRegion() throws {
    let store = document()
    try paintRedBox(store, CGRect(x: 4, y: 3, width: 6, height: 4))
    store.setSelection(SelectionMask.all(width: 16, height: 12))

    XCTAssertEqual(
      store.paintBucket(at: CGPoint(x: 0, y: 0), tolerance: 0, color: .blue, opacity: 1), .filled)
    let bucketed = try pixels(store)
    XCTAssertEqual(bucketed.word(x: 0, y: 0), blue)
    XCTAssertNotEqual(bucketed.word(x: 5, y: 4), blue, "the bucket stops at the red box")

    XCTAssertEqual(store.fillSelection(color: .blue, opacity: 1), .filled)
    let filled = try pixels(store)
    for y in 0..<12 {
      for x in 0..<16 { XCTAssertEqual(filled.word(x: x, y: y), blue, "pixel (\(x), \(y))") }
    }
  }

  /// Through a feathered selection the ink lands by weight, the way Delete
  /// Selection fades (#370): full in the middle, partial on the ramp, none
  /// outside it.
  func testAFeatheredSelectionFillsByWeight() throws {
    // A 16 px box inside a 48 px canvas with a 2 px feather. The ramp is three
    // box blurs of radius `feather / 2 + 1`, so it reaches roughly six pixels
    // either side of the hard edge: narrow enough that the box's middle still
    // saturates and the canvas corner is never reached. A 6 px feather on a
    // 16 px box does neither — the ramps meet in the middle at 0.85 and the
    // tail runs to the canvas edge, which is the feather working, not failing.
    let store = document(CGSize(width: 48, height: 48))
    store.setSelection(
      SelectionMask(
        width: 48, height: 48,
        bits: (0..<48).flatMap { y in
          (0..<48).map { x in (16..<32).contains(x) && (16..<32).contains(y) }
        }
      ))
    store.setFeather(2)
    XCTAssertEqual(try XCTUnwrap(store.selection).feather, 2)

    XCTAssertEqual(store.fillSelection(color: .blue, opacity: 1), .filled)
    let buffer = try pixels(store)
    XCTAssertEqual(buffer.word(x: 24, y: 24), blue, "the middle takes the ink outright")
    XCTAssertEqual(buffer.word(x: 0, y: 0), 0xFFFF_FFFF, "beyond the ramp nothing is painted")
    let edge = buffer.word(x: 16, y: 24)
    XCTAssertNotEqual(edge, blue, "the selection's edge is not filled outright")
    XCTAssertNotEqual(edge, 0xFFFF_FFFF, "the selection's edge is not left alone")
  }

  /// The ink is premultiplied exactly as the bucket premultiplies it, so the
  /// swatch writes the same word through either route.
  func testTheInkMatchesTheBucketsWordAtEveryOpacity() throws {
    let bucketed = document()
    bucketed.setSelection(SelectionMask.all(width: 16, height: 12))
    XCTAssertEqual(
      bucketed.paintBucket(at: CGPoint(x: 1, y: 1), tolerance: 0, color: .blue, opacity: 0.5),
      .filled)

    let filled = document()
    filled.setSelection(SelectionMask.all(width: 16, height: 12))
    XCTAssertEqual(filled.fillSelection(color: .blue, opacity: 0.5), .filled)

    XCTAssertEqual(try pixels(filled).word(x: 1, y: 1), try pixels(bucketed).word(x: 1, y: 1))
  }

  func testFillRefusesTextLayersAndDoesNothingWithNoSelection() throws {
    let store = document()
    XCTAssertEqual(
      store.fillSelection(color: .blue, opacity: 1), .unchanged,
      "with nothing selected there is no shape to fill")
    store.selectAll()
    XCTAssertTrue(store.addTextLayer("T", fontSize: 12, color: .black, at: CGPoint(x: 2, y: 2)))
    XCTAssertEqual(store.fillSelection(color: .blue, opacity: 1), .textLayer)
  }
}

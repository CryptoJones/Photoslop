// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// The selection model and the magic wand (#326).
@MainActor
final class SelectionTests: XCTestCase {
  private func mask(_ rows: [String]) -> SelectionMask {
    SelectionMask(
      width: rows[0].count, height: rows.count, bits: rows.flatMap { $0.map { $0 == "#" } })
  }

  private func rows(_ mask: SelectionMask) -> [String] {
    (0..<mask.height).map { y in
      String((0..<mask.width).map { mask.contains(x: $0, y: y) ? "#" : "." })
    }
  }

  // MARK: - SelectionMask

  func testBoundsAndCountFollowTheSelectedPixels() {
    let empty = mask(["....", "....", "...."])
    XCTAssertTrue(empty.isEmpty)
    XCTAssertNil(empty.bounds)
    let some = mask(["....", ".##.", "...#"])
    XCTAssertEqual(some.count, 3)
    XCTAssertEqual(some.bounds, PixelRect(x: 1, y: 1, width: 3, height: 2))
    XCTAssertEqual(SelectionMask.all(width: 4, height: 3).count, 12)
    XCTAssertFalse(some.contains(x: 4, y: 0), "outside the canvas is never selected")
  }

  func testUnionSubtractionAndInversionAreThePathOperationsTheDesktopUses() {
    let a = mask(["##..", "##..", "...."])
    let b = mask([".##.", ".##.", "...."])
    XCTAssertEqual(rows(a.united(with: b)), ["###.", "###.", "...."])
    XCTAssertEqual(rows(a.subtracting(b)), ["#...", "#...", "...."])
    XCTAssertEqual(rows(a.inverted()), ["..##", "..##", "####"])
    XCTAssertNotEqual(a.id, a.inverted().id, "every mutation mints a new identity")
  }

  func testOutlineMergesUnitEdgesIntoRunsAndClosesAtTheCanvasEdge() {
    // A 2x2 block in the middle of a 4x3 canvas has a perimeter of 8 unit
    // edges that merge into 4 segments, one per side.
    let block = mask(["....", ".##.", ".##."])
    let segments = block.outlineSegments()
    XCTAssertEqual(segments.count, 4)
    let sides = Set(segments.map { "\(Int($0.0.x)),\(Int($0.0.y))-\(Int($0.1.x)),\(Int($0.1.y))" })
    XCTAssertEqual(sides, ["1,1-3,1", "1,3-3,3", "1,1-1,3", "3,1-3,3"])

    // Select All still has an outline: the canvas edge counts as unselected,
    // so the ants run round the picture.
    let all = SelectionMask.all(width: 4, height: 3)
    XCTAssertEqual(all.outlineSegments().count, 4)
    // And a hole is outlined on both its sides.
    let ring = mask(["###", "#.#", "###"])
    XCTAssertEqual(ring.outlineSegments().count, 8)
  }

  // MARK: - EditorStore

  private func document(_ size: CGSize = CGSize(width: 16, height: 12)) -> EditorStore {
    let store = EditorStore()
    store.newDocument(size: size)
    return store
  }

  /// Paint a rectangle of the layer red so the white canvas has two regions.
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

  func testWandSelectsTheTappedRegionWithoutAnUndoStep() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    try paintRedBox(store, CGRect(x: 4, y: 3, width: 6, height: 4))
    let stepsBefore = undoManager.canUndo

    XCTAssertEqual(
      store.magicWand(at: CGPoint(x: 5.5, y: 3.2), tolerance: 0, contiguous: true, combine: .replace),
      .selected)
    let selection = try XCTUnwrap(store.selection)
    XCTAssertEqual(selection.count, 24)
    XCTAssertEqual(selection.bounds, PixelRect(x: 4, y: 3, width: 6, height: 4))
    XCTAssertEqual(undoManager.canUndo, stepsBefore, "selecting is not a step")
    XCTAssertEqual(undoManager.undoActionName, "Box")

    // Off the canvas: nothing happens and the selection stands.
    XCTAssertEqual(
      store.magicWand(at: CGPoint(x: 16, y: 0), tolerance: 0, contiguous: true, combine: .replace),
      .unchanged)
    XCTAssertEqual(store.selection?.id, selection.id)
  }

  func testWandCombinesLikeShiftAndAltClicks() throws {
    let store = document()
    try paintRedBox(store, CGRect(x: 4, y: 3, width: 6, height: 4))
    // Replace: the white outside, everything but the box.
    store.magicWand(at: CGPoint(x: 0, y: 0), tolerance: 0, contiguous: true, combine: .replace)
    XCTAssertEqual(store.selection?.count, 16 * 12 - 24)
    // Add the box: the whole canvas.
    store.magicWand(at: CGPoint(x: 5, y: 4), tolerance: 0, contiguous: true, combine: .add)
    XCTAssertEqual(store.selection?.count, 16 * 12)
    // Subtract the white again: the box alone.
    store.magicWand(at: CGPoint(x: 0, y: 0), tolerance: 0, contiguous: true, combine: .subtract)
    XCTAssertEqual(store.selection?.bounds, PixelRect(x: 4, y: 3, width: 6, height: 4))
    // Subtracting the box from itself leaves nothing, and nothing is nil.
    store.magicWand(at: CGPoint(x: 5, y: 4), tolerance: 0, contiguous: true, combine: .subtract)
    XCTAssertNil(store.selection)
    // A subtract with no selection to cut from is a no-op.
    XCTAssertEqual(
      store.magicWand(at: CGPoint(x: 5, y: 4), tolerance: 0, contiguous: true, combine: .subtract),
      .unchanged)
  }

  func testNonContiguousWandTakesEveryRegionOfTheColour() throws {
    let store = document()
    try paintRedBox(store, CGRect(x: 1, y: 1, width: 2, height: 2))
    try paintRedBox(store, CGRect(x: 12, y: 8, width: 2, height: 2))
    store.magicWand(at: CGPoint(x: 1, y: 1), tolerance: 0, contiguous: true, combine: .replace)
    XCTAssertEqual(store.selection?.count, 4)
    store.magicWand(at: CGPoint(x: 1, y: 1), tolerance: 0, contiguous: false, combine: .replace)
    XCTAssertEqual(store.selection?.count, 8)
  }

  func testSelectAllDeselectAndInvert() throws {
    let store = document()
    XCTAssertNil(store.selection)
    store.invertSelection()
    XCTAssertEqual(store.selection?.count, 16 * 12, "inverting nothing is Select All")
    store.deselect()
    XCTAssertNil(store.selection)
    try paintRedBox(store, CGRect(x: 4, y: 3, width: 6, height: 4))
    store.magicWand(at: CGPoint(x: 5, y: 4), tolerance: 0, contiguous: true, combine: .replace)
    store.invertSelection()
    XCTAssertEqual(store.selection?.count, 16 * 12 - 24)
    XCTAssertFalse(try XCTUnwrap(store.selection).contains(x: 5, y: 4))
    store.selectAll()
    XCTAssertEqual(store.selection?.count, 16 * 12)
  }

  func testDeleteSelectionClearsTheSelectedPixelsAsOneUndoStep() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    try paintRedBox(store, CGRect(x: 4, y: 3, width: 6, height: 4))
    // The workflow this exists for: wand the background, delete it.
    store.magicWand(at: CGPoint(x: 0, y: 0), tolerance: 0, contiguous: true, combine: .replace)
    XCTAssertEqual(store.deleteSelection(), .deleted)
    XCTAssertEqual(undoManager.undoActionName, "Delete Selection")
    let buffer = try XCTUnwrap(PixelBuffer(image: try XCTUnwrap(store.activeLayer).image))
    for y in 0..<12 {
      for x in 0..<16 {
        let inBox = (4..<10).contains(x) && (3..<7).contains(y)
        XCTAssertEqual(buffer.word(x: x, y: y) == 0, !inBox, "pixel (\(x), \(y))")
      }
    }
    // The selection outlives the delete, so a second delete has nothing to
    // clear and registers no step.
    XCTAssertNotNil(store.selection)
    XCTAssertEqual(store.deleteSelection(), .unchanged)
    undoManager.undo()
    let restored = try XCTUnwrap(PixelBuffer(image: try XCTUnwrap(store.activeLayer).image))
    XCTAssertEqual(restored.word(x: 0, y: 0), 0xFFFF_FFFF)
  }

  func testDeleteSelectionRefusesTextLayersAndNothingSelected() throws {
    let store = document()
    XCTAssertEqual(store.deleteSelection(), .unchanged)
    store.selectAll()
    XCTAssertTrue(store.addTextLayer("T", fontSize: 12, color: .black, at: CGPoint(x: 2, y: 2)))
    XCTAssertEqual(store.deleteSelection(), .textLayer)
  }

  func testBucketStaysInsideTheSelection() throws {
    let store = document()
    // Select the left half by hand, then fill the white canvas from inside it.
    store.setSelection(
      SelectionMask(
        width: 16, height: 12,
        bits: (0..<12).flatMap { _ in (0..<16).map { $0 < 8 } }))
    XCTAssertEqual(
      store.paintBucket(at: CGPoint(x: 2, y: 2), tolerance: 0, color: .blue, opacity: 1), .filled)
    let buffer = try XCTUnwrap(PixelBuffer(image: try XCTUnwrap(store.activeLayer).image))
    let blue = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 255, a: 255)
    XCTAssertEqual(buffer.word(x: 7, y: 5), blue)
    XCTAssertEqual(buffer.word(x: 8, y: 5), 0xFFFF_FFFF, "the fill stops at the selection")
    // A tap outside the selection fills nothing.
    XCTAssertEqual(
      store.paintBucket(at: CGPoint(x: 12, y: 2), tolerance: 0, color: .blue, opacity: 1),
      .unchanged)
  }

  func testSelectionIsDroppedWhenTheCanvasChangesSize() throws {
    let store = document()
    store.selectAll()
    XCTAssertNotNil(store.selection)
    store.resizeCanvas(to: CGSize(width: 20, height: 12))
    XCTAssertNil(store.selection, "a mask for the old canvas describes no pixel of the new one")
    store.selectAll()
    store.crop(to: CGRect(x: 2, y: 2, width: 8, height: 6))
    XCTAssertNil(store.selection)
    // Same-size operations keep it.
    store.selectAll()
    let before = try XCTUnwrap(store.selection).id
    XCTAssertTrue(store.addTextLayer("T", fontSize: 12, color: .black, at: CGPoint(x: 1, y: 1)))
    XCTAssertEqual(store.selection?.id, before)
  }

  func testEverySelectionCombineHasASymbol() {
    for mode in SelectionCombine.allCases {
      XCTAssertNotNil(
        UIImage(systemName: mode.symbolName),
        "\(mode.displayName) has no SF Symbol named \(mode.symbolName)")
    }
    for name in [
      "wand.and.rays", "square.dashed", "square.dashed.inset.filled",
      "circle.lefthalf.filled.inverse", "scissors",
      "point.topleft.down.to.point.bottomright.curvepath",
    ] {
      XCTAssertNotNil(UIImage(systemName: name), "no SF Symbol named \(name)")
    }
  }
}

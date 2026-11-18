// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Unit tests for selection to vector path contour tracing and Bézier fitting (#424).
@MainActor
final class VectorPathTests: XCTestCase {
  private func mask(_ rows: [String]) -> SelectionMask {
    SelectionMask(
      width: rows[0].count, height: rows.count, bits: rows.flatMap { $0.map { $0 == "#" } })
  }

  func testEmptySelectionProducesNoCommands() {
    let empty = mask(["....", "....", "...."])
    let commands = empty.makeVectorPath()
    XCTAssertTrue(commands.isEmpty)
    XCTAssertTrue(empty.vectorCGPath().isEmpty)
  }

  func testRectangleContourExtractionAndCommands() {
    let block = mask([
      "......",
      ".####.",
      ".####.",
      ".####.",
      "......",
    ])
    let commands = block.makeVectorPath(tolerance: 2.0)
    XCTAssertFalse(commands.isEmpty)
    XCTAssertEqual(commands.first?.op, "M")
    XCTAssertEqual(commands.last?.op, "Z")
    let cOps = commands.filter { $0.op == "C" }
    // A rectangle has 4 sides
    XCTAssertEqual(cOps.count, 4)
    for c in cOps {
      XCTAssertEqual(c.node, "corner")
    }

    let svg = commands.toSVGPath()
    XCTAssertTrue(svg.hasPrefix("M "))
    XCTAssertTrue(svg.hasSuffix("Z"))
  }

  func testDonutContourExtractionHasTwoSubpaths() {
    let donut = mask([
      "#####",
      "#...#",
      "#...#",
      "#...#",
      "#####",
    ])
    let commands = donut.makeVectorPath(tolerance: 2.0)
    let mCount = commands.filter { $0.op == "M" }.count
    let zCount = commands.filter { $0.op == "Z" }.count
    XCTAssertEqual(mCount, 2, "outer loop + inner hole loop")
    XCTAssertEqual(zCount, 2)
  }

  func testToleranceSimplificationReducesPoints() {
    // Generate a 20x20 circle mask
    var rows: [String] = []
    for y in 0..<20 {
      var row = ""
      for x in 0..<20 {
        let dx = Double(x - 10)
        let dy = Double(y - 10)
        row += (dx * dx + dy * dy <= 64) ? "#" : "."
      }
      rows.append(row)
    }
    let circle = mask(rows)
    let tight = circle.makeVectorPath(tolerance: 0.5)
    let loose = circle.makeVectorPath(tolerance: 8.0)
    XCTAssertLessThan(loose.count, tight.count)
  }

  func testStoreMakeVectorPathAddsLayerAndUndoes() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 40, height: 40))
    let undoManager = UndoManager()
    store.undoManager = undoManager

    // Without a selection: no layer is added
    store.makeVectorPath()
    XCTAssertEqual(store.layers.count, 1)

    // With a selection: creates a new vector path layer
    store.setSelection(
      mask([
        "................",
        "..############..",
        "..############..",
        "..############..",
        "................",
      ]))

    store.makeVectorPath()
    XCTAssertEqual(store.layers.count, 2)
    let layer = store.activeLayer
    XCTAssertNotNil(layer)
    XCTAssertTrue(layer?.name.contains("Vector Path") ?? false)

    // Undo removes the layer
    XCTAssertTrue(undoManager.canUndo)
    undoManager.undo()
    XCTAssertEqual(store.layers.count, 1)

    // Redo restores it
    XCTAssertTrue(undoManager.canRedo)
    undoManager.redo()
    XCTAssertEqual(store.layers.count, 2)
  }
}

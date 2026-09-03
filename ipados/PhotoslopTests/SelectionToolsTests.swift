// SPDX-License-Identifier: Apache-2.0
import PencilKit
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Strokes through a selection, the marquee, the lasso and the feather on
/// the store (#370, DD-015).
@MainActor
final class SelectionToolsTests: XCTestCase {
  private func document(_ size: CGSize = CGSize(width: 32, height: 24)) -> EditorStore {
    let store = EditorStore()
    store.newDocument(size: size)
    return store
  }

  private func pixels(_ store: EditorStore) throws -> PixelBuffer {
    try XCTUnwrap(PixelBuffer(image: try XCTUnwrap(store.activeLayer).image))
  }

  private func selectBox(_ store: EditorStore, _ rect: CGRect) throws -> SelectionMask {
    store.selectRectangle(
      from: rect.origin, to: CGPoint(x: rect.maxX, y: rect.maxY), combine: .replace)
    return try XCTUnwrap(store.selection)
  }

  /// A horizontal pen stroke, `width` px thick, through row `y`.
  private func stroke(y: CGFloat, from x0: CGFloat, to x1: CGFloat, width: CGFloat = 6)
    -> PKStroke
  {
    let points = [CGPoint(x: x0, y: y), CGPoint(x: x1, y: y)].map {
      PKStrokePoint(
        location: $0, timeOffset: 0, size: CGSize(width: width, height: width), opacity: 1,
        force: 1, azimuth: 0, altitude: .pi / 2)
    }
    return PKStroke(
      ink: PKInk(.pen, color: .black),
      path: PKStrokePath(controlPoints: points, creationDate: Date()))
  }

  // MARK: - Strokes honour the selection

  func testStrokeInsideTheSelectionLandsOnTheLayerAsOneUndoStep() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    let selection = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    XCTAssertEqual(selection.bounds, PixelRect(x: 8, y: 6, width: 16, height: 12))

    let key = store.setDrawing(PKDrawing(strokes: [stroke(y: 12, from: 10, to: 22)]))
    XCTAssertEqual(key, store.activeDrawingKey, "the canvas keeps the stroke until the composite")
    XCTAssertTrue(undoManager.canUndo)
    XCTAssertEqual(undoManager.undoActionName, "Draw")
    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(layer.drawing.strokes.isEmpty, "the stroke is pixels, not a stroke")
    let buffer = try pixels(store)
    XCTAssertEqual(buffer.word(x: 16, y: 12), 0xFF00_0000, "black ink at the stroke's centre")
    XCTAssertEqual(buffer.word(x: 4, y: 12), 0xFFFF_FFFF, "nothing to the left of the stroke")

    undoManager.undo()
    XCTAssertEqual(try pixels(store).word(x: 16, y: 12), 0xFFFF_FFFF)
  }

  func testStrokeOutsideTheSelectionLeavesEveryPixelUntouched() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    _ = try selectBox(store, CGRect(x: 8, y: 12, width: 16, height: 10))
    let before = try pixels(store)

    // A stroke across the top rows, clear of the selection's box even with
    // the pen's soft edge.
    let key = store.setDrawing(PKDrawing(strokes: [stroke(y: 2, from: 0, to: 32)]))
    XCTAssertEqual(key, .empty, "nothing landed, so the canvas lets go of it at once")
    XCTAssertFalse(undoManager.canUndo, "no step for ink that went nowhere")
    let after = try pixels(store)
    XCTAssertEqual(after.word(x: 16, y: 2), 0xFFFF_FFFF, "the stroke's own row is untouched")
    for y in 0..<24 {
      for x in 0..<32 {
        XCTAssertEqual(after.word(x: x, y: y), before.word(x: x, y: y), "pixel (\(x), \(y))")
      }
    }
    XCTAssertTrue(try XCTUnwrap(store.activeLayer).drawing.strokes.isEmpty)
  }

  func testStrokeAcrossTheEdgeIsCutAtTheEdge() throws {
    let store = document()
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    store.setDrawing(PKDrawing(strokes: [stroke(y: 12, from: 0, to: 32)]))
    let buffer = try pixels(store)
    for x in 0..<32 {
      let inside = (8..<24).contains(x)
      XCTAssertEqual(buffer.word(x: x, y: 12) == 0xFF00_0000, inside, "column \(x)")
    }
    // The rows above and below the selection are white on every column.
    for x in 0..<32 {
      XCTAssertEqual(buffer.word(x: x, y: 4), 0xFFFF_FFFF, "column \(x) above")
      XCTAssertEqual(buffer.word(x: x, y: 20), 0xFFFF_FFFF, "column \(x) below")
    }
  }

  func testCompositeCarriesTheStrokeAndNothingOutsideTheSelection() throws {
    let store = document()
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    store.setDrawing(PKDrawing(strokes: [stroke(y: 12, from: 0, to: 32)]))
    let flat = try XCTUnwrap(
      PixelBuffer(image: EditorStore.render(layers: store.layers, size: store.canvasSize)))
    XCTAssertEqual(flat.word(x: 16, y: 12), 0xFF00_0000)
    XCTAssertEqual(flat.word(x: 2, y: 12), 0xFFFF_FFFF)
    XCTAssertEqual(flat.word(x: 29, y: 12), 0xFFFF_FFFF)
  }

  func testStrokesBeforeTheSelectionAreBakedWithTheClippedOne() throws {
    let store = document()
    // A free stroke first, kept as a stroke on the layer.
    store.setDrawing(PKDrawing(strokes: [stroke(y: 2, from: 0, to: 32)]))
    XCTAssertEqual(try XCTUnwrap(store.activeLayer).drawing.strokes.count, 1)
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    XCTAssertTrue(
      store.activeCanvasDrawing.strokes.isEmpty, "the canvas shows nothing under a selection")
    store.setDrawing(PKDrawing(strokes: [stroke(y: 12, from: 10, to: 22)]))
    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(layer.drawing.strokes.isEmpty, "the old stroke was baked with the new one")
    let buffer = try pixels(store)
    XCTAssertEqual(buffer.word(x: 16, y: 2), 0xFF00_0000, "the free stroke survives the bake")
    XCTAssertEqual(buffer.word(x: 16, y: 12), 0xFF00_0000)
    store.setSelection(nil)
    XCTAssertEqual(store.activeDrawingKey, layer.drawingKey)
  }

  func testEraserUnderASelectionErasesPixelsInsideOnly() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    // The eraser's frosted preview ink: what the canvas shows while erasing.
    let preview = PKStroke(
      ink: PKInk(.pen, color: BrushTool.selectionEraserInk),
      path: stroke(y: 12, from: 0, to: 32).path)
    store.setDrawing(PKDrawing(strokes: [preview]), erasing: true)
    XCTAssertEqual(undoManager.undoActionName, "Erase")
    let buffer = try pixels(store)
    XCTAssertEqual(buffer.word(x: 16, y: 12), 0, "erased to clear, not tinted")
    XCTAssertEqual(buffer.word(x: 2, y: 12), 0xFFFF_FFFF, "outside the selection: untouched")
    XCTAssertEqual(buffer.word(x: 16, y: 2), 0xFFFF_FFFF)
  }

  func testSelectionStrokeRefusesTextLayersWithoutAStep() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    XCTAssertTrue(store.addTextLayer("T", fontSize: 12, color: .black, at: CGPoint(x: 2, y: 2)))
    let text = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(text.isText)
    _ = try selectBox(store, CGRect(x: 0, y: 0, width: 32, height: 24))
    let steps = undoManager.undoActionName
    let key = store.setDrawing(PKDrawing(strokes: [stroke(y: 12, from: 0, to: 32)]))
    XCTAssertEqual(key, .empty)
    XCTAssertEqual(undoManager.undoActionName, steps)
  }

  func testSuspendedKeyIsNeverALayersKeyAndStepsWhenTheCompositeLands() throws {
    let store = document()
    let layer = try XCTUnwrap(store.activeLayer)
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    let suspended = store.activeDrawingKey
    XCTAssertEqual(suspended.layer, layer.id)
    XCTAssertLessThan(suspended.revision, 0)
    XCTAssertNotEqual(suspended, layer.drawingKey)
    store.setDrawing(PKDrawing(strokes: [stroke(y: 12, from: 10, to: 22)]))
    XCTAssertEqual(store.activeDrawingKey, suspended, "held until the composite carries it")
    let landed = expectation(description: "composite with the stroke")
    Task { @MainActor in
      // The refresh is asynchronous; poll until the generation steps.
      for _ in 0..<200 where store.activeDrawingKey == suspended {
        try? await Task.sleep(nanoseconds: 10_000_000)
      }
      landed.fulfill()
    }
    wait(for: [landed], timeout: 5)
    XCTAssertNotEqual(store.activeDrawingKey, suspended)
    XCTAssertLessThan(store.activeDrawingKey.revision, 0)
  }

  func testStrokeClipPathCoversExactlyTheSelectedPixels() throws {
    let store = document()
    XCTAssertNil(store.strokeClip())
    let selection = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    let clip = try XCTUnwrap(store.strokeClip())
    XCTAssertEqual(clip.id, selection.id)
    XCTAssertEqual(clip.path.boundingBox, CGRect(x: 8, y: 6, width: 16, height: 12))
    XCTAssertTrue(clip.path.contains(CGPoint(x: 8.5, y: 6.5)))
    XCTAssertFalse(clip.path.contains(CGPoint(x: 7.5, y: 6.5)))
    // Cached per selection; rebuilt for the next one.
    XCTAssertTrue(store.strokeClip()?.path === clip.path)
    _ = try selectBox(store, CGRect(x: 0, y: 0, width: 4, height: 4))
    XCTAssertEqual(store.strokeClip()?.path.boundingBox, CGRect(x: 0, y: 0, width: 4, height: 4))
    store.setSelection(nil)
    XCTAssertNil(store.strokeClip())
  }

  func testFillPathMergesRowsIntoBands() {
    let mask = SelectionMask(
      width: 6, height: 4,
      bits: [
        "..##..",
        "..##..",
        "#....#",
        "......",
      ].flatMap { $0.map { $0 == "#" } })
    let path = mask.fillPath()
    XCTAssertEqual(path.boundingBox, CGRect(x: 0, y: 0, width: 6, height: 3))
    XCTAssertTrue(path.contains(CGPoint(x: 2.5, y: 1.5)))
    XCTAssertTrue(path.contains(CGPoint(x: 0.5, y: 2.5)))
    XCTAssertTrue(path.contains(CGPoint(x: 5.5, y: 2.5)))
    XCTAssertFalse(path.contains(CGPoint(x: 2.5, y: 2.5)))
    XCTAssertFalse(path.contains(CGPoint(x: 0.5, y: 0.5)))
    XCTAssertFalse(path.contains(CGPoint(x: 2.5, y: 3.5)))
  }

  // MARK: - Marquee and lasso

  func testRectangleSelectCombinesLikeTheWand() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    // Reversed drag: the rectangle is normalised.
    store.selectRectangle(from: CGPoint(x: 12, y: 10), to: CGPoint(x: 4, y: 2), combine: .replace)
    var selection = try XCTUnwrap(store.selection)
    XCTAssertEqual(selection.bounds, PixelRect(x: 4, y: 2, width: 8, height: 8))
    XCTAssertEqual(selection.count, 64)
    XCTAssertFalse(undoManager.canUndo, "selecting is not a step")

    store.selectRectangle(from: CGPoint(x: 20, y: 2), to: CGPoint(x: 24, y: 6), combine: .add)
    selection = try XCTUnwrap(store.selection)
    XCTAssertEqual(selection.count, 64 + 16)
    XCTAssertEqual(selection.bounds, PixelRect(x: 4, y: 2, width: 20, height: 8))

    store.selectRectangle(from: CGPoint(x: 4, y: 2), to: CGPoint(x: 8, y: 10), combine: .subtract)
    selection = try XCTUnwrap(store.selection)
    XCTAssertEqual(selection.count, 32 + 16)
    XCTAssertFalse(selection.contains(x: 5, y: 5))
    XCTAssertTrue(selection.contains(x: 9, y: 5))

    // Wholly off the canvas: a click for every mode.
    let standing = selection.id
    store.selectRectangle(from: CGPoint(x: 40, y: 40), to: CGPoint(x: 50, y: 50), combine: .add)
    XCTAssertEqual(store.selection?.id, standing)
    store.selectRectangle(
      from: CGPoint(x: 40, y: 40), to: CGPoint(x: 50, y: 50), combine: .subtract)
    XCTAssertEqual(store.selection?.id, standing)
    store.selectRectangle(
      from: CGPoint(x: 40, y: 40), to: CGPoint(x: 50, y: 50), combine: .replace)
    XCTAssertNil(store.selection)
  }

  func testAClickWithRectangleSelectDeselectsUnderNewSelectionOnly() throws {
    let store = document()
    _ = try selectBox(store, CGRect(x: 4, y: 2, width: 8, height: 8))
    let standing = try XCTUnwrap(store.selection).id
    // Under 2 px both ways: the desktop's click.
    store.selectRectangle(from: CGPoint(x: 6, y: 6), to: CGPoint(x: 7.5, y: 7.5), combine: .add)
    XCTAssertEqual(store.selection?.id, standing)
    store.selectRectangle(
      from: CGPoint(x: 6, y: 6), to: CGPoint(x: 7.5, y: 7.5), combine: .subtract)
    XCTAssertEqual(store.selection?.id, standing)
    store.selectRectangle(
      from: CGPoint(x: 6, y: 6), to: CGPoint(x: 7.5, y: 7.5), combine: .replace)
    XCTAssertNil(store.selection)
    // 2 px in one direction is a marquee again.
    store.selectRectangle(from: CGPoint(x: 6, y: 6), to: CGPoint(x: 8, y: 6.5), combine: .replace)
    XCTAssertNotNil(store.selection)
  }

  func testLassoSelectsThePolygonUnderTheOddEvenRule() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    // A bow tie: the crossing point is inside neither lobe.
    store.selectLasso(
      [
        CGPoint(x: 2, y: 2), CGPoint(x: 30, y: 22), CGPoint(x: 30, y: 2), CGPoint(x: 2, y: 22),
      ], combine: .replace)
    let selection = try XCTUnwrap(store.selection)
    XCTAssertFalse(undoManager.canUndo)
    XCTAssertTrue(selection.contains(x: 5, y: 12))
    XCTAssertTrue(selection.contains(x: 26, y: 12))
    XCTAssertFalse(selection.contains(x: 16, y: 3))
    XCTAssertFalse(selection.contains(x: 16, y: 20))
    XCTAssertEqual(
      selection.bits,
      SelectionMask.rasterise(
        [
          CGPoint(x: 2, y: 2), CGPoint(x: 30, y: 22), CGPoint(x: 30, y: 2),
          CGPoint(x: 2, y: 22),
        ], width: 32, height: 24))

    // Subtract a lasso from the marquee.
    store.selectRectangle(from: .zero, to: CGPoint(x: 32, y: 24), combine: .replace)
    store.selectLasso(
      [CGPoint(x: 0, y: 0), CGPoint(x: 32, y: 0), CGPoint(x: 32, y: 24), CGPoint(x: 0, y: 24)],
      combine: .subtract)
    XCTAssertNil(store.selection, "everything cut away is no selection")
  }

  func testALassoOfFewerThanThreePointsIsAClick() throws {
    let store = document()
    _ = try selectBox(store, CGRect(x: 4, y: 2, width: 8, height: 8))
    let standing = try XCTUnwrap(store.selection).id
    store.selectLasso([CGPoint(x: 1, y: 1), CGPoint(x: 20, y: 20)], combine: .add)
    XCTAssertEqual(store.selection?.id, standing)
    store.selectLasso([CGPoint(x: 1, y: 1)], combine: .replace)
    XCTAssertNil(store.selection)
    // Three collinear points enclose nothing: a click too.
    _ = try selectBox(store, CGRect(x: 4, y: 2, width: 8, height: 8))
    store.selectLasso(
      [CGPoint(x: 1, y: 1), CGPoint(x: 10, y: 1), CGPoint(x: 20, y: 1)], combine: .replace)
    XCTAssertNil(store.selection)
  }

  // MARK: - Feather

  func testFeatherSoftensTheEdgeWithoutMovingTheAnts() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    let hard = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    XCTAssertEqual(hard.feather, 0)
    XCTAssertNil(hard.weights)

    store.setFeather(1)
    let soft = try XCTUnwrap(store.selection)
    XCTAssertEqual(soft.feather, 1)
    XCTAssertEqual(soft.bits, hard.bits, "the ants stay on the hard edge")
    XCTAssertEqual(soft.bounds, hard.bounds)
    XCTAssertNotEqual(soft.id, hard.id)
    XCTAssertFalse(undoManager.canUndo, "feathering is not a step")
    let centre = soft.weight(at: 12 * 32 + 16)
    let edge = soft.weight(at: 12 * 32 + 8)
    let outside = soft.weight(at: 12 * 32 + 6)
    let far = soft.weight(at: 12 * 32 + 1)
    XCTAssertEqual(centre, 255)
    XCTAssertLessThan(edge, 255)
    XCTAssertGreaterThan(edge, 0)
    XCTAssertGreaterThan(outside, 0, "the ramp reaches outside the hard edge")
    XCTAssertEqual(far, 0)

    // The same radius again is nothing; 0 is a hard edge; out of range clamps.
    store.setFeather(1)
    XCTAssertEqual(store.selection?.id, soft.id)
    store.setFeather(0)
    XCTAssertNil(store.selection?.weights)
    XCTAssertEqual(store.selection?.feather, 0)
    store.setFeather(500)
    XCTAssertEqual(store.selection?.feather, EditorStore.featherRange.upperBound)
    store.setFeather(-3)
    XCTAssertEqual(store.selection?.feather, 0)
  }

  func testFeatheredDeleteFadesAtTheEdge() throws {
    let store = document()
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    store.setFeather(1)
    let weights = try XCTUnwrap(store.selection?.weights)
    XCTAssertEqual(store.deleteSelection(), .deleted)
    let buffer = try pixels(store)
    XCTAssertEqual(buffer.word(x: 16, y: 12), 0, "clear at the centre")
    XCTAssertEqual(buffer.word(x: 1, y: 12), 0xFFFF_FFFF, "white far outside")
    let edge = buffer.word(x: 7, y: 12)
    let expected = PixelBuffer.blend(0xFFFF_FFFF, toward: 0, weight: weights[12 * 32 + 7])
    XCTAssertEqual(edge, expected, "blended by the weight, as npimage.blend_by_weights")
    XCTAssertNotEqual(edge, 0)
    XCTAssertNotEqual(edge, 0xFFFF_FFFF)
    XCTAssertEqual(buffer.word(x: 7, y: 12) >> 24, 255 - UInt32(weights[12 * 32 + 7]))
  }

  func testFeatheredBucketFadesEitherSideOfTheHardEdge() throws {
    let store = document()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    store.setFeather(1)
    let weights = try XCTUnwrap(store.selection?.weights)
    // The whole canvas is one white region; the fill lands by weight.
    XCTAssertEqual(
      store.paintBucket(at: CGPoint(x: 16, y: 12), tolerance: 0, color: .red, opacity: 1),
      .filled)
    XCTAssertEqual(undoManager.undoActionName, "Paint Bucket")
    let buffer = try pixels(store)
    XCTAssertEqual(buffer.word(x: 16, y: 12), 0xFFFF_0000, "solid inside")
    XCTAssertEqual(buffer.word(x: 1, y: 12), 0xFFFF_FFFF, "white beyond the ramp")
    for x in [6, 7, 8, 9] {
      XCTAssertEqual(
        buffer.word(x: x, y: 12),
        PixelBuffer.blend(0xFFFF_FFFF, toward: 0xFFFF_0000, weight: weights[12 * 32 + x]),
        "column \(x)")
    }
    XCTAssertNotEqual(buffer.word(x: 7, y: 12), 0xFFFF_FFFF, "the ramp reaches outside")
    XCTAssertNotEqual(buffer.word(x: 8, y: 12), 0xFFFF_0000, "and inside")
    // Without a feather the hard mask bounds the region as before (#326).
    store.setFeather(0)
    XCTAssertEqual(
      store.paintBucket(at: CGPoint(x: 16, y: 12), tolerance: 0, color: .blue, opacity: 1),
      .filled)
    let hard = try pixels(store)
    XCTAssertEqual(hard.word(x: 16, y: 12), 0xFF00_00FF)
    XCTAssertEqual(hard.word(x: 7, y: 12), buffer.word(x: 7, y: 12), "outside: untouched")
  }

  func testFeatheredStrokeFadesAtTheEdge() throws {
    let store = document()
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    store.setFeather(1)
    let weights = try XCTUnwrap(store.selection?.weights)
    store.setDrawing(PKDrawing(strokes: [stroke(y: 12, from: 0, to: 32)]))
    let buffer = try pixels(store)
    XCTAssertEqual(buffer.word(x: 16, y: 12), 0xFF00_0000, "full ink at the centre")
    XCTAssertEqual(buffer.word(x: 1, y: 12), 0xFFFF_FFFF, "no ink far outside")
    let edge = buffer.word(x: 8, y: 12)
    XCTAssertEqual(edge, PixelBuffer.over(0xFFFF_FFFF, source: 0xFF00_0000, weight: weights[12 * 32 + 8]))
    XCTAssertNotEqual(edge, 0xFF00_0000)
    XCTAssertNotEqual(edge, 0xFFFF_FFFF)
    // Monotone across the ramp: darker the further in.
    let grey = { (x: Int) in buffer.word(x: x, y: 12) & 0xFF }
    XCTAssertGreaterThan(grey(5), grey(7))
    XCTAssertGreaterThan(grey(7), grey(9))
  }

  func testFeatherResetsWithANewSelectionAndIsRefusedWithoutMemory() throws {
    let store = document()
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    store.setFeather(1)
    XCTAssertNotNil(store.selection?.weights)
    store.selectRectangle(from: CGPoint(x: 0, y: 0), to: CGPoint(x: 6, y: 6), combine: .add)
    XCTAssertEqual(store.selection?.feather, 0, "a new selection is hard, as on the desktop")
    XCTAssertNil(store.selection?.weights)
    store.setFeather(0)
    XCTAssertNil(store.memoryPressureNotice)
  }
}

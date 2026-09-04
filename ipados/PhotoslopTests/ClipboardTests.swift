// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Cut, Copy and Paste over a selection (#374, DD-016).
@MainActor
final class ClipboardTests: XCTestCase {
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

  /// The pasteboard's current image as a buffer, which is what a copy is
  /// judged by — the store keeps no clipboard of its own.
  private func copied() throws -> PixelBuffer {
    try XCTUnwrap(PixelBuffer(image: try XCTUnwrap(UIPasteboard.general.image)))
  }

  /// Fill the whole canvas so a copy has something to carry.
  private func paintCanvasRed(_ store: EditorStore) {
    XCTAssertEqual(
      store.paintBucket(at: CGPoint(x: 1, y: 1), tolerance: 255, color: .red, opacity: 1),
      .filled)
  }

  override func setUp() {
    super.setUp()
    // Each test states its own pasteboard: the simulator's is shared and
    // whatever ran before is not this test's input.
    UIPasteboard.general.items = []
  }

  // MARK: - Copy

  func testCopyWithNoSelectionTakesTheWholeLayer() throws {
    let store = document()
    paintCanvasRed(store)
    XCTAssertEqual(store.copySelection(), .copied)
    let buffer = try copied()
    XCTAssertEqual(buffer.width, 32)
    XCTAssertEqual(buffer.height, 24)
    XCTAssertEqual(buffer.word(x: 16, y: 12), 0xFFFF_0000)
  }

  func testCopyCropsToTheSelectionBounds() throws {
    let store = document()
    paintCanvasRed(store)
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    XCTAssertEqual(store.copySelection(), .copied)
    let buffer = try copied()
    XCTAssertEqual(buffer.width, 16, "cropped to the selection, not the canvas")
    XCTAssertEqual(buffer.height, 12)
    XCTAssertEqual(buffer.word(x: 8, y: 6), 0xFFFF_0000, "the selection's pixels came with it")
  }

  func testCopyOutsideTheSelectionIsTransparentNotBlack() throws {
    let store = document()
    paintCanvasRed(store)
    // An L-shaped selection: its bounds include pixels it does not select.
    store.selectRectangle(from: .zero, to: CGPoint(x: 16, y: 8), combine: .replace)
    store.selectRectangle(
      from: CGPoint(x: 0, y: 8), to: CGPoint(x: 8, y: 20), combine: .add)
    XCTAssertEqual(store.copySelection(), .copied)
    let buffer = try copied()
    XCTAssertEqual(buffer.word(x: 2, y: 2), 0xFFFF_0000, "inside the L")
    XCTAssertEqual(
      buffer.word(x: 14, y: 18), 0, "inside the bounds but outside the selection: nothing")
  }

  func testCopyFadesWithTheFeather() throws {
    // Roomy on purpose: `feathered_weights` is three box-blur passes, so a
    // radius of 2 reaches about 6 px in from every edge. A selection whose
    // centre is nearer than that to a corner never reaches full coverage —
    // correctly — and would make "solid in the middle" a lie.
    let store = document(CGSize(width: 64, height: 48))
    paintCanvasRed(store)
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 32, height: 24))
    store.setFeather(2)
    XCTAssertEqual(store.copySelection(), .copied)
    let buffer = try copied()
    let centre = buffer.word(x: 16, y: 12) >> 24
    let edge = buffer.word(x: 0, y: 12) >> 24
    XCTAssertEqual(centre, 255, "solid well inside the ramp")
    XCTAssertLessThan(edge, centre, "the feather's ramp came with the copy")
    XCTAssertGreaterThan(edge, 0, "the ramp is a ramp, not a hard edge one pixel over")
  }

  // MARK: - Cut

  func testCutIsOneUndoStepAndClearsTheSelectedPixels() throws {
    let store = document()
    paintCanvasRed(store)
    let undoManager = UndoManager()
    store.undoManager = undoManager
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))

    XCTAssertEqual(store.cutSelection(), .cut)
    XCTAssertEqual(undoManager.undoActionName, "Cut", "copy and clear are one step")
    let after = try pixels(store)
    XCTAssertEqual(after.word(x: 16, y: 12), 0, "the selected pixels are gone")
    XCTAssertEqual(after.word(x: 1, y: 1), 0xFFFF_0000, "everything outside stayed")
    XCTAssertEqual(try copied().word(x: 8, y: 6), 0xFFFF_0000, "and they are on the pasteboard")

    undoManager.undo()
    XCTAssertEqual(
      try pixels(store).word(x: 16, y: 12), 0xFFFF_0000, "one undo puts them back")
  }

  func testCutWithoutASelectionAsksForOne() {
    let store = document()
    paintCanvasRed(store)
    XCTAssertEqual(store.cutSelection(), .needsSelection)
  }

  func testCutOnATextLayerIsRefused() throws {
    let store = document()
    XCTAssertTrue(
      store.addTextLayer("Words", fontSize: 12, color: .black, at: CGPoint(x: 4, y: 4)))
    _ = try selectBox(store, CGRect(x: 0, y: 0, width: 32, height: 24))
    XCTAssertEqual(store.cutSelection(), .textLayer, "text stays editable")
  }

  func testCopyOnATextLayerTakesItsPixels() throws {
    let store = document()
    XCTAssertTrue(
      store.addTextLayer("Words", fontSize: 12, color: .black, at: CGPoint(x: 4, y: 4)))
    XCTAssertEqual(store.copySelection(), .copied, "a picture of the words, as the desktop does")
  }

  // MARK: - Paste

  func testPasteAddsALayerAboveTheActiveOneAsOneStep() throws {
    let store = document()
    paintCanvasRed(store)
    let undoManager = UndoManager()
    store.undoManager = undoManager
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    XCTAssertEqual(store.copySelection(), .copied)
    let before = store.layers.count

    XCTAssertEqual(store.paste(), .pasted)
    XCTAssertEqual(store.layers.count, before + 1)
    XCTAssertEqual(undoManager.undoActionName, "Paste")
    XCTAssertEqual(store.activeLayer?.name, "Pasted", "and the new layer is the active one")

    undoManager.undo()
    XCTAssertEqual(store.layers.count, before, "one undo takes the whole paste back")
  }

  /// The round trip the feather weighting exists for: what Paste puts back is
  /// what Cut took away, in the place it was taken from.
  func testCutThenPasteRestoresThePixelsWhereTheyWere() throws {
    let store = document()
    paintCanvasRed(store)
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    XCTAssertEqual(store.cutSelection(), .cut)
    XCTAssertEqual(store.paste(), .pasted)

    let pasted = try pixels(store)
    XCTAssertEqual(pasted.word(x: 16, y: 12), 0xFFFF_0000, "back at the coordinates it left")
    XCTAssertEqual(pasted.word(x: 1, y: 1), 0, "and nowhere else on the new layer")
  }

  func testPasteFromAnotherAppLandsAtTheTopLeft() throws {
    let store = document()
    paintCanvasRed(store)
    _ = try selectBox(store, CGRect(x: 8, y: 6, width: 16, height: 12))
    XCTAssertEqual(store.copySelection(), .copied)

    // Something else writes to the pasteboard: the remembered origin is no
    // longer ours, so the image lands at the origin rather than at 8,6.
    let foreign = EditorStore.solidImage(size: CGSize(width: 6, height: 4), color: .green)
    UIPasteboard.general.image = foreign
    XCTAssertNil(store.ownedPasteOrigin, "another app's copy carries no origin of ours")

    XCTAssertEqual(store.paste(), .pasted)
    let pasted = try pixels(store)
    XCTAssertEqual(pasted.word(x: 1, y: 1), 0xFF00_FF00, "at the top-left")
    XCTAssertEqual(pasted.word(x: 20, y: 20), 0, "and only there")
  }

  func testPasteWithAnEmptyPasteboardDoesNothing() {
    let store = document()
    XCTAssertFalse(store.canPaste)
    XCTAssertEqual(store.paste(), .empty)
  }
}

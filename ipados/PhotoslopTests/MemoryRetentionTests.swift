// SPDX-License-Identifier: Apache-2.0
import PencilKit
import UIKit
import XCTest

@testable import PhotoslopIPad

/// What the editor keeps resident for a session, and what it lets go of.
///
/// The 2026-08-24 memory audit's three steady-state findings: every placed
/// layer kept its decoded original for the session (#350), one geometry undo
/// step pinned a whole document of old bitmaps (#351), and the composite
/// rasterised each layer's strokes at canvas size while change detection
/// serialised drawings on every refresh (#355). Each fix has a shape a test
/// can hold still: bytes retained, bytes pinned, or work not done.
@MainActor
final class MemoryRetentionTests: XCTestCase {
  /// A picture with per-pixel detail, so a resample is measurably lossy and a
  /// compressor cannot flatter itself.
  private func detailed(_ size: CGSize, seed: UInt8 = 0) -> UIImage {
    let width = Int(size.width), height = Int(size.height)
    var pixels = [UInt8](repeating: 0, count: width * height * 4)
    for y in 0..<height {
      for x in 0..<width {
        let index = (y * width + x) * 4
        pixels[index] = UInt8(truncatingIfNeeded: x * 7 &+ Int(seed))
        pixels[index + 1] = UInt8(truncatingIfNeeded: y * 5 &+ Int(seed))
        pixels[index + 2] = UInt8(truncatingIfNeeded: (x ^ y) * 3)
        pixels[index + 3] = 255
      }
    }
    let provider = CGDataProvider(data: Data(pixels) as CFData)!
    let cgImage = CGImage(
      width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
      bytesPerRow: width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
      bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
      provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
    return UIImage(cgImage: cgImage)
  }

  /// One user action's worth of undo registration. `UndoManager` closes its
  /// per-event group at the end of a run loop turn, and a test never turns
  /// one, so without explicit groups every step lands in a single group and
  /// the first `undo()` reverts them all at once.
  private func step(_ undo: UndoManager, _ body: () throws -> Void) rethrows {
    undo.beginUndoGrouping()
    defer { undo.endUndoGrouping() }
    try body()
  }

  private func flat(_ size: CGSize, color: UIColor) -> UIImage {
    EditorStore.solidImage(size: size, color: color)
  }

  /// Every pixel of an image in one known layout, for exact comparison.
  private func bytes(of image: UIImage) -> Data {
    guard let cgImage = image.cgImage else { return Data() }
    let width = cgImage.width, height = cgImage.height
    let context = CGContext(
      data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
      space: CGColorSpace(name: CGColorSpace.sRGB)!,
      bitmapInfo: CGBitmapInfo.byteOrder32Little.rawValue
        | CGImageAlphaInfo.premultipliedFirst.rawValue)!
    context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
    return Data(bytes: context.data!, count: width * height * 4)
  }

  private func stroke(from a: CGPoint, to b: CGPoint) -> PKStroke {
    let points = [a, b].map {
      PKStrokePoint(
        location: $0, timeOffset: 0, size: CGSize(width: 8, height: 8), opacity: 1, force: 1,
        azimuth: 0, altitude: .pi / 2)
    }
    return PKStroke(
      ink: PKInk(.pen, color: .black),
      path: PKStrokePath(controlPoints: points, creationDate: Date()))
  }

  private func pixel(_ image: UIImage, at point: CGPoint) -> (r: UInt8, g: UInt8, b: UInt8, a: UInt8)
  {
    let data = bytes(of: image)
    let index = (Int(point.y) * Int(image.size.width) + Int(point.x)) * 4
    // BGRA in memory for byteOrder32Little + premultipliedFirst.
    return (data[index + 2], data[index + 1], data[index], data[index + 3])
  }

  // MARK: - Sources are bytes, not bitmaps (#350)

  func testAPlacedLayerKeepsItsSourceAsCompressedBytes() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    let original = detailed(CGSize(width: 200, height: 200))
    let png = original.pngData()!
    _ = try store.addPlaceableLayer(name: "Photo", image: original, sourceData: png)

    guard let source = store.layers.last?.source else { return XCTFail("no source") }
    XCTAssertEqual(source.byteCount, png.count, "the bytes the import had are the source, as-is")
    XCTAssertLessThan(
      source.byteCount, 200 * 200 * 4,
      "and they are smaller than the decoded bitmap they used to be")
    XCTAssertEqual(source.pixelSize, CGSize(width: 200, height: 200))
  }

  func testTheRetainedSourceFootprintIsBounded() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    let original = detailed(CGSize(width: 200, height: 200))
    let png = original.pngData()!
    // Room for three sources, then the oldest has to go.
    store.sourceBudgetBytes = png.count * 3

    var ids: [UUID] = []
    for index in 0..<6 {
      ids.append(
        try store.addPlaceableLayer(name: "Photo \(index)", image: original, sourceData: png).id)
    }

    XCTAssertLessThanOrEqual(store.retainedSourceBytes, store.sourceBudgetBytes)
    XCTAssertEqual(store.layers.count, 7, "every layer is still there; only sources were shed")
    let kept = ids.filter { id in store.layers.first { $0.id == id }?.source != nil }
    XCTAssertEqual(kept, Array(ids.suffix(3)), "the newest sources are the ones kept")

    // A layer that lost its source still places, from its own pixels.
    store.placeLayer(ids[0], in: CGRect(x: 0, y: 0, width: 50, height: 50))
    XCTAssertEqual(store.layers.first { $0.id == ids[0] }?.placement?.width, 50)
  }

  func testReplacingALayerLargerAgainGivesTheFirstPlacementsPixels() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    let original = detailed(CGSize(width: 200, height: 200))
    let placed = try store.addPlaceableLayer(
      name: "Photo", image: original, sourceData: original.pngData()!)
    let first = bytes(of: store.layers.last!.image)

    store.placeLayer(placed.id, in: CGRect(x: 0, y: 0, width: 20, height: 20))
    XCTAssertNotEqual(bytes(of: store.layers.last!.image), first, "it really was resampled")
    store.placeLayer(placed.id, in: placed.rect)

    XCTAssertEqual(
      bytes(of: store.layers.last!.image), first,
      "back at its own size, the layer is the decoded source again, not a resample of a thumbnail")
  }

  func testALayerWithoutAFileGetsALosslessSource() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    let original = detailed(CGSize(width: 200, height: 200))
    let placed = try store.addPlaceableLayer(name: "Photo", image: original)
    let first = bytes(of: store.layers.last!.image)

    store.placeLayer(placed.id, in: CGRect(x: 0, y: 0, width: 20, height: 20))
    store.placeLayer(placed.id, in: placed.rect)

    XCTAssertEqual(bytes(of: store.layers.last!.image), first)
  }

  // MARK: - Undo records only what changed (#351)

  func testASingleLayerEditRecordsOnlyThatLayer() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 64, height: 64))
    store.addLayer()
    store.addLayer()
    let undo = UndoManager()
    store.undoManager = undo
    guard let active = store.activeLayerID else { return XCTFail("no active layer") }

    var drawing = PKDrawing()
    drawing.strokes = [stroke(from: CGPoint(x: 10, y: 10), to: CGPoint(x: 30, y: 30))]
    store.setDrawing(drawing)

    guard let record = store.latestUndoRecord else { return XCTFail("nothing registered") }
    XCTAssertEqual(record.order.count, 3, "the order names every layer")
    XCTAssertEqual(
      Array(record.changed.keys), [active],
      "but only the layer that changed is held")
    XCTAssertEqual(
      store.undoPinnedBytes, 0,
      "and it pins nothing: its bitmap is the one the document still has")
  }

  func testUndoAndRedoAcrossGeometryOperationsRoundTripPixelsExactly() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 64, height: 64))
    _ = try store.addPlaceableLayer(
      name: "Detail", image: detailed(CGSize(width: 64, height: 64), seed: 9))
    store.addLayer()
    let undo = UndoManager()
    undo.groupsByEvent = false
    store.undoManager = undo

    func snapshot() -> [Data] { store.layers.map { bytes(of: $0.image) } }
    let original = snapshot()
    let originalCanvas = store.canvasSize

    step(undo) { store.resizeCanvas(to: CGSize(width: 100, height: 80)) }
    let afterResize = snapshot()
    step(undo) { store.crop(to: CGRect(x: 10, y: 10, width: 40, height: 40)) }
    let afterCrop = snapshot()
    step(undo) { store.scaleDocument(to: CGSize(width: 30, height: 30)) }
    let afterScale = snapshot()
    // Every one of those replaced every layer, so every record packs.
    store.settleUndoPacking()

    undo.undo()
    XCTAssertEqual(snapshot(), afterCrop, "Resize Document undone, bit for bit")
    undo.undo()
    XCTAssertEqual(snapshot(), afterResize, "Crop undone")
    undo.undo()
    XCTAssertEqual(snapshot(), original, "Canvas Size undone")
    XCTAssertEqual(store.canvasSize, originalCanvas)

    undo.redo()
    undo.redo()
    undo.redo()
    XCTAssertEqual(snapshot(), afterScale, "and all the way forward again")
    XCTAssertEqual(store.canvasSize, CGSize(width: 30, height: 30))
  }

  func testGeometryUndoHistoryPinsFarLessThanTheDocumentsItReplaced() throws {
    let store = EditorStore()
    let size = CGSize(width: 512, height: 512)
    store.newDocument(size: size)
    store.addLayer()
    XCTAssertTrue(store.addTextLayer("Caption", fontSize: 48, color: .black, at: CGPoint(x: 40, y: 40)))
    _ = try store.addPlaceableLayer(name: "Photo", image: flat(CGSize(width: 300, height: 200), color: .blue))
    XCTAssertEqual(store.layers.count, 4)
    let undo = UndoManager()
    undo.groupsByEvent = false
    store.undoManager = undo

    let document = store.layers.reduce(0) { $0 + $1.imageBytes }
    step(undo) { store.resizeCanvas(to: CGSize(width: 600, height: 600)) }
    step(undo) { store.crop(to: CGRect(x: 20, y: 20, width: 560, height: 560)) }
    step(undo) { store.scaleDocument(to: CGSize(width: 500, height: 500)) }
    step(undo) { store.resizeCanvas(to: CGSize(width: 512, height: 512)) }
    step(undo) { store.scaleDocument(to: CGSize(width: 480, height: 480)) }
    store.settleUndoPacking()

    let pinned = store.undoPinnedBytes
    XCTAssertGreaterThan(pinned, 0, "something is held, or nothing could be undone")
    XCTAssertLessThan(
      pinned, document * 5 / 20,
      "five whole-document steps used to pin five documents (\(document * 5) bytes); "
        + "packed they pin \(pinned)")
    // Undo still works from the packed form, and gives the exact canvas back.
    for _ in 0..<5 { undo.undo() }
    XCTAssertEqual(store.canvasSize, size)
  }

  func testAStepThatDropsALayerStillBringsItBack() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 64, height: 64))
    let undo = UndoManager()
    undo.groupsByEvent = false
    store.undoManager = undo
    try step(undo) {
      _ = try store.addPlaceableLayer(name: "Photo", image: detailed(CGSize(width: 64, height: 64)))
    }
    let pixels = bytes(of: store.layers.last!.image)
    step(undo) { store.deleteActiveLayer() }
    XCTAssertEqual(store.layers.count, 1)

    undo.undo()
    XCTAssertEqual(store.layers.count, 2)
    XCTAssertEqual(bytes(of: store.layers.last!.image), pixels)
    XCTAssertEqual(store.activeLayerID, store.layers.last?.id)
  }

  // MARK: - Strokes: rendered where they are, compared without serialising (#355)

  func testAnUnchangedDrawingIsNotAChange() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 64, height: 64))
    let undo = UndoManager()
    store.undoManager = undo
    var drawing = PKDrawing()
    drawing.strokes = [stroke(from: CGPoint(x: 10, y: 10), to: CGPoint(x: 30, y: 30))]

    XCTAssertFalse(DrawingChange.differs(drawing, drawing))
    let same = PKDrawing(strokes: drawing.strokes)
    XCTAssertFalse(DrawingChange.differs(drawing, same), "equal strokes, separately held")
    var more = drawing
    more.strokes.append(stroke(from: CGPoint(x: 40, y: 40), to: CGPoint(x: 50, y: 50)))
    XCTAssertTrue(DrawingChange.differs(drawing, more))
    let moved = PKDrawing(strokes: drawing.strokes).transformed(
      using: CGAffineTransform(translationX: 5, y: 5))
    XCTAssertTrue(DrawingChange.differs(drawing, moved), "a moved stroke is a change")

    let key = store.setDrawing(drawing)
    XCTAssertTrue(undo.canUndo)
    XCTAssertEqual(key, store.activeDrawingKey)
    let steps = undo.canUndo
    XCTAssertEqual(
      store.setDrawing(same), key,
      "reporting the same strokes again hands back the key the canvas already has")
    XCTAssertEqual(undo.canUndo, steps)
    undo.undo()
    XCTAssertTrue(store.activeLayer?.drawing.strokes.isEmpty ?? false)
  }

  func testDrawingKeysTellRevisionsAndLayersApart() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 64, height: 64))
    let background = store.activeDrawingKey
    XCTAssertNotEqual(background, .empty)
    XCTAssertEqual(background, store.activeDrawingKey, "asking twice is the same answer")

    var drawing = PKDrawing()
    drawing.strokes = [stroke(from: CGPoint(x: 10, y: 10), to: CGPoint(x: 30, y: 30))]
    store.setDrawing(drawing)
    let drawn = store.activeDrawingKey
    XCTAssertNotEqual(drawn, background, "a new drawing is a new revision")
    XCTAssertEqual(drawn.layer, background.layer, "of the same layer")

    store.addLayer()
    XCTAssertNotEqual(store.activeDrawingKey.layer, drawn.layer, "another layer, another key")
    store.activeLayerID = nil
    XCTAssertEqual(store.activeDrawingKey, .empty)
  }

  func testStrokesCompositeWhereTheyAreAndNowhereElse() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    var drawing = PKDrawing()
    drawing.strokes = [stroke(from: CGPoint(x: 300, y: 300), to: CGPoint(x: 340, y: 300))]
    store.setDrawing(drawing)

    let composite = EditorStore.render(layers: store.layers, size: store.canvasSize)
    XCTAssertEqual(composite.size, CGSize(width: 400, height: 400))
    XCTAssertLessThan(pixel(composite, at: CGPoint(x: 320, y: 300)).r, 128, "ink where the stroke is")
    XCTAssertEqual(pixel(composite, at: CGPoint(x: 50, y: 50)).r, 255, "white where it is not")

    // Strokes entirely off the canvas have nothing to rasterise and must not
    // trip over an empty box.
    var outside = PKDrawing()
    outside.strokes = [stroke(from: CGPoint(x: 900, y: 900), to: CGPoint(x: 950, y: 950))]
    store.setDrawing(outside)
    let untouched = EditorStore.render(layers: store.layers, size: store.canvasSize)
    XCTAssertEqual(pixel(untouched, at: CGPoint(x: 320, y: 300)).r, 255)
  }
}

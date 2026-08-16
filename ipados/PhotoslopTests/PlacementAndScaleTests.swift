// SPDX-License-Identifier: Apache-2.0
import PencilKit
import UIKit
import XCTest

@testable import PhotoslopIPad

/// The three operations that change a document's size, and the one that changes
/// a layer's.
///
/// These are easy to confuse and expensive to get wrong, which is exactly what
/// happened: crop took a region nobody chose (#260), a second crop used the
/// first one's geometry (#268), and an imported layer was stretched to the
/// whole canvas with no way back (#266). The arithmetic is testable without a
/// screen, so it is tested without one.
@MainActor
final class PlacementAndScaleTests: XCTestCase {
  private func image(_ size: CGSize, color: UIColor = .red) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: size, format: format).image { context in
      color.setFill()
      context.fill(CGRect(origin: .zero, size: size))
    }
  }

  /// The colour at a point of the composited document, for asking where the
  /// pixels actually went rather than where the rectangle said they would.
  private func pixel(_ image: UIImage, at point: CGPoint) -> (r: UInt8, g: UInt8, b: UInt8, a: UInt8)
  {
    guard let cgImage = image.cgImage else { return (0, 0, 0, 0) }
    var data = [UInt8](repeating: 0, count: 4)
    let space = CGColorSpaceCreateDeviceRGB()
    guard
      let context = CGContext(
        data: &data, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4, space: space,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    else { return (0, 0, 0, 0) }
    // Core Graphics puts the origin at the bottom left and UIImage coordinates
    // put it at the top left, so the row has to be flipped or every sample is
    // taken from the mirror image of the point asked for.
    let flippedY = image.size.height - point.y - 1
    context.draw(
      cgImage,
      in: CGRect(x: -point.x, y: -flippedY, width: image.size.width, height: image.size.height))
    return (data[0], data[1], data[2], data[3])
  }

  // MARK: - Resize Document (#269)

  func testResizeDocumentScalesTheCanvasAndEveryLayer() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 800, height: 600))
    store.scaleDocument(to: CGSize(width: 400, height: 300))

    XCTAssertEqual(store.canvasSize, CGSize(width: 400, height: 300))
    for layer in store.layers {
      XCTAssertEqual(
        layer.image.size, CGSize(width: 400, height: 300),
        "every layer image has to match the canvas exactly or the project will not encode")
    }
  }

  /// The distinction the whole issue turned on: Canvas Size pads, Resize
  /// scales. Same target size, different picture.
  func testResizeDocumentScalesContentWhereCanvasSizePadsIt() {
    let scaled = EditorStore()
    scaled.newDocument(size: CGSize(width: 200, height: 200))
    guard let id = scaled.activeLayerID else { return XCTFail("no active layer") }
    scaled.placeLayer(id, in: CGRect(x: 0, y: 0, width: 200, height: 200))
    scaled.scaleDocument(to: CGSize(width: 400, height: 400))

    let padded = EditorStore()
    padded.newDocument(size: CGSize(width: 200, height: 200))
    guard let paddedID = padded.activeLayerID else { return XCTFail("no active layer") }
    padded.placeLayer(paddedID, in: CGRect(x: 0, y: 0, width: 200, height: 200))
    padded.resizeCanvas(to: CGSize(width: 400, height: 400))

    XCTAssertEqual(scaled.canvasSize, padded.canvasSize, "both reach the same canvas")
    // Near the corner, the scaled document still has picture; the padded one has
    // the border that was added around it.
    let scaledCorner = pixel(scaled.layers[0].image, at: CGPoint(x: 380, y: 380))
    let paddedCorner = pixel(padded.layers[0].image, at: CGPoint(x: 380, y: 380))
    XCTAssertGreaterThan(
      Int(scaledCorner.a), Int(paddedCorner.a),
      "scaling fills the new corner with picture; padding leaves it empty")
  }

  func testResizeDocumentCarriesStrokesAndTextWithThePixels() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    XCTAssertTrue(store.addTextLayer("Hi", fontSize: 40, color: .black, at: CGPoint(x: 100, y: 200)))
    guard let before = store.layers.last?.text else { return XCTFail("no text layer") }

    store.scaleDocument(to: CGSize(width: 200, height: 200))

    guard let after = store.layers.last?.text else { return XCTFail("text layer lost") }
    XCTAssertEqual(after.x, before.x / 2, accuracy: 0.001, "the anchor scales with the canvas")
    XCTAssertEqual(after.y, before.y / 2, accuracy: 0.001)
    XCTAssertEqual(
      after.fontSize, before.fontSize / 2, accuracy: 0.001,
      "type scales with the picture, or a resized document reflows")
  }

  func testResizeDocumentIsOneUndoStep() {
    let store = EditorStore()
    let undo = UndoManager()
    store.newDocument(size: CGSize(width: 400, height: 400))
    // Attached after the document exists: UndoManager groups by run loop, so a
    // manager present for both mutations would undo them together and the test
    // would be measuring its own setup rather than the resize.
    store.undoManager = undo
    store.scaleDocument(to: CGSize(width: 200, height: 200))
    XCTAssertEqual(store.canvasSize, CGSize(width: 200, height: 200))
    undo.undo()
    XCTAssertEqual(store.canvasSize, CGSize(width: 400, height: 400))
  }

  func testResizeDocumentRefusesAnImpossibleCanvas() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    store.scaleDocument(to: CGSize(width: 0, height: 400))
    XCTAssertEqual(store.canvasSize, CGSize(width: 400, height: 400))
  }

  // MARK: - Placing a layer (#266, #262)

  func testImportedLayerKeepsItsOwnSizeAndLeavesTheCanvasAlone() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 1000, height: 1000))
    let placed = try store.addPlaceableLayer(name: "Photo", image: image(CGSize(width: 200, height: 100)))

    XCTAssertEqual(
      store.canvasSize, CGSize(width: 1000, height: 1000),
      "importing a layer must never resize the document")
    XCTAssertEqual(
      placed.rect, CGRect(x: 400, y: 450, width: 200, height: 100),
      "the image arrives at its own size, centred — not stretched to the canvas")
    XCTAssertEqual(store.layers.last?.source?.size, CGSize(width: 200, height: 100))
  }

  /// The bug in the user's words: "importing an image into a layer is still
  /// scaling that layer to the entire canvas".
  func testAPlaceableImportIsNotStretchedToTheCanvas() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    _ = try store.addPlaceableLayer(name: "Photo", image: image(CGSize(width: 40, height: 40)))
    guard let layer = store.layers.last else { return XCTFail("no layer") }

    XCTAssertEqual(pixel(layer.image, at: CGPoint(x: 200, y: 200)).a, 255, "the picture is centred")
    XCTAssertEqual(
      pixel(layer.image, at: CGPoint(x: 10, y: 10)).a, 0,
      "and the rest of the canvas is left empty rather than filled with a stretched copy")
  }

  func testPlacingALayerPutsThePixelsWhereTheBoxSays() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    let placed = try store.addPlaceableLayer(name: "Photo", image: image(CGSize(width: 40, height: 40)))
    store.placeLayer(placed.id, in: CGRect(x: 0, y: 0, width: 100, height: 100))

    guard let layer = store.layers.last else { return XCTFail("no layer") }
    XCTAssertEqual(layer.placement, CGRect(x: 0, y: 0, width: 100, height: 100))
    XCTAssertEqual(pixel(layer.image, at: CGPoint(x: 50, y: 50)).a, 255, "inside the box")
    XCTAssertEqual(pixel(layer.image, at: CGPoint(x: 150, y: 150)).a, 0, "outside it")
  }

  /// Repeated resizes must go back to the original pixels, not to the last
  /// resample. Scaling down to a thumbnail and back up should not leave the
  /// picture at thumbnail quality.
  func testRepeatedResizesResampleFromTheOriginalPixels() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    let original = image(CGSize(width: 200, height: 200))
    let placed = try store.addPlaceableLayer(name: "Photo", image: original)

    store.placeLayer(placed.id, in: CGRect(x: 0, y: 0, width: 20, height: 20))
    store.placeLayer(placed.id, in: CGRect(x: 0, y: 0, width: 200, height: 200))

    XCTAssertEqual(
      store.layers.last?.source?.size, CGSize(width: 200, height: 200),
      "the source stays the original, so the round trip does not compound losses")
  }

  func testALayerFromAFileHasNoSourceAndStillResizes() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    guard let id = store.activeLayerID else { return XCTFail("no active layer") }
    XCTAssertNil(store.layers.first?.source, "a restored layer has no separate source")
    XCTAssertEqual(
      store.placementRect(for: id), CGRect(x: 0, y: 0, width: 400, height: 400),
      "so its box opens on the whole canvas")

    store.placeLayer(id, in: CGRect(x: 100, y: 100, width: 100, height: 100))
    XCTAssertEqual(store.layers.first?.placement, CGRect(x: 100, y: 100, width: 100, height: 100))
    XCTAssertNotNil(store.layers.first?.source, "and it gains one, so the next resize is clean")
  }

  func testPlacingALayerIsOneUndoStep() throws {
    let store = EditorStore()
    let undo = UndoManager()
    store.newDocument(size: CGSize(width: 400, height: 400))
    let placed = try store.addPlaceableLayer(name: "Photo", image: image(CGSize(width: 40, height: 40)))
    store.undoManager = undo
    store.placeLayer(placed.id, in: CGRect(x: 0, y: 0, width: 200, height: 200))
    XCTAssertEqual(store.layers.last?.placement?.width, 200)
    undo.undo()
    XCTAssertEqual(store.layers.last?.placement?.width, 40, "back to where it landed")
  }

  // MARK: - Fitting text (#261)

  func testFittingTextScalesTheTypeToSpanTheBox() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 800, height: 600))
    XCTAssertTrue(
      store.addTextLayer("Caption", fontSize: 20, color: .black, at: CGPoint(x: 10, y: 10)))
    guard let id = store.activeLayerID, let opened = store.textRect(for: id) else {
      return XCTFail("no text box")
    }
    XCTAssertGreaterThan(opened.width, 0, "the box opens around the words that are there")

    let target = CGRect(x: 100, y: 100, width: opened.width * 2, height: opened.height * 2)
    XCTAssertTrue(store.fitTextLayer(id, to: target))

    guard let content = store.layers.last?.text else { return XCTFail("text lost") }
    XCTAssertEqual(content.fontSize, 40, accuracy: 1.5, "doubling the box doubles the type")
    XCTAssertEqual(content.x, 100, accuracy: 0.001, "and the anchor moves to the box")
    XCTAssertEqual(content.y, 100, accuracy: 0.001)
  }

  /// The box is a container, so an off-shape box scales the type by whichever
  /// axis runs out first — a box three times as wide but only twice as tall
  /// doubles the words rather than tripling them into the ceiling.
  func testFittingTextIntoAnOffShapeBoxIsLimitedByTheTightAxis() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 800, height: 600))
    XCTAssertTrue(
      store.addTextLayer("Caption", fontSize: 20, color: .black, at: CGPoint(x: 10, y: 10)))
    guard let id = store.activeLayerID, let opened = store.textRect(for: id) else {
      return XCTFail("no text box")
    }

    let wide = CGRect(x: 50, y: 50, width: opened.width * 3, height: opened.height * 2)
    XCTAssertTrue(store.fitTextLayer(id, to: wide))
    guard let content = store.layers.last?.text else { return XCTFail("text lost") }
    XCTAssertEqual(
      content.fontSize, 40, accuracy: 1.5,
      "the height ran out at 2x, so 2x is the fit — width had room to spare")
  }

  func testFittingRefusesALayerThatIsNotText() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 400))
    let placed = try store.addPlaceableLayer(name: "Photo", image: image(CGSize(width: 40, height: 40)))
    XCTAssertFalse(store.fitTextLayer(placed.id, to: CGRect(x: 0, y: 0, width: 100, height: 100)))
    XCTAssertNil(store.textRect(for: placed.id))
  }

  // MARK: - The geometry underneath

  /// A crop cannot leave the canvas; a layer being placed can. Same arithmetic,
  /// different bounds — which is why the bounds are a parameter.
  func testPlacementMayLeaveTheCanvasAndACropMayNot() {
    let canvas = CGSize(width: 100, height: 100)
    let start = CGRect(x: 10, y: 10, width: 40, height: 40)

    let cropped = CropGeometry.resized(
      start, handle: .interior, translation: CGSize(width: -100, height: 0),
      canvas: canvas, aspect: .free)
    XCTAssertEqual(cropped.minX, 0, "a crop stops at the edge of the picture")

    let placed = CropGeometry.resized(
      start, handle: .interior, translation: CGSize(width: -100, height: 0),
      bounds: CGRect(x: -100, y: -100, width: 300, height: 300), ratio: nil)
    XCTAssertEqual(placed.minX, -90, "a placed layer may hang over it")
  }

  /// Picking the handle is arithmetic now that the box is dragged from UIKit,
  /// so it is tested as arithmetic.
  func testATouchPicksTheHandleItLandedOn() {
    let rect = CGRect(x: 100, y: 100, width: 200, height: 200)

    XCTAssertEqual(
      CropGeometry.handle(at: CGPoint(x: 300, y: 300), in: rect, tolerance: 44), .bottomRight)
    XCTAssertEqual(
      CropGeometry.handle(at: CGPoint(x: 100, y: 100), in: rect, tolerance: 44), .topLeft)
    XCTAssertEqual(
      CropGeometry.handle(at: CGPoint(x: 200, y: 100), in: rect, tolerance: 44), .top,
      "the middle of an edge is that edge, not a corner")
    XCTAssertEqual(
      CropGeometry.handle(at: CGPoint(x: 200, y: 200), in: rect, tolerance: 44), .interior,
      "the middle moves the whole rectangle")
    XCTAssertNil(
      CropGeometry.handle(at: CGPoint(x: 600, y: 600), in: rect, tolerance: 44),
      "a touch nowhere near the box grabs nothing")
  }

  /// A corner is the more specific intent, so it wins where both are in range.
  func testACornerBeatsAnEdgeWhenBothAreInReach() {
    let rect = CGRect(x: 0, y: 0, width: 60, height: 60)
    XCTAssertEqual(
      CropGeometry.handle(at: CGPoint(x: 58, y: 58), in: rect, tolerance: 44), .bottomRight)
  }

  /// A caption's box is shorter than a fingertip, and it still has to be
  /// movable: with the full 44pt radius inside the rectangle, every interior
  /// point was "near" a corner or an edge, so the box could only ever be
  /// resized — the fit-text bug, measured on device. Inside, the handles
  /// compete with a radius scaled to the box; outside, the full radius stays,
  /// so the same small box's handles remain easy to take hold of.
  func testTheMiddleOfASmallBoxIsStillItsInterior() {
    // The measured shape of a fitted caption: 497 × 58 document pixels, with a
    // zoomed-out touch radius far taller than the box itself.
    let rect = CGRect(x: 1024, y: 768, width: 497, height: 58)
    XCTAssertEqual(
      CropGeometry.handle(at: CGPoint(x: rect.midX, y: rect.midY), in: rect, tolerance: 123),
      .interior,
      "the middle of a small box must move it, not resize it")
    XCTAssertEqual(
      CropGeometry.handle(
        at: CGPoint(x: rect.maxX + 30, y: rect.maxY + 30), in: rect, tolerance: 123),
      .bottomRight,
      "outside the box the full touch radius still grabs the corner")
  }

  func testConstrainedProportionsHoldTheShape() {
    let bounds = CGRect(x: -400, y: -400, width: 1200, height: 1200)
    let start = CGRect(x: 0, y: 0, width: 200, height: 100)
    let resized = CropGeometry.resized(
      start, handle: .bottomRight, translation: CGSize(width: 200, height: 0),
      bounds: bounds, ratio: 2)
    XCTAssertEqual(
      resized.width / resized.height, 2, accuracy: 0.05,
      "dragging one axis with proportions locked moves the other")
  }
}

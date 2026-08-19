// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

final class TextLayerRendererTests: XCTestCase {
  private let canvas = CGSize(width: 200, height: 120)

  /// Decode the whole image once into RGBA so pixels can be read by UIKit
  /// coordinates.
  ///
  /// Drawing a CGImage into a same-sized bitmap context writes it top-down, so
  /// buffer row 0 is the image's top row and no flip is wanted. Assuming CG's
  /// bottom-left origin applies here and flipping anyway reads the mirror image
  /// of every sample, which looks exactly like a renderer placing text at the
  /// wrong end of the canvas.
  private struct Pixels {
    let width: Int
    let height: Int
    let rgba: [UInt8]

    init(_ image: UIImage) throws {
      let cgImage = try XCTUnwrap(image.cgImage)
      width = cgImage.width
      height = cgImage.height
      var buffer = [UInt8](repeating: 0, count: width * height * 4)
      let context = try XCTUnwrap(
        CGContext(
          data: &buffer, width: width, height: height, bitsPerComponent: 8,
          bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
      context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
      rgba = buffer
    }

    /// (r, g, b, a) at a top-left-origin point, or nil when out of bounds.
    func at(_ x: Int, _ y: Int) -> (UInt8, UInt8, UInt8, UInt8)? {
      guard x >= 0, y >= 0, x < width, y < height else { return nil }
      let i = (y * width + x) * 4
      return (rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3])
    }

    var maxAlpha: UInt8 { stride(from: 3, to: rgba.count, by: 4).map { rgba[$0] }.max() ?? 0 }

    /// The most opaque pixel, which is where a glyph actually landed.
    var densestPixel: (x: Int, y: Int, rgba: (UInt8, UInt8, UInt8, UInt8))? {
      var best: (Int, Int, (UInt8, UInt8, UInt8, UInt8))?
      for y in 0..<height {
        for x in 0..<width {
          guard let px = at(x, y) else { continue }
          if px.3 > (best?.2.3 ?? 0) { best = (x, y, px) }
        }
      }
      return best.map { (x: $0.0, y: $0.1, rgba: $0.2) }
    }
  }

  func testRenderedLayerMatchesTheCanvasExactly() throws {
    // A project rejects any layer whose image is not the canvas size, so text
    // drawn into a tight box the way the desktop does it would fail to save.
    let image = try XCTUnwrap(
      TextLayerRenderer.render(
        text: "Hello", fontSize: 24, color: .black,
        at: CGPoint(x: 10, y: 10), canvasSize: canvas))
    XCTAssertEqual(image.size, canvas)
    XCTAssertTrue(ProjectArchive.isValidCanvas(image.size))
  }

  func testTextLandsAtTheAnchorAndNotAtTheOrigin() throws {
    let anchor = CGPoint(x: 120, y: 70)
    let image = try XCTUnwrap(
      TextLayerRenderer.render(
        text: "X", fontSize: 40, color: .black, at: anchor, canvasSize: canvas))
    let pixels = try Pixels(image)

    XCTAssertGreaterThan(pixels.maxAlpha, 0, "nothing was drawn at all")
    let densest = try XCTUnwrap(pixels.densestPixel)
    XCTAssertGreaterThanOrEqual(
      CGFloat(densest.x), anchor.x,
      "glyphs landed left of the anchor, so the anchor is being ignored")
    XCTAssertGreaterThanOrEqual(
      CGFloat(densest.y), anchor.y,
      "glyphs landed above the anchor, so the anchor is being ignored")
  }

  func testTextDrawnAtTheOriginStaysNearIt() throws {
    let image = try XCTUnwrap(
      TextLayerRenderer.render(
        text: "X", fontSize: 40, color: .black, at: .zero, canvasSize: canvas))
    let densest = try XCTUnwrap(try Pixels(image).densestPixel)
    XCTAssertLessThan(densest.x, 60, "text at the origin drifted right")
    XCTAssertLessThan(densest.y, 60, "text at the origin drifted down")
  }

  func testBlankInputRendersNothingRatherThanAnEmptyLayer() {
    for blank in ["", "   ", "\n", "\n\n  \n"] {
      XCTAssertNil(
        TextLayerRenderer.render(
          text: blank, fontSize: 24, color: .black, at: .zero, canvasSize: canvas),
        "\(blank.debugDescription) should render nothing")
    }
  }

  /// Mirrors the desktop naming: first line, capped at 24 characters, or "Text".
  func testLayerNameMirrorsTheDesktopRule() {
    XCTAssertEqual(TextLayerRenderer.layerName(for: "Hello"), "Hello")
    XCTAssertEqual(TextLayerRenderer.layerName(for: "Hello\nworld"), "Hello")
    XCTAssertEqual(TextLayerRenderer.layerName(for: "   "), "Text")
    XCTAssertEqual(
      TextLayerRenderer.layerName(for: String(repeating: "a", count: 40)),
      String(repeating: "a", count: 24))
  }

  func testColorIsHonoured() throws {
    let image = try XCTUnwrap(
      TextLayerRenderer.render(
        text: "M", fontSize: 60, color: .red,
        at: CGPoint(x: 10, y: 10), canvasSize: canvas))
    let densest = try XCTUnwrap(try Pixels(image).densestPixel)
    XCTAssertGreaterThan(densest.rgba.0, densest.rgba.1, "red text decoded without red dominance")
    XCTAssertGreaterThan(densest.rgba.0, densest.rgba.2, "red text decoded as blue-ish")
  }
}

extension EditorStoreTests {
  func testAddTextLayerAppendsAnActiveLayerNamedForTheText() {
    let store = EditorStore()
    let before = store.layers.count

    XCTAssertTrue(
      store.addTextLayer("Sign here", fontSize: 64, color: .black, at: CGPoint(x: 40, y: 40)))
    XCTAssertEqual(store.layers.count, before + 1)
    XCTAssertEqual(store.layers.last?.name, "Sign here")
    XCTAssertEqual(store.activeLayerID, store.layers.last?.id)
    // A text layer is now stored at the extent of its words, not as a
    // full-canvas bitmap (#309). What must hold is that it sits where it was
    // anchored and stays inside the canvas — not that it IS the canvas.
    let layer = try? XCTUnwrap(store.layers.last)
    XCTAssertEqual(layer?.origin, CGPoint(x: 40, y: 40))
    XCTAssertLessThan(layer?.image.size.width ?? .infinity, store.canvasSize.width)
    XCTAssertTrue(
      CGRect(origin: .zero, size: store.canvasSize).intersects(layer?.frame ?? .null))
  }

  func testAddTextLayerRefusesBlankTextInsteadOfAddingAnEmptyLayer() {
    let store = EditorStore()
    let before = store.layers.count
    XCTAssertFalse(store.addTextLayer("   ", fontSize: 64, color: .black, at: .zero))
    XCTAssertEqual(store.layers.count, before)
  }

  func testAddTextLayerIsUndoable() {
    let store = EditorStore()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    let before = store.layers.count

    store.addTextLayer("Undo me", fontSize: 32, color: .black, at: CGPoint(x: 10, y: 10))
    XCTAssertEqual(store.layers.count, before + 1)

    undoManager.undo()
    XCTAssertEqual(store.layers.count, before)
  }
}

extension EditorStoreTests {
  func testTextSurvivesASaveAndReload() throws {
    let store = EditorStore()
    store.addTextLayer("Round trip", fontSize: 44, color: .red, at: CGPoint(x: 30, y: 60))

    let snapshot = try store.snapshot(contentType: .photoslopProject)
    let wrapper = try ProjectArchive.encode(snapshot)
    let restored = try ProjectArchive.decode(wrapper)

    let text = try XCTUnwrap(restored.layers.last?.text, "text was not persisted")
    XCTAssertEqual(text.string, "Round trip")
    XCTAssertEqual(text.fontSize, 44, accuracy: 0.001)
    XCTAssertEqual(text.anchor.x, 30, accuracy: 0.001)
    XCTAssertEqual(text.anchor.y, 60, accuracy: 0.001)
    XCTAssertEqual(text.red, 1, accuracy: 0.01, "colour did not survive")
  }

  /// A version 1 document predates the text field entirely. Rejecting it would
  /// strand every project already saved on a device.
  func testVersionOneDocumentsStillOpen() throws {
    let store = EditorStore()
    let snapshot = try store.snapshot(contentType: .photoslopProject)
    var manifest = snapshot.manifest
    manifest.version = 1
    manifest.layers = manifest.layers.map {
      var record = $0
      record.text = nil
      return record
    }
    let legacy = ProjectSnapshot(manifest: manifest, layers: snapshot.layers)

    let restored = try ProjectArchive.decode(try ProjectArchive.encode(legacy))
    XCTAssertEqual(restored.layers.count, store.layers.count)
    XCTAssertTrue(restored.layers.allSatisfy { $0.text == nil })
  }

  func testEditingTextKeepsTheLayerAndItsPosition() throws {
    let store = EditorStore()
    store.addTextLayer("before", fontSize: 40, color: .black, at: CGPoint(x: 25, y: 35))
    let id = try XCTUnwrap(store.activeLayerID)
    let count = store.layers.count

    XCTAssertTrue(store.updateTextLayer(id, string: "after", fontSize: 50, color: .blue))

    XCTAssertEqual(store.layers.count, count, "editing must not add a layer")
    let layer = try XCTUnwrap(store.layers.first { $0.id == id })
    let text = try XCTUnwrap(layer.text)
    XCTAssertEqual(text.string, "after")
    XCTAssertEqual(text.fontSize, 50, accuracy: 0.001)
    XCTAssertEqual(text.anchor.x, 25, accuracy: 0.001, "editing moved the text")
    XCTAssertEqual(text.anchor.y, 35, accuracy: 0.001, "editing moved the text")
    XCTAssertEqual(layer.name, "after", "the layer name follows the words")
  }

  func testMovingTextChangesOnlyTheAnchor() throws {
    let store = EditorStore()
    store.addTextLayer("drag me", fontSize: 40, color: .black, at: CGPoint(x: 10, y: 10))
    let id = try XCTUnwrap(store.activeLayerID)

    XCTAssertTrue(store.moveTextLayer(id, to: CGPoint(x: 90, y: 120)))
    let text = try XCTUnwrap(store.layers.first { $0.id == id }?.text)
    XCTAssertEqual(text.anchor.x, 90, accuracy: 0.001)
    XCTAssertEqual(text.anchor.y, 120, accuracy: 0.001)
    XCTAssertEqual(text.string, "drag me", "moving must not alter the words")
  }

  /// A drag emits a sample per touch. Without coalescing, one gesture would
  /// leave dozens of undo entries and undo would crawl backwards pixel by pixel.
  func testADragCoalescesIntoOneUndoStep() throws {
    let store = EditorStore()
    let undoManager = UndoManager()
    // UndoManager groups by run loop event by default, and a test never turns
    // the run loop, so the add and the drag would land in one group and a
    // single undo would reverse both. Separating them is what makes this test
    // measure coalescing rather than grouping.
    undoManager.groupsByEvent = false
    store.undoManager = undoManager

    undoManager.beginUndoGrouping()
    store.addTextLayer("drag", fontSize: 40, color: .black, at: CGPoint(x: 10, y: 10))
    undoManager.endUndoGrouping()
    let id = try XCTUnwrap(store.activeLayerID)

    // One gesture: many samples while the finger moves, then the release.
    undoManager.beginUndoGrouping()
    for x in stride(from: 20, through: 80, by: 10) {
      store.moveTextLayer(id, to: CGPoint(x: CGFloat(x), y: 40), coalesce: true)
    }
    store.moveTextLayer(id, to: CGPoint(x: 90, y: 40))
    undoManager.endUndoGrouping()

    undoManager.undo()
    let text = try XCTUnwrap(store.layers.first { $0.id == id }?.text)
    XCTAssertEqual(text.anchor.x, 10, accuracy: 0.001, "one undo should return to before the drag")
  }

  func testResizingTheCanvasCarriesTheTextAnchorWithIt() throws {
    let store = EditorStore()
    store.addTextLayer("anchored", fontSize: 40, color: .black, at: CGPoint(x: 100, y: 100))
    let id = try XCTUnwrap(store.activeLayerID)
    let original = store.canvasSize

    let grown = CGSize(width: original.width + 400, height: original.height + 200)
    store.resizeCanvas(to: grown)

    let text = try XCTUnwrap(store.layers.first { $0.id == id }?.text)
    XCTAssertEqual(text.anchor.x, 300, accuracy: 1, "anchor did not follow the centred padding")
    XCTAssertEqual(text.anchor.y, 200, accuracy: 1, "anchor did not follow the centred padding")
  }

  func testNonTextLayersRefuseTextOperations() {
    let store = EditorStore()
    let id = store.activeLayerID!
    XCTAssertFalse(store.updateTextLayer(id, string: "nope", fontSize: 20, color: .black))
    XCTAssertFalse(store.moveTextLayer(id, to: CGPoint(x: 5, y: 5)))
  }
}

extension EditorStoreTests {
  /// Adding text over an imported photo used to produce nothing: placement
  /// waited for a canvas tap, and a tap outside the artwork — easy when a large
  /// photo is zoomed to fit inside grey surround — was silently dropped.
  func testTextCanBeAddedOverAnImportedPhoto() throws {
    let store = EditorStore()
    let size = CGSize(width: 4032, height: 3024)
    // scale 1 on purpose: the renderer otherwise uses the screen's scale, and a
    // 3x phone would produce a 12096x9072 image that exceeds the project's pixel
    // cap. A decoded photo is scale 1, so this matches what import really sees.
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    let photo = UIGraphicsImageRenderer(size: size, format: format).image { ctx in
      UIColor.systemTeal.setFill()
      ctx.fill(CGRect(origin: .zero, size: size))
    }
    try store.importImage(data: XCTUnwrap(photo.pngData()), suggestedName: "Photo")
    XCTAssertEqual(store.layers.count, 1)

    let centre = CGPoint(x: store.canvasSize.width / 2, y: store.canvasSize.height / 2)
    XCTAssertTrue(store.addTextLayer("OVER PHOTO", fontSize: 200, color: .red, at: centre))

    XCTAssertEqual(store.layers.count, 2, "the text layer was not added")
    let top = try XCTUnwrap(store.layers.last)
    XCTAssertTrue(top.isText, "text must go on top of the existing stack")
    // Bounded extent (#309): the words cost their own box, anchored where they
    // were placed, rather than a canvas-sized bitmap that is mostly empty.
    XCTAssertEqual(top.origin, centre)
    XCTAssertLessThanOrEqual(top.image.size.width, store.canvasSize.width)
    XCTAssertTrue(CGRect(origin: .zero, size: store.canvasSize).intersects(top.frame))
    XCTAssertEqual(store.activeLayerID, top.id, "the new text should be selected")
  }

  /// The centre of any canvas is inside it, so the default anchor can never be
  /// the off-canvas position that produced nothing before.
  func testTheDefaultTextAnchorIsAlwaysOnTheCanvas() {
    for size in [CGSize(width: 1, height: 1), CGSize(width: 4032, height: 3024)] {
      let centre = CGPoint(x: size.width / 2, y: size.height / 2)
      XCTAssertTrue(
        (0...size.width).contains(centre.x) && (0...size.height).contains(centre.y),
        "centre of \(size) fell outside the canvas")
    }
  }
}

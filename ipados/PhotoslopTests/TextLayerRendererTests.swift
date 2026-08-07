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
    XCTAssertEqual(store.layers.last?.image.size, store.canvasSize)
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

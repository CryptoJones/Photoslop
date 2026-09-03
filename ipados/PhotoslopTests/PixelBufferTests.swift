// SPDX-License-Identifier: Apache-2.0
import PencilKit
import UIKit
import XCTest

@testable import PhotoslopIPad

/// The pixel seam (#324): a layer's pixels out as premultiplied ARGB32 words,
/// back in as a layer image, byte for byte, and one undo step per operation.
@MainActor
final class PixelBufferTests: XCTestCase {
  /// A deterministic 7x5 buffer with transparent, opaque and half-covered
  /// pixels, every one honouring the premultiplied invariant.
  private func sampleBuffer() -> PixelBuffer {
    var buffer = PixelBuffer(width: 7, height: 5)
    for y in 0..<buffer.height {
      for x in 0..<buffer.width {
        let a = [0, 255, 128, 17, 200][y]
        let word = PixelBuffer.premultipliedWord(
          r: (x * 37) % 256, g: (y * 91 + x) % 256, b: (x * y * 13) % 256, a: a)
        buffer.setWord(word, x: x, y: y)
      }
    }
    return buffer
  }

  func testByteOrderIsLittleEndianARGB32LikeTheDesktop() {
    // 0xAARRGGBB as a word is B, G, R, A in memory — Qt's ARGB32 on x86/arm.
    let word = PixelBuffer.premultipliedWord(r: 0x11, g: 0x22, b: 0x33, a: 0xFF)
    XCTAssertEqual(word, 0xFF11_2233)
    let bytes = withUnsafeBytes(of: word.littleEndian) { Array($0) }
    XCTAssertEqual(bytes, [0x33, 0x22, 0x11, 0xFF])
    // Same floor the desktop's premultiplied_u32 takes: 200 * 128 // 255 == 100.
    XCTAssertEqual(PixelBuffer.premultipliedWord(r: 200, g: 0, b: 0, a: 128), 0x8064_0000)
  }

  func testImageRoundTripIsByteExact() throws {
    let original = sampleBuffer()
    let image = try XCTUnwrap(original.makeImage())
    XCTAssertEqual(image.scale, 1)
    XCTAssertEqual(image.imageOrientation, .up)
    XCTAssertEqual(image.size, CGSize(width: 7, height: 5))

    let back = try XCTUnwrap(PixelBuffer(image: image))
    XCTAssertEqual(back.width, 7)
    XCTAssertEqual(back.height, 5)
    XCTAssertEqual(back.bytesPerRow, 28)
    XCTAssertEqual(back.words, original.words)

    // And once more, so a layer that has already been through the seam is
    // not disturbed by going through it again.
    let again = try XCTUnwrap(PixelBuffer(image: try XCTUnwrap(back.makeImage())))
    XCTAssertEqual(again.words, original.words)
  }

  func testBufferFromARendererImageKeepsPremultipliedInvariant() throws {
    // A UIKit-rendered image is what a real layer is; every channel must sit
    // at or below its alpha once it is in the buffer.
    let image = EditorStore.solidImage(
      size: CGSize(width: 9, height: 4), color: UIColor(red: 1, green: 0.5, blue: 0, alpha: 0.5))
    let buffer = try XCTUnwrap(PixelBuffer(image: image))
    for word in buffer.words {
      let a = word >> 24
      XCTAssertLessThanOrEqual((word >> 16) & 0xFF, a)
      XCTAssertLessThanOrEqual((word >> 8) & 0xFF, a)
      XCTAssertLessThanOrEqual(word & 0xFF, a)
      XCTAssertGreaterThan(a, 0)
    }
  }

  func testBufferRespectsPixelSizeAndOrientation() throws {
    // A 2x image has twice the pixels its point size says.
    var wide = PixelBuffer(width: 4, height: 2)
    for i in 0..<wide.words.count { wide.words[i] = 0xFF00_0000 | UInt32(i) }
    let cg = try XCTUnwrap(try XCTUnwrap(wide.makeImage()).cgImage)
    let scaled = UIImage(cgImage: cg, scale: 2, orientation: .up)
    XCTAssertEqual(scaled.size, CGSize(width: 2, height: 1))
    let fromScaled = try XCTUnwrap(PixelBuffer(image: scaled))
    XCTAssertEqual(fromScaled.width, 4)
    XCTAssertEqual(fromScaled.height, 2)
    XCTAssertEqual(fromScaled.words, wide.words)

    // A rotated image comes out the way it is displayed: 4x2 rotated right is
    // 2 wide and 4 tall, with the old bottom-left pixel now top-left.
    let rotated = UIImage(cgImage: cg, scale: 1, orientation: .right)
    let fromRotated = try XCTUnwrap(PixelBuffer(image: rotated))
    XCTAssertEqual(fromRotated.width, 2)
    XCTAssertEqual(fromRotated.height, 4)
    XCTAssertEqual(fromRotated.word(x: 0, y: 0), wide.word(x: 0, y: 1))
    XCTAssertEqual(fromRotated.word(x: 1, y: 3), wide.word(x: 3, y: 0))
  }

  func testProbeReadsSinglePixelsWithoutABuffer() throws {
    let original = sampleBuffer()
    let image = try XCTUnwrap(original.makeImage())
    for y in 0..<original.height {
      for x in 0..<original.width {
        XCTAssertEqual(PixelBuffer.probe(image: image, x: x, y: y), original.word(x: x, y: y))
      }
    }
    XCTAssertNil(PixelBuffer.probe(image: image, x: 7, y: 0))
    XCTAssertNil(PixelBuffer.probe(image: image, x: 0, y: -1))
  }

  func testBandsCoverEveryRowExactlyOnce() {
    for height in [1, 255, 256, 257, 1000, 1536] {
      var visits = [Int](repeating: 0, count: height)
      var bands = 0
      PixelBuffer.forEachBand(height: height) { rows in
        bands += 1
        XCTAssertLessThanOrEqual(rows.count, PixelBuffer.bandRows)
        for y in rows { visits[y] += 1 }
      }
      XCTAssertEqual(visits, [Int](repeating: 1, count: height), "height \(height)")
      XCTAssertEqual(bands, (height + PixelBuffer.bandRows - 1) / PixelBuffer.bandRows)
    }
  }

  func testApplyPixelOperationRegistersOneUndoStepAndUndoRestoresBytes() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 40, height: 30))
    let undoManager = UndoManager()
    // UndoManager groups by run loop event by default, and a test never turns
    // the run loop, so the implicit group would never close. Grouping by hand
    // makes the fill's registration land in exactly one group, and the
    // `canUndo` check after a single undo below is what proves it was one step.
    undoManager.groupsByEvent = false
    store.undoManager = undoManager
    let layerID = try XCTUnwrap(store.activeLayerID)
    let before = try XCTUnwrap(PixelBuffer(image: store.layers[0].image))

    undoManager.beginUndoGrouping()
    let applied = store.applyPixelOperation(to: layerID, actionName: "Tint") { buffer in
      buffer.forEachBand { rows in
        for y in rows { buffer.setWord(0xFF00_FF00, x: 3, y: y) }
      }
      return true
    }
    undoManager.endUndoGrouping()
    XCTAssertTrue(applied)
    XCTAssertTrue(undoManager.canUndo)
    XCTAssertEqual(undoManager.undoActionName, "Tint")

    let after = try XCTUnwrap(PixelBuffer(image: store.layers[0].image))
    XCTAssertEqual(after.word(x: 3, y: 0), 0xFF00_FF00)
    XCTAssertEqual(after.word(x: 3, y: 29), 0xFF00_FF00)
    XCTAssertEqual(after.word(x: 4, y: 0), before.word(x: 4, y: 0))

    undoManager.undo()
    let restored = try XCTUnwrap(PixelBuffer(image: store.layers[0].image))
    XCTAssertEqual(restored.words, before.words)
    XCTAssertFalse(undoManager.canUndo)
    XCTAssertTrue(undoManager.canRedo)
  }

  func testNoOpRegistersNothing() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 20, height: 20))
    let undoManager = UndoManager()
    store.undoManager = undoManager
    let layerID = try XCTUnwrap(store.activeLayerID)
    let image = store.layers[0].image

    let applied = store.applyPixelOperation(to: layerID, actionName: "Nothing") { _ in false }
    XCTAssertFalse(applied)
    XCTAssertFalse(undoManager.canUndo)
    XCTAssertTrue(store.layers[0].image === image, "an unchanged layer keeps its image")
  }

  func testPixelOperationRefusesTextLayers() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 200, height: 100))
    let undoManager = UndoManager()
    store.undoManager = undoManager
    XCTAssertTrue(store.addTextLayer("Hi", fontSize: 24, color: .black, at: CGPoint(x: 10, y: 10)))
    let textID = try XCTUnwrap(store.activeLayerID)
    XCTAssertTrue(store.layers.first { $0.id == textID }?.isText ?? false)
    undoManager.removeAllActions()

    var ran = false
    let applied = store.applyPixelOperation(to: textID, actionName: "Fill") { _ in
      ran = true
      return true
    }
    XCTAssertFalse(applied)
    XCTAssertFalse(ran)
    XCTAssertFalse(undoManager.canUndo)
  }

  func testPixelOperationSeesStrokesAndBakesThem() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 64, height: 48))
    let layerID = try XCTUnwrap(store.activeLayerID)
    // A thick black pen stroke across the middle of the canvas.
    let points = [CGPoint(x: 4, y: 24), CGPoint(x: 60, y: 24)].map {
      PKStrokePoint(
        location: $0, timeOffset: 0, size: CGSize(width: 10, height: 10), opacity: 1,
        force: 1, azimuth: 0, altitude: .pi / 2)
    }
    let path = PKStrokePath(controlPoints: points, creationDate: Date())
    store.setDrawing(PKDrawing(strokes: [PKStroke(ink: PKInk(.pen, color: .black), path: path)]))
    XCTAssertFalse(try XCTUnwrap(store.activeLayer).drawing.strokes.isEmpty)

    var underStroke: UInt32 = 0
    var offStroke: UInt32 = 0
    XCTAssertTrue(
      store.applyPixelOperation(to: layerID, actionName: "Probe") { buffer in
        XCTAssertEqual(buffer.width, 64)
        XCTAssertEqual(buffer.height, 48)
        underStroke = buffer.word(x: 32, y: 24)
        offStroke = buffer.word(x: 32, y: 4)
        return true
      })
    // The stroke is in the pixels the operation saw: dark ink over the white
    // background, while the background is untouched elsewhere.
    XCTAssertEqual(offStroke, 0xFFFF_FFFF)
    XCTAssertNotEqual(underStroke, offStroke)
    XCTAssertLessThan((underStroke >> 16) & 0xFF, 0x40)
    // And baked: the layer no longer carries vector strokes.
    let result = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(result.drawing.strokes.isEmpty)
    XCTAssertTrue(result.fillsCanvas(store.canvasSize))
  }
}

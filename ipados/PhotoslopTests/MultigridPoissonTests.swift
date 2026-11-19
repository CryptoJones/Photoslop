// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Tests for the Cascadic Multigrid Poisson solver and EditorStore healing operations (Issue #415).
@MainActor
final class MultigridPoissonTests: XCTestCase {

  // MARK: - Plane & Multigrid Algorithm Tests

  func testLaplaceRampReconstruction() {
    let w = 40, h = 40
    var groundTruth = [Float](repeating: 0, count: w * h)
    for y in 0..<h {
      for x in 0..<w {
        groundTruth[y * w + x] = 20.0 + 1.5 * Float(x) + 2.5 * Float(y)
      }
    }

    var destData = groundTruth
    var mask = [Bool](repeating: false, count: w * h)
    for y in 10..<30 {
      for x in 10..<30 {
        mask[y * w + x] = true
        destData[y * w + x] = 0.0 // erase hole
      }
    }

    let destPlane = MultigridPoisson.Plane(width: w, height: h, data: destData)
    let solved = MultigridPoisson.solveChannel(dest: destPlane, mask: mask)

    var maxErr: Float = 0
    for y in 10..<30 {
      for x in 10..<30 {
        let err = abs(solved[x, y] - groundTruth[y * w + x])
        if err > maxErr { maxErr = err }
      }
    }
    XCTAssertLessThan(maxErr, 0.05, "Laplace reconstruction of ramp should be virtually exact")
  }

  func testSeamlessClonePreservesTextureAndMatchesTone() {
    let w = 40, h = 40
    let destPlane = MultigridPoisson.Plane(width: w, height: h, initialValue: 50.0)

    // Checkerboard texture in source: 160 vs 220 (mean 190)
    var srcData = [Float](repeating: 0, count: w * h)
    for y in 0..<h {
      for x in 0..<w {
        let check = ((y / 4) + (x / 4)) % 2 == 0
        srcData[y * w + x] = check ? 220.0 : 160.0
      }
    }
    let srcPlane = MultigridPoisson.Plane(width: w, height: h, data: srcData)

    var mask = [Bool](repeating: false, count: w * h)
    for y in 10..<30 {
      for x in 10..<30 {
        mask[y * w + x] = true
      }
    }

    let solved = MultigridPoisson.solveChannel(dest: destPlane, mask: mask, src: srcPlane, mixed: false)

    var sum: Float = 0
    var count: Float = 0
    for y in 10..<30 {
      for x in 10..<30 {
        sum += solved[x, y]
        count += 1
      }
    }
    let mean = sum / count
    XCTAssertEqual(mean, 50.0, accuracy: 1.0, "Tone should shift to match destination (50.0)")

    var sumSq: Float = 0
    for y in 10..<30 {
      for x in 10..<30 {
        let diff = solved[x, y] - mean
        sumSq += diff * diff
      }
    }
    let variance = sumSq / count
    XCTAssertGreaterThan(variance, 700.0, "Texture variance should be preserved")

    // Boundary matches destination exactly
    XCTAssertEqual(solved[20, 9], 50.0)
    XCTAssertEqual(solved[20, 30], 50.0)
  }

  // MARK: - PixelBuffer Inpainting & Seamless Cloning

  func testInpaintRemovesBlemishInPixelBuffer() {
    let w = 40, h = 40
    var buffer = PixelBuffer(width: w, height: h)
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let black = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 0, a: 255)

    buffer.withMutableWords { words in
      for i in 0..<words.count { words[i] = gray }
      for y in 18..<22 {
        for x in 18..<22 {
          words[y * w + x] = black
        }
      }
    }

    var mask = [Bool](repeating: false, count: w * h)
    for y in 17..<23 {
      for x in 17..<23 {
        mask[y * w + x] = true
      }
    }

    let rect = MultigridPoisson.inpaint(buffer: &buffer, mask: mask)
    XCTAssertNotNil(rect)

    let centerWord = buffer.word(x: 20, y: 20)
    let r = (centerWord >> 16) & 0xFF
    let g = (centerWord >> 8) & 0xFF
    let b = centerWord & 0xFF

    XCTAssertGreaterThan(r, 150, "Blemish should be filled with surround-like gray")
    XCTAssertGreaterThan(g, 150)
    XCTAssertGreaterThan(b, 150)
    XCTAssertEqual(buffer.word(x: 5, y: 5), gray, "Untouched regions remain exact")
  }

  func testCanvasEdgeInpaintingWithNeumann() {
    let w = 30, h = 30
    var buffer = PixelBuffer(width: w, height: h)
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let dark = PixelBuffer.premultipliedWord(r: 10, g: 10, b: 10, a: 255)

    buffer.withMutableWords { words in
      for i in 0..<words.count { words[i] = gray }
      for y in 0..<8 {
        for x in 0..<8 {
          words[y * w + x] = dark
        }
      }
    }

    var mask = [Bool](repeating: false, count: w * h)
    for y in 0..<8 {
      for x in 0..<8 {
        mask[y * w + x] = true
      }
    }

    let rect = MultigridPoisson.inpaint(buffer: &buffer, mask: mask)
    XCTAssertNotNil(rect)

    let cornerWord = buffer.word(x: 2, y: 2)
    let r = (cornerWord >> 16) & 0xFF
    XCTAssertGreaterThan(r, 140, "Corner touching canvas boundary must inpaint to surround")
  }

  // MARK: - EditorStore Integration Tests

  func testEditorStoreSpotHealSelection() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 40, height: 40))

    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let black = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 0, a: 255)

    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = gray }
        for y in 18..<22 {
          for x in 18..<22 { words[y * 40 + x] = black }
        }
      }
      return true
    })

    let undoManager = UndoManager()
    store.undoManager = undoManager

    var bits = [Bool](repeating: false, count: 40 * 40)
    for y in 17..<23 {
      for x in 17..<23 { bits[y * 40 + x] = true }
    }
    store.setSelection(SelectionMask(width: 40, height: 40, bits: bits))

    XCTAssertTrue(store.spotHealSelection())
    XCTAssertEqual(undoManager.undoActionName, "Spot Heal")

    let probe = PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: 20, y: 20)
    let r = ((try XCTUnwrap(probe)) >> 16) & 0xFF
    XCTAssertGreaterThan(r, 150)

    undoManager.undo()
    let undoneProbe = PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: 20, y: 20)
    XCTAssertEqual(undoneProbe, black)
  }

  func testEditorStoreHealSelectionWithSourceOffset() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 60, height: 30))

    let dark = PixelBuffer.premultipliedWord(r: 50, g: 50, b: 50, a: 255)
    let bright = PixelBuffer.premultipliedWord(r: 220, g: 220, b: 220, a: 255)

    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = dark }
        for y in 0..<30 {
          for x in 0..<20 { words[y * 60 + x] = bright }
        }
      }
      return true
    })

    let undoManager = UndoManager()
    store.undoManager = undoManager

    // Select a region in the dark area (x: 40..<50, y: 10..<20)
    var bits = [Bool](repeating: false, count: 60 * 30)
    for y in 10..<20 {
      for x in 40..<50 { bits[y * 60 + x] = true }
    }
    store.setSelection(SelectionMask(width: 60, height: 30, bits: bits))

    // Sample from left side: dx = 10 - 40 = -30
    XCTAssertTrue(store.healSelection(dx: -30, dy: 0))
    XCTAssertEqual(undoManager.undoActionName, "Healing Brush")

    let probe = PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: 45, y: 15)
    let r = ((try XCTUnwrap(probe)) >> 16) & 0xFF
    // Tone should blend smoothly near destination (50)
    XCTAssertLessThan(r, 110)

    undoManager.undo()
    let undoneProbe = PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: 45, y: 15)
    XCTAssertEqual(undoneProbe, dark)
  }

  func testEditorStoreSpotHealDab() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 40, height: 40))
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let black = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 0, a: 255)

    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = gray }
        words[20 * 40 + 20] = black
      }
      return true
    })

    XCTAssertTrue(store.spotHeal(at: CGPoint(x: 20, y: 20), radius: 4))
    let probe = PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: 20, y: 20)
    let r = ((try XCTUnwrap(probe)) >> 16) & 0xFF
    XCTAssertGreaterThan(r, 150)
  }
}

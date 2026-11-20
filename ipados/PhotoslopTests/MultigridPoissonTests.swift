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

  func testLargeHoleRampCenter() {
    // A large hole must reproduce the ramp at its centre, not just near the
    // boundary — the dynamic-depth pyramid + residual stop carry the low
    // frequency part (CodeRabbit MultigridPoisson.swift:234).
    let w = 200, h = 200
    var groundTruth = [Float](repeating: 0, count: w * h)
    for y in 0..<h {
      for x in 0..<w {
        groundTruth[y * w + x] = 20.0 + 0.05 * Float(x) + 0.08 * Float(y)
      }
    }
    var destData = groundTruth
    var mask = [Bool](repeating: false, count: w * h)
    for y in 4..<(h - 4) {
      for x in 4..<(w - 4) {
        mask[y * w + x] = true
        destData[y * w + x] = 0.0
      }
    }
    let solved = MultigridPoisson.solveChannel(
      dest: MultigridPoisson.Plane(width: w, height: h, data: destData), mask: mask)
    let cx = w / 2, cy = h / 2
    XCTAssertEqual(solved[cx, cy], groundTruth[cy * w + cx], accuracy: 0.5,
                   "Centre of a large hole must match the harmonic ramp")
  }

  func testLargeConstantOffsetClone() {
    // Flat source 220 over destination boundary 60: the offset -160 must reach
    // the centre of a large mask (CodeRabbit npimage.py:330 / Swift parity).
    let n = 256
    let dest = MultigridPoisson.Plane(width: n, height: n, initialValue: 60.0)
    let src = MultigridPoisson.Plane(width: n, height: n, initialValue: 220.0)
    var mask = [Bool](repeating: false, count: n * n)
    for y in 8..<(n - 8) {
      for x in 8..<(n - 8) { mask[y * n + x] = true }
    }
    let solved = MultigridPoisson.solveChannel(dest: dest, mask: mask, src: src, mixed: false)
    XCTAssertEqual(solved[n / 2, n / 2], 60.0, accuracy: 0.5)
    var maxDev: Float = 0
    for y in 8..<(n - 8) {
      for x in 8..<(n - 8) { maxDev = max(maxDev, abs(solved[x, y] - 60.0)) }
    }
    XCTAssertLessThan(maxDev, 1.0, "Constant offset must be exact throughout")
  }

  func testCloneHighFreqTextureToneMatched() {
    // A near-Nyquist (single-pixel checkerboard) source must be tone-matched to
    // the destination across a large hole, not aliased to one phase by the coarse
    // restriction (CodeRabbit npimage.py:350 / Swift parity). Injection sampled
    // only the 220 phase, biasing the offset to -160 instead of -130; aligned
    // full-weighting restriction preserves the source mean (190).
    let n = 256
    let dest = MultigridPoisson.Plane(width: n, height: n, initialValue: 60.0)
    var srcData = [Float](repeating: 0, count: n * n)
    for y in 0..<n {
      for x in 0..<n {
        srcData[y * n + x] = ((y + x) % 2 == 0) ? 220.0 : 160.0  // mean 190
      }
    }
    let src = MultigridPoisson.Plane(width: n, height: n, data: srcData)
    var mask = [Bool](repeating: false, count: n * n)
    for y in 8..<(n - 8) {
      for x in 8..<(n - 8) { mask[y * n + x] = true }
    }
    let solved = MultigridPoisson.solveChannel(dest: dest, mask: mask, src: src, mixed: false)
    // Correct harmonic offset is 60 - 190 = -130 throughout the interior.
    var sum: Float = 0
    var count: Float = 0
    for y in 8..<(n - 8) {
      for x in 8..<(n - 8) {
        sum += solved[x, y]
        count += 1
      }
    }
    XCTAssertEqual(sum / count, 60.0, accuracy: 1.0, "Interior tone must match destination")
    let c = n / 2
    XCTAssertEqual(solved[c, c], 90.0, accuracy: 1.0)  // 220 - 130
    XCTAssertEqual(solved[c + 1, c], 30.0, accuracy: 1.0)  // 160 - 130
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
      for x in 10..<30 { mask[y * w + x] = true }
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
        for x in 18..<22 { words[y * w + x] = black }
      }
    }

    var mask = [Bool](repeating: false, count: w * h)
    for y in 17..<23 {
      for x in 17..<23 { mask[y * w + x] = true }
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
        for x in 0..<8 { words[y * w + x] = dark }
      }
    }

    var mask = [Bool](repeating: false, count: w * h)
    for y in 0..<8 {
      for x in 0..<8 { mask[y * w + x] = true }
    }

    let rect = MultigridPoisson.inpaint(buffer: &buffer, mask: mask)
    XCTAssertNotNil(rect)

    let cornerWord = buffer.word(x: 2, y: 2)
    XCTAssertGreaterThan((cornerWord >> 16) & 0xFF, 140, "Interior corner must inpaint to surround")
    // Probe the actual canvas-edge pixel (0,0): writeback must not skip row 0 /
    // column 0 (CodeRabbit MultigridPoissonTests.swift:159).
    let edgeWord = buffer.word(x: 0, y: 0)
    XCTAssertGreaterThan((edgeWord >> 16) & 0xFF, 140, "Masked canvas-edge pixel must be written")
  }

  func testInpaintFullOpaqueImageReturnsNil() {
    // Spot-healing an entire opaque image leaves no known boundary pixel: the
    // operation must refuse (nil), not fill with translucent 128 and report
    // success (CodeRabbit MultigridPoisson.swift:218).
    let w = 8, h = 8
    var buffer = PixelBuffer(width: w, height: h)
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    buffer.withMutableWords { words in
      for i in 0..<words.count { words[i] = gray }
    }
    let mask = [Bool](repeating: true, count: w * h)
    let rect = MultigridPoisson.inpaint(buffer: &buffer, mask: mask)
    XCTAssertNil(rect, "No known boundary pixel -> no edit")
    XCTAssertEqual(buffer.word(x: 4, y: 4), gray, "Image must be unchanged")
  }

  func testSpotHealDabCoveringNoPixelReturnsNil() {
    // A radius-4 dab at (-3,-3) has a clipped bbox but covers no pixel: must
    // return nil, not a successful empty edit (CodeRabbit MultigridPoisson.swift:360).
    let w = 40, h = 40
    var buffer = PixelBuffer(width: w, height: h)
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    buffer.withMutableWords { words in
      for i in 0..<words.count { words[i] = gray }
    }
    let rect = MultigridPoisson.spotHeal(buffer: &buffer, center: CGPoint(x: -3, y: -3), radius: 4)
    XCTAssertNil(rect)
    XCTAssertEqual(buffer.word(x: 0, y: 0), gray)
  }

  func testNarrowBufferSpotHealAdmittedByGhostBorder() {
    // A 2-wide crop becomes 4 wide after the left/right ghost columns; the size
    // guard must check padW/padH, not cropW/cropH (CodeRabbit MultigridPoisson.swift:382).
    let w = 2, h = 8
    var buffer = PixelBuffer(width: w, height: h)
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let black = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 0, a: 255)
    buffer.withMutableWords { words in
      for i in 0..<words.count { words[i] = gray }
      for y in 3..<5 {
        for x in 0..<2 { words[y * w + x] = black }
      }
    }
    var mask = [Bool](repeating: false, count: w * h)
    for y in 3..<5 {
      for x in 0..<2 { mask[y * w + x] = true }
    }
    let rect = MultigridPoisson.inpaint(buffer: &buffer, mask: mask)
    XCTAssertNotNil(rect, "Ghost border admits the narrow crop")
    XCTAssertGreaterThan((buffer.word(x: 0, y: 3) >> 16) & 0xFF, 140)
  }

  func testHealSourceFootprintAtCanvasEdge() {
    // A dab whose sampled source footprint fits on-canvas must heal even when
    // the solver halo crosses the edge (CodeRabbit MultigridPoisson.swift:503).
    let w = 60, h = 30
    var buffer = PixelBuffer(width: w, height: h)
    let flat = PixelBuffer.premultipliedWord(r: 60, g: 60, b: 60, a: 255)
    buffer.withMutableWords { words in
      for i in 0..<words.count { words[i] = flat }
      for y in 16..<25 {
        for x in 0..<9 {
          let c: Int = ((x / 2) + (y / 2)) % 2 == 0 ? 220 : 160
          words[y * w + x] = PixelBuffer.premultipliedWord(r: c, g: c, b: c, a: 255)
        }
      }
      // Reset the destination dab to flat 60 so it starts untextured.
      for y in 18..<23 {
        for x in 2..<7 { words[y * w + x] = flat }
      }
    }
    var mask = [Bool](repeating: false, count: w * h)
    for y in 18..<23 {
      for x in 2..<7 { mask[y * w + x] = true }
    }
    // dx = -2: source footprint x=0..4 fits, but the pad-4 halo reaches x=-2.
    let rect = MultigridPoisson.seamlessClone(buffer: &buffer, mask: mask, dx: -2, dy: 0)
    XCTAssertNotNil(rect, "Valid source footprint must not be refused")
    var changed = false
    for y in 18..<23 {
      for x in 2..<7 where buffer.word(x: x, y: y) != flat { changed = true }
    }
    XCTAssertTrue(changed, "Source texture must transfer")
    XCTAssertEqual(buffer.word(x: 30, y: 20), flat, "Unmasked pixel unchanged")
  }

  func testHealRefusesOffCanvasSourceFootprint() {
    let w = 60, h = 30
    var buffer = PixelBuffer(width: w, height: h)
    let flat = PixelBuffer.premultipliedWord(r: 60, g: 60, b: 60, a: 255)
    buffer.withMutableWords { words in
      for i in 0..<words.count { words[i] = flat }
    }
    var mask = [Bool](repeating: false, count: w * h)
    for y in 18..<23 {
      for x in 2..<7 { mask[y * w + x] = true }
    }
    let rect = MultigridPoisson.seamlessClone(buffer: &buffer, mask: mask, dx: -10, dy: 0)
    XCTAssertNil(rect, "Off-canvas source footprint must be refused")
    XCTAssertEqual(buffer.word(x: 4, y: 20), flat)
  }

  // MARK: - EditorStore Integration Tests

  func testEditorStoreSpotHealSelection() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 40, height: 40))

    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let black = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 0, a: 255)

    let undoManager = UndoManager()
    store.undoManager = undoManager

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
    // Clear the fixture undo step so healing is the only undoable action.
    undoManager.removeAllActions()

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

    let undoManager = UndoManager()
    store.undoManager = undoManager

    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = dark }
        // A distinct checker texture in the sampled source block (x 0..<20).
        // A flat source would tone-match to the dark field and look like a
        // no-op; texture makes the assertion fail if no edit occurs.
        for y in 0..<30 {
          for x in 0..<20 {
            let c: Int = ((x / 2) + (y / 2)) % 2 == 0 ? 220 : 160
            words[y * 60 + x] = PixelBuffer.premultipliedWord(r: c, g: c, b: c, a: 255)
          }
        }
      }
      return true
    })
    undoManager.removeAllActions()

    // Select a region in the dark area (x: 40..<50, y: 10..<20)
    var bits = [Bool](repeating: false, count: 60 * 30)
    for y in 10..<20 {
      for x in 40..<50 { bits[y * 60 + x] = true }
    }
    store.setSelection(SelectionMask(width: 60, height: 30, bits: bits))

    // Sample from the textured left side: dx = 10 - 40 = -30
    XCTAssertTrue(store.healSelection(dx: -30, dy: 0))
    XCTAssertEqual(undoManager.undoActionName, "Healing Brush")

    // Texture transferred: the healed region is no longer uniformly dark.
    var minR: UInt32 = 255, maxR: UInt32 = 0
    for y in 12..<18 {
      for x in 42..<48 {
        let probe = try XCTUnwrap(PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: x, y: y))
        let r = (probe >> 16) & 0xFF
        minR = min(minR, r)
        maxR = max(maxR, r)
      }
    }
    XCTAssertGreaterThan(maxR - minR, 20, "Source texture must appear at the destination")
    XCTAssertLessThan(maxR, 160, "Tone must stay matched to the dark destination")

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

  // MARK: - Interactive stroke tools (#456)

  /// A drag of several dabs heals the whole trail and is a single undo step,
  /// the way the desktop's SpotHealTool inpaints its accumulated mask once on
  /// release.
  func testEditorStoreSpotHealStrokeIsOneUndoStep() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 40, height: 40))
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let black = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 0, a: 255)

    let undoManager = UndoManager()
    store.undoManager = undoManager

    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = gray }
        // A horizontal blemish the stroke will cover.
        for x in 14..<27 { words[20 * 40 + x] = black }
      }
      return true
    })
    undoManager.removeAllActions()

    let centers = [CGPoint(x: 15, y: 20), CGPoint(x: 20, y: 20), CGPoint(x: 25, y: 20)]
    XCTAssertTrue(store.spotHealStroke(centers: centers, radius: 4))
    XCTAssertEqual(undoManager.undoActionName, "Spot Heal")

    // Every dab center healed, not just the first.
    for x in [15, 20, 25] {
      let probe = try XCTUnwrap(PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: x, y: 20))
      XCTAssertGreaterThan((probe >> 16) & 0xFF, 150, "dab at \(x) did not heal")
    }

    // One stroke, one undo: the whole trail comes back at once.
    undoManager.undo()
    for x in [15, 20, 25] {
      let probe = PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: x, y: 20)
      XCTAssertEqual(probe, black, "undo did not restore dab at \(x)")
    }
    XCTAssertFalse(undoManager.canUndo, "a stroke must register exactly one undo step")
  }

  /// A healing-brush stroke transplants the source texture along the trail,
  /// tone-matched, as one undo step.
  func testEditorStoreHealStrokeIsOneUndoStep() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 60, height: 30))
    let dark = PixelBuffer.premultipliedWord(r: 50, g: 50, b: 50, a: 255)

    let undoManager = UndoManager()
    store.undoManager = undoManager

    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = dark }
        for y in 0..<30 {
          for x in 0..<20 {
            let c: Int = ((x / 2) + (y / 2)) % 2 == 0 ? 220 : 160
            words[y * 60 + x] = PixelBuffer.premultipliedWord(r: c, g: c, b: c, a: 255)
          }
        }
      }
      return true
    })
    undoManager.removeAllActions()

    // Destinations in the dark field; offset 30 samples the textured left side
    // (source = center − offset lands at x 10, 15, 20).
    let centers = [CGPoint(x: 40, y: 15), CGPoint(x: 45, y: 15), CGPoint(x: 50, y: 15)]
    XCTAssertTrue(store.healStroke(centers: centers, sourceOffset: CGSize(width: 30, height: 0), radius: 4))
    XCTAssertEqual(undoManager.undoActionName, "Healing Brush")

    var minR: UInt32 = 255, maxR: UInt32 = 0
    for x in 40..<51 {
      let probe = try XCTUnwrap(PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: x, y: 15))
      let r = (probe >> 16) & 0xFF
      minR = min(minR, r)
      maxR = max(maxR, r)
    }
    XCTAssertGreaterThan(maxR - minR, 20, "source texture must appear along the stroke")
    XCTAssertLessThan(maxR, 160, "tone must stay matched to the dark destination")

    undoManager.undo()
    XCTAssertEqual(
      PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: 45, y: 15), dark)
    XCTAssertFalse(undoManager.canUndo, "a stroke must register exactly one undo step")
  }

  /// The aligned offset semantics: source = center − offset, so a positive
  /// offset samples to the left of the destination.
  func testHealStrokeAlignedOffsetSamplesSource() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 60, height: 30))
    let dark = PixelBuffer.premultipliedWord(r: 50, g: 50, b: 50, a: 255)
    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = dark }
        for y in 0..<30 {
          for x in 0..<20 {
            let c: Int = ((x / 2) + (y / 2)) % 2 == 0 ? 220 : 160
            words[y * 60 + x] = PixelBuffer.premultipliedWord(r: c, g: c, b: c, a: 255)
          }
        }
      }
      return true
    })
    // A single-dab stroke at x=45 with offset 35 samples x=10 (textured).
    XCTAssertTrue(store.healStroke(
      centers: [CGPoint(x: 45, y: 15)], sourceOffset: CGSize(width: 35, height: 0), radius: 4))
    var minR: UInt32 = 255, maxR: UInt32 = 0
    for x in 43..<48 {
      let probe = try XCTUnwrap(PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: x, y: 15))
      let r = (probe >> 16) & 0xFF
      minR = min(minR, r); maxR = max(maxR, r)
    }
    XCTAssertGreaterThan(maxR - minR, 15, "the offset must sample the textured source")
  }

  func testSpotHealStrokeEmptyCentersReturnsFalse() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 20, height: 20))
    XCTAssertFalse(store.spotHealStroke(centers: [], radius: 4))
    XCTAssertFalse(store.healStroke(centers: [], sourceOffset: .zero, radius: 4))
  }

  /// A stroke wholly off the canvas changes nothing and registers no undo.
  func testSpotHealStrokeOffCanvasReturnsFalse() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 20, height: 20))
    let undoManager = UndoManager()
    store.undoManager = undoManager
    XCTAssertFalse(store.spotHealStroke(centers: [CGPoint(x: -10, y: -10)], radius: 2))
    XCTAssertFalse(undoManager.canUndo)
  }

  /// A stroke that mixes a far-off-canvas center with an on-canvas one must heal
  /// the on-canvas dab and not crash. The mask-building pass clips each dab like
  /// the bounding-box pass does; without that guard an off-canvas center built
  /// `0..<negative` and trapped Swift's Range precondition — a drag starting in
  /// the surround beside the fitted canvas and ending on the image (#456).
  func testSpotHealStrokeMixedOffCanvasCenterDoesNotCrash() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 20, height: 20))
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let black = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 0, a: 255)
    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = gray }
        words[10 * 20 + 10] = black
      }
      return true
    })
    // The first center is far off the canvas; the second heals the blemish.
    let centers = [CGPoint(x: -100, y: -100), CGPoint(x: 10, y: 10)]
    XCTAssertTrue(store.spotHealStroke(centers: centers, radius: 4))
    let probe = try XCTUnwrap(PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: 10, y: 10))
    XCTAssertGreaterThan((probe >> 16) & 0xFF, 150, "the on-canvas dab must still heal")
  }

  /// A dab straddling the canvas edge heals rather than refusing or smearing: the
  /// local-mask inpaint edge-replicates the solver halo on the clipped side.
  func testSpotHealStrokeEdgeDabHeals() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 40, height: 40))
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let black = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 0, a: 255)
    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = gray }
        for x in 0..<4 { words[10 * 40 + x] = black }
      }
      return true
    })
    // Centered on the left edge: the dab clips to x 0...3.
    XCTAssertTrue(store.spotHealStroke(centers: [CGPoint(x: 0, y: 10)], radius: 4))
    let probe = try XCTUnwrap(PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: 1, y: 10))
    XCTAssertGreaterThan((probe >> 16) & 0xFF, 150, "an edge dab must heal toward the field")
  }

  /// Dabs spaced at the drag spacing (radius/2) cover the whole segment between
  /// the first and last center — the union mask has no holes, which is what the
  /// drag handler's interpolation guarantees for a fast stroke (#456).
  func testSpotHealStrokeCoversTrailAtSpacing() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 40, height: 40))
    let gray = PixelBuffer.premultipliedWord(r: 180, g: 180, b: 180, a: 255)
    let black = PixelBuffer.premultipliedWord(r: 0, g: 0, b: 0, a: 255)
    let layer = try XCTUnwrap(store.activeLayer)
    XCTAssertTrue(store.applyPixelOperation(to: layer.id, actionName: "Setup") { buf in
      buf.withMutableWords { words in
        for i in 0..<words.count { words[i] = gray }
        for x in 10...30 { words[20 * 40 + x] = black }
      }
      return true
    })
    // radius 4 → spacing 2; centers every 2px from 10 to 30, as interpolation emits.
    let centers = stride(from: 10, through: 30, by: 2).map { CGPoint(x: $0, y: 20) }
    XCTAssertTrue(store.spotHealStroke(centers: centers, radius: 4))
    for x in 10...30 {
      let probe = try XCTUnwrap(PixelBuffer.probe(image: try XCTUnwrap(store.activeLayer).image, x: x, y: 20))
      XCTAssertGreaterThan((probe >> 16) & 0xFF, 150, "unhealed hole in the trail at x=\(x)")
    }
  }
}
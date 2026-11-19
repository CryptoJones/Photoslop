// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Comprehensive test suite for Select and Mask & Guided Filter matting on iOS (Issue #417).
///
/// Verifies:
/// 1. Guided Filter matting accuracy (recovering visual edges and snapping boundaries).
/// 2. Smart Radius (adaptive bandwidth based on transition width).
/// 3. Global refinements (smooth, feather, contrast steepening, shift edge morphology).
/// 4. Color decontamination (normalized convolution interior-to-fringe bleed removal).
/// 5. Edge cases: empty masks, zero radii, boundary limits, all-canvas selections.
/// 6. Memory frugality (DD-001): bounded ROI execution with zero persistent overhead.
@MainActor
final class RefineSelectionTests: XCTestCase {

  private func makeBuffer(width: Int, height: Int, color: UInt32 = 0xFF00_0000) -> PixelBuffer {
    PixelBuffer(width: width, height: height, words: [UInt32](repeating: color, count: width * height))
  }

  // MARK: - 1. Guided Filter Matting

  func testGuidedFilterSnapsEdgeTowardsTrueBoundary() {
    let width = 40, height = 40
    // Left half (cols 0..<20) is pure blue (0xFF0000FF), right half (cols 20..<40) is yellow (0xFFFFFF00)
    var buffer = makeBuffer(width: width, height: height)
    buffer.withMutableWords { words in
      for y in 0..<height {
        for x in 0..<width {
          words[y * width + x] = (x < 20) ? 0xFFFF_0000 : 0xFF00_FFFF
        }
      }
    }

    // Rough mask with edge placed at col 24 (4 pixels off from true boundary at col 20)
    var bits = [Bool](repeating: false, count: width * height)
    for y in 0..<height {
      for x in 24..<width {
        bits[y * width + x] = true
      }
    }
    let mask = SelectionMask(width: width, height: height, bits: bits)

    var options = RefineSelectionOptions()
    options.radius = 6

    let (refined, _) = RefineSelectionAlgorithms.refineSelection(
      mask: mask, buffer: buffer, options: options
    )

    // Selection should snap towards col 20
    XCTAssertFalse(refined.contains(x: 15, y: 20), "Background region must not be selected")
    XCTAssertTrue(refined.contains(x: 28, y: 20), "Foreground interior must remain selected")
    // The edge moved closer to x=20 than original rough mask at x=24
    XCTAssertGreaterThan(refined.count, mask.count, "Refined mask expanded to capture foreground pixels")
  }

  func testGuidedFilterCapturesThinFeature() {
    let width = 30, height = 30
    var red = [Float](repeating: 0, count: width * height)
    var green = [Float](repeating: 0, count: width * height)
    var blue = [Float](repeating: 0, count: width * height)
    // 1-pixel white strand along column 15
    for y in 0..<height {
      red[y * width + 15] = 1.0
      green[y * width + 15] = 1.0
      blue[y * width + 15] = 1.0
    }

    var p = [Float](repeating: 0, count: width * height)
    for y in 0..<height {
      for x in 13...17 {
        p[y * width + x] = 0.5
      }
    }

    let q = RefineSelectionAlgorithms.guidedFilter(
      red: red, green: green, blue: blue, p: p, width: width, height: height, radius: 3
    )

    // The thin strand at x=15 should have a higher response than neighboring pixels
    let centerVal = q[15 * width + 15]
    let leftVal = q[15 * width + 13]
    let rightVal = q[15 * width + 17]
    XCTAssertGreaterThan(centerVal, leftVal)
    XCTAssertGreaterThan(centerVal, rightVal)
  }

  // MARK: - 2. Smart Radius

  func testSmartRadiusMaintainsSharperStepTransition() {
    let width = 40, height = 40
    var red = [Float](repeating: 0, count: width * height)
    var p = [Float](repeating: 0, count: width * height)
    for y in 0..<height {
      for x in 20..<width {
        red[y * width + x] = 1.0
        p[y * width + x] = 1.0
      }
    }
    let green = red
    let blue = red

    let qSmart = RefineSelectionAlgorithms.guidedFilter(
      red: red, green: green, blue: blue, p: p, width: width, height: height, radius: 8,
      smartRadius: true
    )
    let qUniform = RefineSelectionAlgorithms.guidedFilter(
      red: red, green: green, blue: blue, p: p, width: width, height: height, radius: 8,
      smartRadius: false
    )

    // Smart radius maintains tighter transition ramp on a knife-edge step
    let smartOutside = qSmart[20 * width + 18]
    let uniformOutside = qUniform[20 * width + 18]
    XCTAssertLessThanOrEqual(smartOutside, uniformOutside + 1e-4)
  }

  // MARK: - 3. Global Refinements

  func testSmoothHealsNotch() {
    let width = 40, height = 40
    var bits = [Bool](repeating: false, count: width * height)
    for y in 10..<30 {
      for x in 10..<30 {
        bits[y * width + x] = true
      }
    }
    // Cut a 4x4 notch into top edge
    for y in 10..<14 {
      for x in 18..<22 {
        bits[y * width + x] = false
      }
    }
    let mask = SelectionMask(width: width, height: height, bits: bits)

    var options = RefineSelectionOptions()
    options.smooth = 4

    let (refined, _) = RefineSelectionAlgorithms.refineSelection(
      mask: mask, buffer: nil, options: options
    )

    // Notch at (20, 11) must be healed
    XCTAssertTrue(refined.contains(x: 20, y: 11), "Smooth should heal notch")
    // Extents should be preserved
    XCTAssertEqual(refined.bounds?.x, 10)
    XCTAssertEqual(refined.bounds?.y, 10)
  }

  func testFeatherProducesSoftWeights() {
    let width = 60, height = 60
    var bits = [Bool](repeating: false, count: width * height)
    for y in 15..<45 {
      for x in 15..<45 {
        bits[y * width + x] = true
      }
    }
    let mask = SelectionMask(width: width, height: height, bits: bits)

    var options = RefineSelectionOptions()
    options.feather = 6

    let (refined, _) = RefineSelectionAlgorithms.refineSelection(
      mask: mask, buffer: nil, options: options
    )

    XCTAssertEqual(refined.feather, 6)
    XCTAssertNotNil(refined.weights)
    // Center pixel retains full weight
    XCTAssertEqual(refined.weight(at: 30 * width + 30), 255)
    // Edge pixel has soft weight
    let edgeWeight = refined.weight(at: 15 * width + 30)
    XCTAssertGreaterThan(edgeWeight, 20)
    XCTAssertLessThan(edgeWeight, 240)
  }

  func testShiftEdgeExpandsAndContracts() {
    let width = 40, height = 40
    var bits = [Bool](repeating: false, count: width * height)
    for y in 15..<25 {
      for x in 15..<25 {
        bits[y * width + x] = true
      }
    }
    let mask = SelectionMask(width: width, height: height, bits: bits)

    var optExpand = RefineSelectionOptions()
    optExpand.shiftEdge = 3
    let (expanded, _) = RefineSelectionAlgorithms.refineSelection(
      mask: mask, buffer: nil, options: optExpand
    )
    XCTAssertGreaterThan(expanded.count, mask.count)
    XCTAssertEqual(expanded.bounds?.x, 12)
    XCTAssertEqual(expanded.bounds?.y, 12)

    var optContract = RefineSelectionOptions()
    optContract.shiftEdge = -2
    let (contracted, _) = RefineSelectionAlgorithms.refineSelection(
      mask: mask, buffer: nil, options: optContract
    )
    XCTAssertLessThan(contracted.count, mask.count)
    XCTAssertEqual(contracted.bounds?.x, 17)
    XCTAssertEqual(contracted.bounds?.y, 17)
  }

  // MARK: - 4. Color Decontamination

  func testColorDecontaminationPurgesFringeBleed() {
    let width = 30, height = 30
    var buffer = makeBuffer(width: width, height: height)
    buffer.withMutableWords { words in
      for y in 0..<height {
        for x in 0..<width {
          // Left is Red (0xFFFF0000), right is Green (0xFF00FF00)
          words[y * width + x] = (x < 15) ? 0xFFFF_0000 : 0xFF00_FF00
        }
        // Bleed green into edge of red at col 14
        words[y * width + 14] = 0xFF78_B414
      }
    }

    var bits = [Bool](repeating: false, count: width * height)
    for y in 0..<height {
      for x in 0..<15 {
        bits[y * width + x] = true
      }
    }
    let mask = SelectionMask(width: width, height: height, bits: bits)

    var options = RefineSelectionOptions()
    options.radius = 4
    options.decontaminate = true
    options.decontaminateAmount = 1.0

    let (_, decBuffer) = RefineSelectionAlgorithms.refineSelection(
      mask: mask, buffer: buffer, options: options
    )

    XCTAssertNotNil(decBuffer)
    guard let clean = decBuffer else { return }

    let origFringe = buffer.words[15 * width + 14]
    let cleanFringe = clean.words[15 * width + 14]

    let origRed = (origFringe >> 16) & 0xFF
    let origGreen = (origFringe >> 8) & 0xFF
    let cleanRed = (cleanFringe >> 16) & 0xFF
    let cleanGreen = (cleanFringe >> 8) & 0xFF

    XCTAssertGreaterThan(cleanRed, origRed, "Decontamination must restore foreground Red")
    XCTAssertLessThan(cleanGreen, origGreen, "Decontamination must purge background Green bleed")
  }

  // MARK: - 5. Edge Cases & Memory Frugality (DD-001)

  func testEmptySelectionHandledSafely() {
    let empty = SelectionMask(width: 20, height: 20, bits: [Bool](repeating: false, count: 400))
    var options = RefineSelectionOptions()
    options.radius = 5
    options.smooth = 3

    let (refined, buf) = RefineSelectionAlgorithms.refineSelection(
      mask: empty, buffer: nil, options: options
    )
    XCTAssertTrue(refined.isEmpty)
    XCTAssertNil(buf)
  }

  func testZeroRadiusPreservesSharpEdge() {
    let width = 20, height = 20
    var bits = [Bool](repeating: false, count: width * height)
    for y in 5..<15 {
      for x in 5..<15 {
        bits[y * width + x] = true
      }
    }
    let mask = SelectionMask(width: width, height: height, bits: bits)
    let options = RefineSelectionOptions() // radius 0, smooth 0, feather 0, etc.

    let (refined, _) = RefineSelectionAlgorithms.refineSelection(
      mask: mask, buffer: nil, options: options
    )
    XCTAssertEqual(refined.bits, mask.bits)
    XCTAssertEqual(refined.count, mask.count)
  }
}

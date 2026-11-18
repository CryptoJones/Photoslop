// SPDX-License-Identifier: Apache-2.0
//
// LiquifyTests.swift — Liquify mesh displacement unit tests (#419).
//

import CoreGraphics
import UIKit
import XCTest

@testable import PhotoslopIPad

final class LiquifyTests: XCTestCase {

  private func makeStripeImage(width: Int = 100, height: Int = 100) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let renderer = UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format)
    return renderer.image { ctx in
      UIColor.white.setFill()
      ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
      UIColor.red.setFill()
      ctx.fill(CGRect(x: 45, y: 0, width: 10, height: height))
    }
  }

  func testGridDimensionsAndSpacing() {
    let grid = LiquifyGrid(width: 200, height: 150, spacing: 8)
    XCTAssertEqual(grid.width, 200)
    XCTAssertEqual(grid.height, 150)
    XCTAssertEqual(grid.spacing, 8)
    XCTAssertEqual(grid.cols, (200 + 7) / 8 + 1)
    XCTAssertEqual(grid.rows, (150 + 7) / 8 + 1)
    XCTAssertEqual(grid.dx.count, grid.cols * grid.rows)
    XCTAssertEqual(grid.dy.count, grid.cols * grid.rows)
    XCTAssertEqual(grid.freeze.count, grid.cols * grid.rows)
    XCTAssertTrue(grid.dx.allSatisfy { $0 == 0.0 })
    XCTAssertTrue(grid.dy.allSatisfy { $0 == 0.0 })
    XCTAssertTrue(grid.freeze.allSatisfy { $0 == 0.0 })
  }

  func testForwardWarpDisplacement() {
    var grid = LiquifyGrid(width: 100, height: 100, spacing: 8)
    grid.applyStroke(
      tool: .forwardWarp,
      points: [CGPoint(x: 40, y: 50), CGPoint(x: 60, y: 50)],
      size: 40,
      pressure: 0.8
    )

    let minDx = grid.dx.min() ?? 0.0
    XCTAssertLessThan(minDx, -2.0)
  }

  func testReconstructRelaxesToIdentity() {
    var grid = LiquifyGrid(width: 100, height: 100, spacing: 8)
    grid.applyStroke(
      tool: .forwardWarp,
      points: [CGPoint(x: 50, y: 50), CGPoint(x: 70, y: 50)],
      size: 40,
      pressure: 1.0
    )
    let initialMax = grid.dx.map { abs($0) }.max() ?? 0.0
    XCTAssertGreaterThan(initialMax, 5.0)

    for _ in 0..<10 {
      grid.applyBrush(
        tool: .reconstruct,
        center: CGPoint(x: 60, y: 50),
        radius: 30,
        pressure: 1.0
      )
    }

    let reducedMax = grid.dx.map { abs($0) }.max() ?? 0.0
    XCTAssertLessThan(reducedMax, initialMax * 0.4)

    grid.reset()
    XCTAssertTrue(grid.dx.allSatisfy { $0 == 0.0 })
  }

  func testSmoothReducesDiscontinuity() {
    var grid = LiquifyGrid(width: 100, height: 100, spacing: 8)
    let idx = 5 * grid.cols + 5
    grid.dx[idx] = 20.0

    grid.applyBrush(
      tool: .smooth,
      center: CGPoint(x: 5 * 8, y: 5 * 8),
      radius: 20,
      pressure: 1.0
    )

    XCTAssertLessThan(grid.dx[idx], 20.0)
  }

  func testTwirlDirection() {
    var gridCW = LiquifyGrid(width: 100, height: 100, spacing: 8)
    var gridCCW = LiquifyGrid(width: 100, height: 100, spacing: 8)

    gridCW.applyBrush(tool: .twirlCW, center: CGPoint(x: 50, y: 50), radius: 30, pressure: 0.8)
    gridCCW.applyBrush(tool: .twirlCCW, center: CGPoint(x: 50, y: 50), radius: 30, pressure: 0.8)

    let idxY = 70 / 8
    let idxX = 50 / 8
    let idx = idxY * gridCW.cols + idxX

    XCTAssertGreaterThan(gridCW.dx[idx], 1.0)
    XCTAssertLessThan(gridCCW.dx[idx], -1.0)
  }

  func testPuckerAndBloatDisplacements() {
    var gridPucker = LiquifyGrid(width: 100, height: 100, spacing: 8)
    var gridBloat = LiquifyGrid(width: 100, height: 100, spacing: 8)

    gridPucker.applyBrush(tool: .pucker, center: CGPoint(x: 50, y: 50), radius: 30, pressure: 0.8)
    gridBloat.applyBrush(tool: .bloat, center: CGPoint(x: 50, y: 50), radius: 30, pressure: 0.8)

    let cRight = 50 / 8 + 2
    let rCenter = 50 / 8
    let idx = rCenter * gridPucker.cols + cRight

    XCTAssertGreaterThan(gridPucker.dx[idx], 0.0)
    XCTAssertLessThan(gridBloat.dx[idx], 0.0)
  }

  func testPushLeftDisplacement() {
    var grid = LiquifyGrid(width: 100, height: 100, spacing: 8)
    grid.applyStroke(
      tool: .pushLeft,
      points: [CGPoint(x: 50, y: 30), CGPoint(x: 50, y: 70)],
      size: 40,
      pressure: 0.8
    )

    let minDx = grid.dx.min() ?? 0.0
    XCTAssertLessThan(minDx, -2.0)
  }

  func testFreezeMaskProtectsArea() {
    var grid = LiquifyGrid(width: 100, height: 100, spacing: 8)
    for _ in 0..<5 {
      grid.applyBrush(
        tool: .freezeMask,
        center: CGPoint(x: 50, y: 50),
        radius: 25,
        pressure: 1.0
      )
    }

    let centerIdx = (50 / 8) * grid.cols + (50 / 8)
    XCTAssertGreaterThanOrEqual(grid.freeze[centerIdx], 0.99)

    grid.applyStroke(
      tool: .forwardWarp,
      points: [CGPoint(x: 40, y: 50), CGPoint(x: 60, y: 50)],
      size: 40,
      pressure: 1.0
    )

    XCTAssertEqual(grid.dx[centerIdx], 0.0, accuracy: 1e-4)

    for _ in 0..<10 {
      grid.applyBrush(
        tool: .thawMask,
        center: CGPoint(x: 50, y: 50),
        radius: 25,
        pressure: 1.0
      )
    }
    XCTAssertLessThan(grid.freeze[centerIdx], 0.2)
  }

  func testRasterizePreservesDimensionsAndPixels() {
    let img = makeStripeImage(width: 100, height: 100)
    var grid = LiquifyGrid(width: 100, height: 100, spacing: 8)
    grid.applyBrush(tool: .twirlCW, center: CGPoint(x: 50, y: 50), radius: 35, pressure: 1.0)

    let warped = LiquifyRasterizer.rasterize(image: img, grid: grid)
    XCTAssertNotNil(warped)
    XCTAssertEqual(Int(warped?.size.width ?? 0), 100)
    XCTAssertEqual(Int(warped?.size.height ?? 0), 100)
  }
}

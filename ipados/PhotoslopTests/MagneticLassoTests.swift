// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Tests for Magnetic Lasso and Live-wire edge snapping (Issue #416).
@MainActor
final class MagneticLassoTests: XCTestCase {

  /// Stepped edge image: 80x50, black left / white right stepping from x=30 to x=45 at y=25.
  private func steppedEdgeImage(width w: Int = 80, height h: Int = 50) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    let renderer = UIGraphicsImageRenderer(size: CGSize(width: w, height: h), format: format)
    return renderer.image { ctx in
      let cg = ctx.cgContext
      cg.setFillColor(UIColor.black.cgColor)
      cg.fill(CGRect(x: 0, y: 0, width: w, height: h))

      cg.setFillColor(UIColor.white.cgColor)
      cg.fill(CGRect(x: 30, y: 0, width: w - 30, height: 25))
      cg.fill(CGRect(x: 45, y: 25, width: w - 45, height: h - 25))
    }
  }

  func testLivewireFollowsSteppedEdge() throws {
    let img = steppedEdgeImage()
    let path = LivewireAlgorithms.livewirePath(
      image: img,
      from: CGPoint(x: 30, y: 4),
      to: CGPoint(x: 45, y: 46),
      width: 20
    )

    XCTAssertFalse(path.isEmpty)
    XCTAssertEqual(path.first, CGPoint(x: 30, y: 4))
    XCTAssertEqual(path.last, CGPoint(x: 45, y: 46))

    var onEdge = 0
    for pt in path {
      let boundaryX: CGFloat = pt.y < 25 ? 30 : 45
      if abs(pt.x - boundaryX) <= 2 || (pt.y >= 23 && pt.y <= 27) {
        onEdge += 1
      }
    }
    let ratio = Double(onEdge) / Double(path.count)
    XCTAssertGreaterThan(ratio, 0.8, "Livewire path must hug the stepped edge boundary")
  }

  func testLivewireFallbackOnLargeCorridor() throws {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    let renderer = UIGraphicsImageRenderer(size: CGSize(width: 600, height: 600), format: format)
    let bigImg = renderer.image { ctx in
      ctx.cgContext.setFillColor(UIColor.white.cgColor)
      ctx.cgContext.fill(CGRect(x: 0, y: 0, width: 600, height: 600))
    }

    let fallback = LivewireAlgorithms.livewirePath(
      image: bigImg,
      from: CGPoint(x: 0, y: 0),
      to: CGPoint(x: 599, y: 599),
      maxArea: 60000
    )
    XCTAssertEqual(fallback, [CGPoint(x: 0, y: 0), CGPoint(x: 599, y: 599)])
  }

  func testSelectMagneticLassoOnStore() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 60, height: 60))

    let points = [
      CGPoint(x: 10, y: 10),
      CGPoint(x: 30, y: 10),
      CGPoint(x: 30, y: 30),
      CGPoint(x: 10, y: 30),
    ]
    store.selectMagneticLasso(points, combine: .replace)

    let sel = try XCTUnwrap(store.selection)
    XCTAssertFalse(sel.isEmpty)
    let bounds = try XCTUnwrap(sel.bounds)
    XCTAssertEqual(bounds.width, 20)
    XCTAssertEqual(bounds.height, 20)
  }

  func testBrushToolMagneticLassoProperties() {
    let tool = BrushTool.magneticLasso
    XCTAssertEqual(tool.displayName, "Magnetic Lasso")
    XCTAssertEqual(tool.family, .select)
    XCTAssertTrue(tool.selectsByDrag)
    XCTAssertTrue(tool.selects)
    XCTAssertFalse(tool.actsOnTap)
  }
}

// SPDX-License-Identifier: Apache-2.0
import PencilKit
import UIKit
import XCTest

@testable import PhotoslopIPad

final class BrushToolTests: XCTestCase {
  func testInkingBrushesMapToTheirPencilKitInkType() {
    let expected: [BrushTool: PKInkingTool.InkType] = [
      .pen: .pen,
      .pencil: .pencil,
      .marker: .marker,
    ]
    for (brush, inkType) in expected {
      let tool = brush.pkTool(color: .red, width: 12)
      let inking = try? XCTUnwrap(tool as? PKInkingTool)
      XCTAssertEqual(inking?.inkType, inkType, "\(brush.displayName) used the wrong ink")
      XCTAssertEqual(inking?.width, 12)
    }
  }

  func testEraserProducesABitmapEraserRatherThanInk() {
    let tool = BrushTool.eraser.pkTool(color: .red, width: 12)
    XCTAssertNil(tool as? PKInkingTool)
    XCTAssertTrue(tool is PKEraserTool)
  }

  /// The bug this type was introduced for: `.pen` ink tracks force only, so a
  /// tilted Apple Pencil drew an identical stroke. Pencil and Marker are the
  /// ink types that read altitude and azimuth.
  func testOnlyPencilAndMarkerRespondToTilt() {
    XCTAssertTrue(BrushTool.pencil.respondsToTilt)
    XCTAssertTrue(BrushTool.marker.respondsToTilt)
    XCTAssertFalse(BrushTool.pen.respondsToTilt)
    XCTAssertFalse(BrushTool.eraser.respondsToTilt)
    XCTAssertTrue(
      BrushTool.allCases.contains { $0.respondsToTilt },
      "at least one brush must vary with Pencil tilt"
    )
  }

  func testOnlyInkingBrushesUseTheColorAndWidthControls() {
    XCTAssertTrue(BrushTool.pen.usesInk)
    XCTAssertTrue(BrushTool.pencil.usesInk)
    XCTAssertTrue(BrushTool.marker.usesInk)
    XCTAssertFalse(BrushTool.eraser.usesInk)
    // The bucket takes the ink but not the width: a fill has no stroke.
    XCTAssertTrue(BrushTool.bucket.usesInk)
    XCTAssertFalse(BrushTool.bucket.usesWidth)
    XCTAssertTrue(BrushTool.pen.usesWidth)
    XCTAssertFalse(BrushTool.eraser.usesWidth)
  }

  func testOnlyTheBucketFillsOnTap() {
    XCTAssertEqual(BrushTool.allCases.filter(\.fillsOnTap), [.bucket])
    XCTAssertFalse(BrushTool.bucket.respondsToTilt)
  }

  func testOnlyTheWandSelectsOnTapAndTakesNoInk() {
    XCTAssertEqual(BrushTool.allCases.filter(\.selectsOnTap), [.wand])
    XCTAssertEqual(BrushTool.allCases.filter(\.actsOnTap), [.bucket, .wand, .eyedropper])
    // The bucket and the wand grow a region, so they take a tolerance; the
    // eyedropper (#379) taps too but reads a single pixel, so it does not.
    XCTAssertEqual(BrushTool.allCases.filter(\.usesTolerance), [.bucket, .wand])
    // The wand paints nothing, so no ink.
    XCTAssertFalse(BrushTool.wand.usesInk)
    XCTAssertFalse(BrushTool.wand.usesWidth)
    XCTAssertFalse(BrushTool.wand.respondsToTilt)
  }

  func testTheMarqueeAndLassoSelectByDragAndTakeNoInk() {
    XCTAssertEqual(BrushTool.allCases.filter(\.selectsByDrag), [.rectSelect, .lasso])
    XCTAssertEqual(BrushTool.allCases.filter(\.selects), [.wand, .rectSelect, .lasso])
    for tool in [BrushTool.rectSelect, .lasso] {
      XCTAssertFalse(tool.actsOnTap, "\(tool) is a drag, not a tap")
      XCTAssertFalse(tool.usesTolerance)
      XCTAssertFalse(tool.usesInk)
      XCTAssertFalse(tool.usesWidth)
      XCTAssertFalse(tool.respondsToTilt)
      // Armed, the canvas is disabled; the pen it installs never draws.
      XCTAssertTrue(tool.pkTool(color: .black, width: 4) is PKInkingTool)
    }
  }

  func testTheEraserIsAPixelEraserUnderASelection() throws {
    // Under a selection (#370) the strokes are pixels by the time they land,
    // so the eraser is a pen of the bitmap eraser's width in the frosted
    // preview ink, whose coverage is taken out of the layer.
    let tool = try XCTUnwrap(
      BrushTool.eraser.pkTool(color: .black, width: 4, clippedToSelection: true) as? PKInkingTool)
    XCTAssertEqual(tool.inkType, .pen)
    XCTAssertEqual(tool.color.cgColor.alpha, BrushTool.selectionEraserInk.cgColor.alpha, accuracy: 0.01)
    XCTAssertEqual(tool.width, PKEraserTool.EraserType.fixedWidthBitmap.defaultWidth)
    XCTAssertTrue(BrushTool.eraser.pkTool(color: .black, width: 4) is PKEraserTool)
    // The brushes are the same pen either way: the clip is on the canvas.
    let pen = try XCTUnwrap(
      BrushTool.pen.pkTool(color: .red, width: 9, clippedToSelection: true) as? PKInkingTool)
    XCTAssertEqual(pen.inkType, .pen)
    XCTAssertEqual(pen.width, 9)
  }

  func testEveryBrushIsPresentableInTheToolStrip() {
    XCTAssertEqual(BrushTool.allCases.first, .pen, "Pen stays the default brush")
    for brush in BrushTool.allCases {
      XCTAssertFalse(brush.displayName.isEmpty)
      XCTAssertNotNil(
        UIImage(systemName: brush.symbolName),
        "\(brush.displayName) has no SF Symbol named \(brush.symbolName)"
      )
      XCTAssertEqual(brush.id, brush.rawValue)
    }
  }
}

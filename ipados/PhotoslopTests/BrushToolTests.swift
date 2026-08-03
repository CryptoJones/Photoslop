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

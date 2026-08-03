// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import XCTest

@testable import PhotoslopIPad

final class CanvasPresetTests: XCTestCase {
  func testEveryFixedPresetIsACreatableCanvas() throws {
    for preset in CanvasPreset.allCases where preset != .custom {
      let size = try XCTUnwrap(preset.size, "\(preset.displayName) has no size")
      XCTAssertTrue(
        ProjectArchive.isValidCanvas(size),
        "\(preset.displayName) at \(size) is not a valid canvas")
    }
  }

  func testCustomIsTheOnlyPresetWithoutAFixedSize() {
    XCTAssertNil(CanvasPreset.custom.size)
    for preset in CanvasPreset.allCases where preset != .custom {
      XCTAssertNotNil(preset.size, "\(preset.displayName)")
    }
  }

  func testValidatedRejectsSizesTheProjectCouldNotSave() {
    XCTAssertNil(CanvasPreset.validated(width: 0, height: 100))
    XCTAssertNil(CanvasPreset.validated(width: 100, height: 0))
    XCTAssertNil(CanvasPreset.validated(width: -10, height: 10))
    XCTAssertNil(
      CanvasPreset.validated(
        width: ProjectArchive.maximumDimension + 1, height: 10),
      "a side past the per-side cap must be refused")
    XCTAssertNil(
      CanvasPreset.validated(width: 16_000, height: 16_000),
      "256 megapixels is past the total-pixel cap")
  }

  func testValidatedAcceptsSizesAtTheLimits() throws {
    let side = try XCTUnwrap(CanvasPreset.validated(width: 1, height: 1))
    XCTAssertEqual(side, CGSize(width: 1, height: 1))

    let wide = try XCTUnwrap(
      CanvasPreset.validated(width: ProjectArchive.maximumDimension, height: 1))
    XCTAssertEqual(wide.width, CGFloat(ProjectArchive.maximumDimension))
  }

  func testSubtitleReportsPixelDimensions() {
    XCTAssertEqual(CanvasPreset.hd.subtitle, "1920 by 1080 px")
    XCTAssertEqual(CanvasPreset.custom.subtitle, "Enter any size")
  }

  func testStandardPresetMatchesTheDefaultDocumentSize() throws {
    let store = EditorStore()
    let standard = try XCTUnwrap(CanvasPreset.standard.size)
    XCTAssertEqual(
      store.canvasSize, standard,
      "the Standard preset should be what a new document already uses")
  }
}

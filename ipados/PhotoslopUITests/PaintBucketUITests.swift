// SPDX-License-Identifier: Apache-2.0
import XCTest

/// The paint bucket (#325) as a running app sees it: pick the tool, tap the
/// canvas, and the layer's pixels change.
///
/// The unit tests prove the fill is the desktop's fill; this proves the tap
/// reaches it. XCUITest reads the accessibility tree rather than the screen,
/// so the app exposes one pixel of the active layer under
/// `-PhotoslopPixelProbe` (see `EditorView.pixelProbe`), and this test reads
/// it before and after.
final class PaintBucketUITests: UITestCase {
  func testBucketTapFillsTheActiveLayer() {
    let app = openEditor()
    // A fresh document, so the active layer is the white Background rather
    // than whatever an earlier test left selected — a text layer, say, which
    // the bucket refuses by design.
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.openNewDocument()
    app.selectTool("Bucket")

    // The tolerance slider takes the width slider's slot for the bucket.
    XCTAssertTrue(
      app.sliders["Tolerance"].firstMatch.waitForExistence(timeout: 10),
      "the bucket's tolerance control is not on the strip")
    XCTAssertFalse(app.sliders["Brush width"].firstMatch.exists, "a fill has no brush width")

    let probe = app.staticTexts["Pixel probe"].firstMatch
    XCTAssertTrue(probe.waitForExistence(timeout: 10), "the pixel probe is not exposed")
    let before = probe.value as? String
    XCTAssertEqual(before, "FFFFFFFF", "a new document's background is opaque white")

    // A finger tap on the canvas: the bucket is a tap tool, so it fills whether
    // or not finger drawing is on.
    let canvas = app.descendants(matching: .any)
      .matching(NSPredicate(format: "label == %@", "Editable image canvas")).firstMatch
    XCTAssertTrue(canvas.waitForExistence(timeout: 15), "no canvas on screen")
    canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()

    let changed = NSPredicate(format: "value != %@", "FFFFFFFF")
    let expectation = XCTNSPredicateExpectation(predicate: changed, object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [expectation], timeout: 20), .completed,
      "the centre pixel is still white after the bucket tap")
    // Black ink is the default swatch: premultiplied black at whatever opacity
    // the ink is set to has zero colour bytes.
    XCTAssertTrue(
      (probe.value as? String ?? "").hasSuffix("000000"),
      "the filled pixel is not black ink: \(probe.value ?? "nil")")

    // One undo step, named for the tool.
    let undo = app.buttons["Undo"].firstMatch
    XCTAssertTrue(undo.waitForExistence(timeout: 10))
    XCTAssertTrue(undo.isEnabled, "the fill did not register an undo step")
    undo.tap()
    let restored = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value == %@", "FFFFFFFF"), object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [restored], timeout: 20), .completed,
      "undo did not restore the white background")

    // Leave the editor on the default tool for whoever runs next.
    app.selectTool("Pen")
  }
}

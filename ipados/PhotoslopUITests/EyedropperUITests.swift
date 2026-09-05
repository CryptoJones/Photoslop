// SPDX-License-Identifier: Apache-2.0
import XCTest

/// The Eyedropper (#379) driven through the real UI.
///
/// The unit tests prove `sampleColor` returns the right colour; this proves the
/// tool is reachable from the strip and that what it samples actually reaches
/// the ink. The check is deliberately indirect, because the swatch does not
/// publish its colour to accessibility: a new document is white and the default
/// ink is black, so sampling the white canvas and then filling with the Bucket
/// must leave the centre pixel WHITE. If the eyedropper were a no-op the ink
/// would still be black and the same fill would turn it black.
final class EyedropperUITests: UITestCase {
  func testSampledColourBecomesTheInk() {
    let app = openEditor()
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.openNewDocument()

    let probe = app.staticTexts["Pixel probe"].firstMatch
    XCTAssertTrue(probe.waitForExistence(timeout: 10), "the pixel probe is not exposed")
    XCTAssertEqual(probe.value as? String, "FFFFFFFF", "a new document's background is white")

    app.selectTool("Eyedropper")

    // It reads one pixel, so neither a width nor a tolerance belongs to it.
    XCTAssertFalse(app.sliders["Brush width"].firstMatch.exists, "the eyedropper has no width")
    XCTAssertFalse(
      app.sliders["Tolerance"].firstMatch.exists, "one pixel has no region to grow")
    // The swatch stays: it is where the sampled colour lands.
    XCTAssertTrue(
      app.buttons["Ink color"].firstMatch.exists, "the ink swatch left with the brush")

    let canvas = app.descendants(matching: .any)
      .matching(NSPredicate(format: "label == %@", "Editable image canvas")).firstMatch
    XCTAssertTrue(canvas.waitForExistence(timeout: 15), "no canvas on screen")
    canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()

    // Sampling writes no pixels.
    XCTAssertEqual(probe.value as? String, "FFFFFFFF", "the eyedropper painted something")

    // Now prove the ink actually changed, by spending it.
    app.selectTool("Bucket")
    canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()

    let stayedWhite = NSPredicate(format: "value == %@", "FFFFFFFF")
    let expectation = XCTNSPredicateExpectation(predicate: stayedWhite, object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [expectation], timeout: 20), .completed,
      """
      the fill did not use the sampled white — the ink is still the default \
      black, so the eyedropper's tap never reached it
      """)
  }
}

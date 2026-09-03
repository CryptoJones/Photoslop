// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Stages a document worth photographing for the App Store (#257).
///
/// Not a test of anything: it draws a few strokes and places a line of text so
/// that the *next* launch restores an editor showing actual artwork, and the
/// screenshots the listing needs can be taken with `simctl io screenshot`
/// instead of a hand on every device size. Skipped everywhere unless asked
/// for by name — `TEST_RUNNER_PHOTOSLOP_STAGE_SCREENSHOTS=1` on the
/// xcodebuild invocation — so CI never pays for it.
final class StoreScreenshotStagingUITests: UITestCase {
  func testStageADocumentForStoreScreenshots() throws {
    try XCTSkipUnless(
      ProcessInfo.processInfo.environment["PHOTOSLOP_STAGE_SCREENSHOTS"] == "1",
      "screenshot staging runs only when explicitly asked for; see #257")

    let app = openEditor()
    app.selectTool("Pen")

    // Synthesized touches are finger touches, and finger drawing starts off
    // on an iPad — without this every drag below pans the canvas instead of
    // painting on it. A phone starts with it on (#313), which is why this
    // reads the toggle rather than flipping it.
    app.setFingerDrawing(true)

    // A little skyline of strokes, by coordinate *within the drawable canvas*
    // — window fractions were tried first and mostly landed on the grey
    // around the canvas, which pans the scroll view instead of painting.
    let canvas = app.descendants(matching: .any)
      .matching(NSPredicate(format: "label == %@", "Editable image canvas")).firstMatch
    XCTAssertTrue(canvas.waitForExistence(timeout: 15), "no drawable canvas on screen")
    func at(_ dx: CGFloat, _ dy: CGFloat) -> XCUICoordinate {
      canvas.coordinate(withNormalizedOffset: CGVector(dx: dx, dy: dy))
    }
    let strokes: [((CGFloat, CGFloat), (CGFloat, CGFloat))] = [
      ((0.20, 0.70), (0.32, 0.30)),
      ((0.32, 0.30), (0.44, 0.70)),
      ((0.44, 0.70), (0.56, 0.22)),
      ((0.56, 0.22), (0.68, 0.70)),
      ((0.15, 0.78), (0.85, 0.78)),
    ]
    for ((fromX, fromY), (toX, toY)) in strokes {
      at(fromX, fromY).press(
        forDuration: 0.15,
        thenDragTo: at(toX, toY),
        withVelocity: .slow,
        thenHoldForDuration: 0.1)
    }

    app.addText("Proudly Made in Nebraska")
    // Placing text leaves the move-it banner up; the screenshot wants the
    // editor's ordinary chrome.
    let done = app.buttons["Done"].firstMatch
    if done.waitForExistence(timeout: 10), done.isHittable {
      done.tap()
    }

    // The document autosaves; reaching the editor again is enough to know the
    // staging left the app in the state the screenshots want.
    XCTAssertTrue(
      app.navigationBars.buttons["Export Image"].firstMatch.waitForExistence(timeout: 30))

    // The screenshot rides the result bundle rather than being raced from
    // outside: pass -resultBundlePath, then
    // `xcrun xcresulttool export attachments` hands back "editor.png" at the
    // device's native pixels.
    let screenshot = XCUIScreen.main.screenshot()
    let attachment = XCTAttachment(screenshot: screenshot)
    attachment.name = "editor"
    attachment.lifetime = .keepAlways
    add(attachment)
  }
}

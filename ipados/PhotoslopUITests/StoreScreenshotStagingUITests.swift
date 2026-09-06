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

    // Import the artwork rather than scribbling one.
    //
    // The screenshots this replaces drew a few strokes by hand and looked it:
    // the canvas renders zoom-to-fit, so on a phone a 1024-wide document is a
    // couple of hundred points across and a default 8px stroke lands
    // sub-pixel — a hairline scratch on a postage stamp, in the middle of a
    // grey screen. That reads as an empty app, which is a listing problem and
    // an App Review one.
    //
    // `scripts/stage-store-screenshots.sh` puts `docs/appstore/artwork` into
    // the simulator's photo library first, so the picture below is the
    // project's own artwork. Importing it also puts the feature being
    // photographed on screen: a photo brought in as its own layer.
    XCTAssertTrue(app.openLayerList(), "the layer list could not be reached")
    let addPhoto = app.buttons["New layer from photo"].firstMatch
    XCTAssertTrue(addPhoto.waitForExistence(timeout: 15), "no way to import a photo")
    addPhoto.tap()

    XCTAssertTrue(app.buttons["Choose"].waitForExistence(timeout: 20), "no import source sheet")
    app.buttons["Choose"].tap()

    let thumbnails = app.images.matching(NSPredicate(format: "label BEGINSWITH 'Photo,'"))
    try XCTSkipUnless(
      thumbnails.element(boundBy: 0).waitForExistence(timeout: 25),
      "the simulator's photo library is empty; run scripts/stage-store-screenshots.sh")
    // The picker is a remote view and reports thumbnails as not hittable, so
    // tap the middle of the element's own frame.
    thumbnails.element(boundBy: 0)
      .coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    // Named `addButton`, not `add`: a local called `add` shadows XCTest's own
    // `add(_:)` and the attachment at the end of this test silently stops
    // compiling.
    let addButton = app.buttons["Add"].firstMatch
    if addButton.waitForExistence(timeout: 10) { addButton.tap() }

    // The import lands behind a placement box; committing it leaves the
    // editor's ordinary chrome, which is what the listing should show.
    let place = app.buttons["Apply Placement"].firstMatch
    XCTAssertTrue(place.waitForExistence(timeout: 30), "the placement box never appeared")
    place.tap()

    // Committing the placement can raise "the image hangs over the canvas".
    // Answer it, or the placement bar stays up and the screenshot catches the
    // placement chrome instead of the editor's.
    let crop = app.buttons["Crop to Canvas"].firstMatch
    if crop.waitForExistence(timeout: 5) { crop.tap() }

    if place.exists {
      // A second, deliberate tap on the button's own centre. The bar sits at
      // the bottom of a regular-width window where the first tap can land on
      // the safe-area inset rather than the control.
      place.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
      if crop.waitForExistence(timeout: 5) { crop.tap() }
    }
    XCTAssertFalse(
      place.waitForExistence(timeout: 8),
      "the placement bar is still up: \(app.buttons.allElementsBoundByIndex.map(\.label))")

    // Zoom in so the picture fills the frame. The canvas opens zoomed to fit
    // the scroll view's whole area, which on a tall phone leaves a landscape
    // document sitting small in the middle of a lot of grey — accurate, but it
    // photographs as an empty app.
    let art = app.descendants(matching: .any)
      .matching(NSPredicate(format: "label == %@", "Editable image canvas")).firstMatch
    if art.waitForExistence(timeout: 15) {
      // Adaptive, not a fixed factor: the same pinch that fills a phone
      // overshoots an iPad, where a landscape canvas already spans most of the
      // frame, and crops into the picture. Aim for the canvas covering about
      // four fifths of the window's width, and never zoom out.
      let window = app.windows.firstMatch.frame.width
      let canvasWidth = art.frame.width
      if window > 0, canvasWidth > 0 {
        let wanted = (window * 0.8) / canvasWidth
        if wanted > 1.15 {
          art.pinch(withScale: min(wanted, 3.0), velocity: 1.2)
        }
      }
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

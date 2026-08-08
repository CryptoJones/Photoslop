// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Making layers out of photos.
///
/// What the layers get filled with is `EditorStoreTests`' job — it can assert on
/// pixels and undo. What only a running app can answer is whether the button
/// raises the picker at all, and the answer was no: at compact width the layer
/// list is itself a sheet, and a picker asked for while it is up was silently
/// dropped. The flag flipped and nothing appeared.
///
/// The first version of this test asserted `picker.state == .runningForeground ||
/// cancelButtonExists`, which passed while the feature was broken — the second
/// branch matched the layer sheet's own Cancel. This one waits for the picker's
/// own photo thumbnails, which nothing else on screen can supply.
final class LayerFromPhotoUITests: UITestCase {
  func testNewLayerFromPhotoOpensThePicker() {
    let app = XCUIApplication()
    app.openNewDocument()

    let layers = app.navigationBars.buttons["Layers"]
    if layers.waitForExistence(timeout: 10), layers.isHittable {
      layers.tap()
    }

    let button = app.buttons["New layer from photo"]
    XCTAssertTrue(
      button.waitForExistence(timeout: 15), "there is no way to make a layer from a photo")
    XCTAssertTrue(button.isHittable, "the button is present but cannot be tapped")
    button.tap()

    let thumbnails = app.images.matching(NSPredicate(format: "label BEGINSWITH 'Photo,'"))
    XCTAssertTrue(
      thumbnails.element(boundBy: 0).waitForExistence(timeout: 25),
      "tapping it did not raise the photo picker")
  }

  /// The whole point: photos join the document instead of replacing it.
  func testChosenPhotosBecomeLayersOverWhatIsAlreadyThere() throws {
    let app = XCUIApplication()
    app.openNewDocument()

    let layers = app.navigationBars.buttons["Layers"]
    if layers.waitForExistence(timeout: 10), layers.isHittable {
      layers.tap()
    }
    XCTAssertTrue(app.cells.firstMatch.waitForExistence(timeout: 15))
    let before = app.cells.count

    app.buttons["New layer from photo"].tap()
    let thumbnails = app.images.matching(NSPredicate(format: "label BEGINSWITH 'Photo,'"))
    try XCTSkipUnless(
      thumbnails.element(boundBy: 1).waitForExistence(timeout: 25),
      "this simulator's photo library has fewer than two images")

    // The picker is a remote view and reports thumbnails as not hittable, so tap
    // the middle of each element's own frame.
    for index in 0..<2 {
      thumbnails.element(boundBy: index)
        .coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    }
    XCTAssertTrue(app.buttons["Add"].waitForExistence(timeout: 10), "the picker offers no Add")
    app.buttons["Add"].tap()

    if layers.waitForExistence(timeout: 30), layers.isHittable {
      layers.tap()
    }
    XCTAssertTrue(app.cells.firstMatch.waitForExistence(timeout: 20))
    XCTAssertEqual(
      app.cells.count, before + 2,
      "two photos should add two layers and keep what was already there")
  }
}

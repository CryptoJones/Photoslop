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
  /// Compact width only, deliberately. This is where the bug was — the layer
  /// list is a sheet there, and the picker had to be raised from its dismissal —
  /// and it is the one place the route to the list is deterministic. On a
  /// regular-width iPad the list is a sidebar that presents the picker directly,
  /// and whether that sidebar is showing depends on the model and the
  /// orientation: these tests passed on a 13-inch iPad and failed on whichever
  /// iPad the CI runner offers, reporting "there is no way to make a layer from a
  /// photo" — true of the screen it was looking at, false of the app.
  override func setUp() {
    super.setUp()
    continueAfterFailure = false
  }

  private func skipUnlessCompact() throws {
    try XCTSkipUnless(
      UIDevice.current.userInterfaceIdiom == .phone,
      "the sheet-versus-sidebar difference this covers only exists at compact width")
  }

  func testNewLayerFromPhotoOpensThePicker() throws {
    try skipUnlessCompact()
    let app = XCUIApplication()
    app.openNewDocument()

    XCTAssertTrue(app.openLayerList(), "the layer list could not be reached")

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
    try skipUnlessCompact()
    let app = XCUIApplication()
    app.openNewDocument()

    XCTAssertTrue(app.openLayerList(), "the layer list could not be reached")
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

    XCTAssertTrue(app.openLayerList(), "the layer list could not be reached again")
    XCTAssertTrue(app.cells.firstMatch.waitForExistence(timeout: 20))

    // Wait for the count rather than reading it once. Decoding the photos and
    // inserting the layers is asynchronous, so the layer list is on screen — and
    // its first cell exists — before the new layers are in it. Reading `count`
    // at that moment races the decode and returns the *old* number, which on
    // this machine lands after the work and on a CI runner three times slower
    // lands before it. That is a test bug, not an app one, and it is exactly the
    // sort of thing `-retry-tests-on-failure` was quietly absorbing.
    let grew = NSPredicate(format: "count == %d", before + 2)
    expectation(for: grew, evaluatedWith: app.cells)
    waitForExpectations(timeout: 30) { error in
      XCTAssertNil(
        error,
        """
        two photos should add two layers and keep what was already there — \
        the list settled at \(app.cells.count) cells, expected \(before + 2)
        """)
    }
  }
}

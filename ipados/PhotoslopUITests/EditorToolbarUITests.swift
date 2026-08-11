// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Toolbar reachability, which only a running app can answer.
///
/// The unit tests cover what export produces; they cannot see whether the
/// control that starts it survives a phone-width navigation bar. It did not.
/// Every document action went on one bar, and at iPhone width UIKit collapsed
/// the leading group into an overflow menu and dropped the trailing group —
/// Undo, Redo, Export and About — entirely, leaving no way to export at all.
final class EditorToolbarUITests: UITestCase {
  /// Export has to be on the bar itself on every device, not behind a menu and
  /// certainly not missing: it is the only way to get artwork out of the app.
  func testExportIsOnTheToolbarAndOpensTheExportSheet() {
    let app = openEditor()

    let export = app.navigationBars.buttons["Export Image"]
    XCTAssertTrue(export.waitForExistence(timeout: 10), "Export is not on the navigation bar")
    XCTAssertTrue(export.isHittable, "Export is on the bar but cannot be tapped")
    export.tap()

    XCTAssertTrue(
      app.navigationBars["Export Image"].waitForExistence(timeout: 10),
      "tapping Export did not open the export sheet")
    XCTAssertTrue(app.buttons["Export"].waitForExistence(timeout: 10))
  }

  /// Undo and redo are used mid-drawing, so they have to be one tap wherever
  /// they sit — the navigation bar on iPad, the tool strip on a phone.
  func testUndoAndRedoAreOneTapAway() {
    let app = openEditor()

    for label in ["Undo", "Redo"] {
      let button = app.buttons[label]
      XCTAssertTrue(button.waitForExistence(timeout: 10), "\(label) is not on screen")
      XCTAssertTrue(button.isHittable, "\(label) is on screen but cannot be tapped")
    }
  }

  /// What does not fit on a phone goes in one menu the app controls, rather
  /// than being handed to UIKit's overflow and silently losing half of it.
  func testCompactWidthKeepsEveryOtherActionInOneMenu() throws {
    // The iPad has its own More Actions menu now, but a different one: Layers
    // is a sidebar there rather than a bar button, and About stays on the bar.
    try XCTSkipUnless(
      UIDevice.current.userInterfaceIdiom == .phone,
      "the iPad menu holds a different set; this pins the phone's")
    let app = openEditor()

    XCTAssertTrue(
      app.navigationBars.buttons["Layers"].waitForExistence(timeout: 10),
      "Layers is not on the navigation bar; it is the only route to the layer list on a phone")

    let more = app.navigationBars.buttons["More Actions"]
    XCTAssertTrue(more.waitForExistence(timeout: 10), "the overflow menu is not on the bar")
    more.tap()

    for label in ["New", "Canvas Size", "Add Text", "Import Image", "Photos", "About Photoslop"] {
      XCTAssertTrue(
        app.buttons[label].waitForExistence(timeout: 10), "\(label) is missing from the menu")
    }
  }

  /// Nothing may be handed to UIKit's own overflow, on any device.
  ///
  /// This is the assertion that would have caught the iPad mini: at 744pt the
  /// regular-width layout put five leading and four trailing items on the bar,
  /// UIKit collapsed the trailing group behind a chevron, and Export Image left
  /// the bar. Every other test still passed, because they all reached Export
  /// through a query that does not care whether a button is on the bar or in
  /// the system overflow — the failure only ever showed up as the *next* test
  /// timing out on "the editor never came up".
  func testNothingIsHandedToTheSystemOverflow() {
    let app = openEditor()

    let overflow = app.navigationBars.buttons["OverflowBarButtonItem"]
    XCTAssertFalse(
      overflow.exists,
      """
      UIKit collapsed part of the navigation bar into its own overflow, which \
      hides actions behind an unlabelled chevron. The bar is over budget for \
      this device's width — move something into the app's own More Actions menu.
      """)
  }

  /// The bar's item count may not depend on the document's contents.
  ///
  /// Edit Text and Move Text appear only while a text layer is active, so on a
  /// narrow bar the toolbar fit until the moment someone added text and then
  /// silently overflowed. A bar that changes size as you work is one no test
  /// written before that step can catch, which is why they now live in the
  /// menu at every width that is not provably wide enough.
  func testAddingTextDoesNotPushActionsOffTheBar() {
    let app = openEditor()
    let barItemsBefore = app.navigationBars.buttons.count

    app.addText("Hi")

    XCTAssertFalse(
      app.navigationBars.buttons["OverflowBarButtonItem"].exists,
      "adding a text layer pushed the navigation bar into UIKit's overflow")
    XCTAssertEqual(
      app.navigationBars.buttons.count, barItemsBefore,
      "the navigation bar gained or lost items because a text layer became active")
    XCTAssertTrue(
      app.navigationBars.buttons["Export Image"].exists, "Export left the bar once text was added")
  }

  /// Launch into a fresh document, past the launch scene and the canvas-size
  /// question `DocumentGroup` triggers for the document it creates.
  private func openEditor() -> XCUIApplication {
    let app = XCUIApplication()
    app.openNewDocument()
    return app
  }
}

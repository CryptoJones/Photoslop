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
    try XCTSkipUnless(
      UIDevice.current.userInterfaceIdiom == .phone,
      "iPad shows these actions on the bar itself")
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

  /// Launch into a fresh document, past the launch scene and the canvas-size
  /// question `DocumentGroup` triggers for the document it creates.
  private func openEditor() -> XCUIApplication {
    let app = XCUIApplication()
    let create = app.buttons["Create Document"]
    app.launch()
    if !create.waitForExistence(timeout: 90) {
      app.terminate()
      _ = app.wait(for: .notRunning, timeout: 20)
      app.launch()
    }
    XCTAssertTrue(create.waitForExistence(timeout: 90), "launch scene never appeared")
    create.tap()

    let useThisSize = app.buttons["Use This Size"]
    if useThisSize.waitForExistence(timeout: 60) {
      useThisSize.tap()
      XCTAssertTrue(
        useThisSize.waitForNonExistence(timeout: 30),
        "the canvas size sheet never dismissed")
    }
    XCTAssertTrue(
      app.navigationBars.buttons["Export Image"].waitForExistence(timeout: 90),
      "the editor never came up")

    return app
  }
}

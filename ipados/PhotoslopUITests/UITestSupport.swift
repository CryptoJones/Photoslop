// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Shared setup for the UI tests.
///
/// The app is terminated after every test. XCTest launches a fresh process per
/// test but does not tear down the previous one, so without this a test inherits
/// whatever the last one left on screen — an open sheet, an open menu, a
/// half-dismissed presentation. That is how a test which passes alone and passes
/// in CI fails only when a new test class is added ahead of it in the run order.
class UITestCase: XCTestCase {
  override func setUp() {
    super.setUp()
    continueAfterFailure = false
  }

  override func tearDown() {
    // Terminating is not enough: the next test's `launch()` can race a scene
            // still being torn down, and the app then comes up on a screen nobody
    // asked for. Fifteen consecutive launches inside one test method never
    // flake; launches across method boundaries did, until this waited.
    let app = XCUIApplication()
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 20)
    super.tearDown()
  }
}

extension XCUIApplication {
  /// Open a fresh document and stop on the editor.
  ///
  /// `DocumentGroup` asks a created document for its canvas size, so that sheet
  /// stands between the launch scene and the editor. Dismissing it here keeps
  /// every other test from having to know that.
  func openNewDocument(file: StaticString = #filePath, line: UInt = #line) {
    let create = buttons["Create Document"]
    launch()
    if !create.waitForExistence(timeout: 30) {
      // One retry, for the case where the previous scene had not finished going
      // away when this process launched.
      terminate()
      _ = wait(for: .notRunning, timeout: 20)
      launch()
    }
    XCTAssertTrue(
      create.waitForExistence(timeout: 30), "launch scene never appeared", file: file, line: line)
    create.tap()

    let useThisSize = buttons["Use This Size"]
    if useThisSize.waitForExistence(timeout: 30) {
      useThisSize.tap()
      // Waiting for the sheet to actually leave, not just for the tap to land.
      // A `navigationBars` query run while a sheet is still dismissing can match
      // the sheet's own bar instead of the editor's, so an assertion about the
      // toolbar fails for reasons that have nothing to do with the toolbar. That
      // is what made this suite fail a different test on each run.
      XCTAssertTrue(
        useThisSize.waitForNonExistence(timeout: 15),
        "the canvas size sheet never dismissed", file: file, line: line)
    }

    XCTAssertTrue(
      navigationBars.buttons["Export Image"].waitForExistence(timeout: 30),
      "the editor never came up", file: file, line: line)
  }

  /// Reach About, which sits on the bar at regular width and in the actions menu
  /// at compact width.
  @discardableResult
  func openAbout() -> Bool {
    let about = navigationBars.buttons["About Photoslop"]
    if about.waitForExistence(timeout: 10), about.isHittable {
      about.tap()
    } else {
      let more = navigationBars.buttons["More Actions"]
      guard more.waitForExistence(timeout: 10) else { return false }
      more.tap()
      let menuAbout = buttons["About Photoslop"]
      guard menuAbout.waitForExistence(timeout: 10) else { return false }
      menuAbout.tap()
    }
    // Tapping is not arriving: the sheet has to be up before anything is read
    // off it.
    return navigationBars["About"].waitForExistence(timeout: 15)
  }
}

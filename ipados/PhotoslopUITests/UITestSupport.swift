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
    XCUIApplication().terminate()
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
    launch()
    let create = buttons["Create Document"]
    XCTAssertTrue(
      create.waitForExistence(timeout: 60), "launch scene never appeared", file: file, line: line)
    create.tap()

    let useThisSize = buttons["Use This Size"]
    if useThisSize.waitForExistence(timeout: 30) {
      useThisSize.tap()
    }
  }

  /// Reach About, which sits on the bar at regular width and in the actions menu
  /// at compact width.
  @discardableResult
  func openAbout() -> Bool {
    let about = navigationBars.buttons["About Photoslop"]
    if about.waitForExistence(timeout: 10), about.isHittable {
      about.tap()
      return true
    }
    let more = navigationBars.buttons["More Actions"]
    guard more.waitForExistence(timeout: 10) else { return false }
    more.tap()
    let menuAbout = buttons["About Photoslop"]
    guard menuAbout.waitForExistence(timeout: 10) else { return false }
    menuAbout.tap()
    return true
  }
}

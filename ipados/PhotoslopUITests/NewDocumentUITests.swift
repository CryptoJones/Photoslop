// SPDX-License-Identifier: Apache-2.0
import XCTest

/// The canvas-size question for a newly created document.
///
/// This regressed silently once and the unit suite did not notice, because the
/// flag `EditorStore.init()` sets was never the broken part. Creating a document
/// writes it to disk and reopens it through `init(configuration:)`, so that flag
/// was spent on a store that never reached the screen. Only a running app can
/// tell whether the question actually gets asked.
final class NewDocumentUITests: XCTestCase {
  override func setUp() {
    super.setUp()
    continueAfterFailure = false
  }

  func testCreatingADocumentAsksForItsCanvasSize() {
    let app = XCUIApplication()
    app.launch()

    let create = app.buttons["Create Document"]
    XCTAssertTrue(create.waitForExistence(timeout: 60), "launch scene never appeared")
    create.tap()

    XCTAssertTrue(
      app.buttons["Use This Size"].waitForExistence(timeout: 30),
      "a new document opened without ever asking for its canvas size")
    XCTAssertTrue(app.buttons["Cancel"].exists, "the sheet should be refusable")
  }

  /// Answering has to actually take effect, not just dismiss.
  func testChoosingAPresetResizesTheCanvas() {
    let app = XCUIApplication()
    app.launch()

    let create = app.buttons["Create Document"]
    XCTAssertTrue(create.waitForExistence(timeout: 60), "launch scene never appeared")
    create.tap()

    let useThisSize = app.buttons["Use This Size"]
    XCTAssertTrue(useThisSize.waitForExistence(timeout: 30), "size sheet never appeared")

    let hd = app.buttons["HD, 1920 by 1080 px"]
    XCTAssertTrue(hd.waitForExistence(timeout: 10), "the preset list is missing HD")
    hd.tap()
    useThisSize.tap()

    // About reports the canvas the document actually ended up with.
    // `LabeledContent` folds its label into the value, hence "Size, ...".
    XCTAssertTrue(openAbout(app), "could not reach About")
    XCTAssertTrue(
      app.staticTexts["Size, 1920 x 1080 px"].waitForExistence(timeout: 10),
      "the chosen preset did not resize the canvas")
  }

  /// About sits on the bar on iPad and in the actions menu on a phone.
  private func openAbout(_ app: XCUIApplication) -> Bool {
    let about = app.navigationBars.buttons["About Photoslop"]
    if about.waitForExistence(timeout: 10), about.isHittable {
      about.tap()
      return true
    }
    let more = app.navigationBars.buttons["More Actions"]
    guard more.waitForExistence(timeout: 10) else { return false }
    more.tap()
    let menuAbout = app.buttons["About Photoslop"]
    guard menuAbout.waitForExistence(timeout: 10) else { return false }
    menuAbout.tap()
    return true
  }
}

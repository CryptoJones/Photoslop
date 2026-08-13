// SPDX-License-Identifier: Apache-2.0
import XCTest

/// The canvas-size question for a newly created document.
///
/// This regressed silently once and the unit suite did not notice, because the
/// flag `EditorStore.init()` sets was never the broken part. Creating a document
/// writes it to disk and reopens it through `init(configuration:)`, so that flag
/// was spent on a store that never reached the screen. Only a running app can
/// tell whether the question actually gets asked.
final class NewDocumentUITests: UITestCase {
  /// Both tests here are about creating a document, so neither can reuse the
  /// shared editor: `openLaunchScene()` starts them from a fresh launch and
  /// tells the base class its editor is gone.
  func testCreatingADocumentAsksForItsCanvasSize() {
    let app = openLaunchScene()
    app.buttons["Create Document"].firstMatch.tap()

    XCTAssertTrue(
      app.buttons["Use This Size"].waitForExistence(timeout: 30),
      "a new document opened without ever asking for its canvas size")
    XCTAssertTrue(app.buttons["Cancel"].exists, "the sheet should be refusable")
  }

  /// Answering has to actually take effect, not just dismiss.
  func testChoosingAPresetResizesTheCanvas() {
    let app = openLaunchScene()
    app.buttons["Create Document"].firstMatch.tap()

    let useThisSize = app.buttons["Use This Size"]
    XCTAssertTrue(useThisSize.waitForExistence(timeout: 30), "size sheet never appeared")

    let hd = app.buttons["HD, 1920 by 1080 px"]
    XCTAssertTrue(hd.waitForExistence(timeout: 10), "the preset list is missing HD")
    hd.tap()
    useThisSize.tap()

    // About reports the canvas the document actually ended up with.
    // `LabeledContent` folds its label into the value, hence "Size, ...".
    XCTAssertTrue(app.openAbout(), "could not reach About")
    XCTAssertTrue(
      app.staticTexts["Size, 1920 x 1080 px"].waitForExistence(timeout: 10),
      "the chosen preset did not resize the canvas")
  }
}

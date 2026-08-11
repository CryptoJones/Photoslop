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
  /// Timeouts are generous on purpose. A CI runner takes about three times as
  /// long as this machine for the same test — 75 seconds against 25 — so limits
  /// tuned locally expire there while the app is still coming up, and the failure
  /// reads as "the editor never came up" when the truth is that nobody waited.
  func openNewDocument(file: StaticString = #filePath, line: UInt = #line) {
    let create = buttons["Create Document"]

    // Three attempts at the *launch dance only*, which is the racy part: a
    // relaunch can beat the previous scene's teardown and come up somewhere the
    // test did not ask for. This is deliberately not `-retry-tests-on-failure`
    // — that re-runs the assertions too, so a genuine defect gets three
    // chances to look intermittent. Here every assertion below still runs
    // exactly once, and only getting to the launch scene is retried.
    launchArguments.append("-PhotoslopFreshDocumentStore")
    for attempt in 1...3 {
      if attempt > 1 {
        terminate()
        _ = wait(for: .notRunning, timeout: 30)
      }
      launch()
      if create.waitForExistence(timeout: 90) { break }
    }
    XCTAssertTrue(
      create.waitForExistence(timeout: 30), "launch scene never appeared", file: file, line: line)
    create.tap()

    let useThisSize = buttons["Use This Size"]
    if useThisSize.waitForExistence(timeout: 60) {
      useThisSize.tap()
      // Waiting for the sheet to actually leave, not just for the tap to land.
      // A `navigationBars` query run while a sheet is still dismissing can match
      // the sheet's own bar instead of the editor's, so an assertion about the
      // toolbar fails for reasons that have nothing to do with the toolbar. That
      // is what made this suite fail a different test on each run.
      XCTAssertTrue(
        useThisSize.waitForNonExistence(timeout: 30),
        "the canvas size sheet never dismissed", file: file, line: line)
    }

    XCTAssertTrue(
      navigationBars.buttons["Export Image"].waitForExistence(timeout: 90),
      "the editor never came up", file: file, line: line)
  }

  /// Get the layer list on screen, wherever this device keeps it.
  ///
  /// Three different places: a sheet behind **Layers** at compact width, an
  /// always-visible sidebar on a wide iPad, and a *collapsed* sidebar behind the
  /// system toggle on an iPad in portrait. Only the first two were handled, so
  /// these tests passed locally on a landscape iPad and failed on CI's portrait
  /// one — reported as "there is no way to make a layer from a photo", which was
  /// true of the screen the test was looking at and false of the app.
  @discardableResult
  func openLayerList() -> Bool {
    let marker = buttons["New layer from photo"]
    if marker.exists { return true }

    let layers = navigationBars.buttons["Layers"]
    if layers.waitForExistence(timeout: 30), layers.isHittable {
      layers.tap()
      if marker.waitForExistence(timeout: 30) { return true }
    }

    for toggle in ["ToggleSidebar", "SidebarToggle"] {
      let button = navigationBars.buttons[toggle]
      if button.exists, button.isHittable {
        button.tap()
        if marker.waitForExistence(timeout: 15) { return true }
      }
    }
    return marker.waitForExistence(timeout: 10)
  }

  /// Add a text layer, wherever this width keeps **Add Text**.
  ///
  /// It is on the bar only when the bar is provably wide enough; otherwise it
  /// is in the app's own More Actions menu, alongside Edit Text and Move Text.
  /// A test that cares about the *result* of adding text should not have to
  /// know which.
  func addText(_ body: String, file: StaticString = #filePath, line: UInt = #line) {
    let addText = navigationBars.buttons["Add Text"]
    if addText.waitForExistence(timeout: 10), addText.isHittable {
      addText.tap()
    } else {
      let more = navigationBars.buttons["More Actions"]
      XCTAssertTrue(
        more.waitForExistence(timeout: 10), "neither Add Text nor a menu holding it is on the bar",
        file: file, line: line)
      more.tap()
      let menuItem = buttons["Add Text"]
      XCTAssertTrue(
        menuItem.waitForExistence(timeout: 10), "Add Text is missing from More Actions",
        file: file, line: line)
      menuItem.tap()
    }

    let field = textFields["Type something"]
    XCTAssertTrue(
      field.waitForExistence(timeout: 20), "the text sheet never appeared", file: file, line: line)
    field.tap()
    field.typeText(body)

    let add = buttons["Add"]
    XCTAssertTrue(add.waitForExistence(timeout: 10), "no Add button", file: file, line: line)
    add.tap()
    XCTAssertTrue(
      add.waitForNonExistence(timeout: 20), "the text sheet never dismissed", file: file, line: line)
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

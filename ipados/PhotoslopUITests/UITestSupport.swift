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
  private static var hasWarmedUp = false

  override func setUp() {
    super.setUp()
    continueAfterFailure = false
    Self.warmUpOnce()
  }

  /// Pay the cold-start cost once, before any assertion can be charged for it.
  ///
  /// The first UI test of a run kept failing on CI with "the editor never came
  /// up" — always the first class alphabetically, once per device. Nothing was
  /// wrong with the screen under test: a freshly booted simulator installing the
  /// app, launching it, and creating and opening its first document simply took
  /// longer than the 90-second wait, and whichever test happened to run first
  /// paid for all of it. Raising that timeout would only move the number; the
  /// cost belongs outside the assertions entirely.
  ///
  /// So the whole first-document path runs here, once per test-target
  /// invocation, and deliberately without a single assertion — a warm-up that
  /// cannot fail a test. If the app is genuinely broken the real test says so in
  /// its own words, rather than the failure landing on whichever class sorted
  /// first.
  private static func warmUpOnce() {
    guard !hasWarmedUp else { return }
    hasWarmedUp = true

    let app = XCUIApplication()
    app.launchArguments.append("-PhotoslopFreshDocumentStore")
    app.launch()

    let create = app.buttons["Create Document"].firstMatch
    if create.waitForExistence(timeout: 180) {
      create.tap()
      let useThisSize = app.buttons["Use This Size"].firstMatch
      if useThisSize.waitForExistence(timeout: 120) {
        useThisSize.tap()
        _ = useThisSize.waitForNonExistence(timeout: 60)
      }
      // Reaching the editor is what actually warms the expensive path.
      _ = app.navigationBars.buttons["Export Image"].firstMatch.waitForExistence(timeout: 180)
    }

    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
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
  ///
  /// Timeouts are generous on purpose. A CI runner takes about three times as
  /// long as this machine for the same test — 75 seconds against 25 — so limits
  /// tuned locally expire there while the app is still coming up, and the failure
  /// reads as "the editor never came up" when the truth is that nobody waited.
  ///
  /// Every query here is `.firstMatch`. Without it XCTest resolves the *whole*
  /// query, and between Create Document and the editor the system document
  /// browser is on screen — a hierarchy belonging to another process, and a
  /// large one. On the CI runner that enumeration outran the snapshot timeout
  /// and the run died on `Failed to get matching snapshots: Timed out while
  /// evaluating UI query`, which is not an assertion failure and so cannot be
  /// waited out or retried by the caller. `.firstMatch` stops at the first hit
  /// rather than enumerating, which is the documented remedy.
  func openNewDocument(file: StaticString = #filePath, line: UInt = #line) {
    let create = buttons["Create Document"].firstMatch

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

    // The canvas-size question can be asked more than once, so answer it until
    // it stops being asked rather than assuming a single sheet.
    //
    // Reopening a still-blank document asks again — that is the app's documented
    // behaviour, not a bug: a new document is written to disk and reopened
    // through `init(configuration:)`, and the opening path recognises an
    // untouched one. Answering exactly once was fine while every test inherited
    // the last one's documents, and stopped being fine once the store was
    // emptied at launch, because more of the runs now start from a genuinely new
    // document. The old code tapped the first sheet and then asserted the button
    // was gone, which a second sheet fails by simply existing.
    //
    // Waiting for the sheet to actually leave still matters: a `navigationBars`
    // query run mid-dismissal can match the sheet's own bar instead of the
    // editor's, so a toolbar assertion fails for reasons unrelated to toolbars.
    let useThisSize = buttons["Use This Size"].firstMatch
    for _ in 1...3 {
      guard useThisSize.waitForExistence(timeout: 60) else { break }
      useThisSize.tap()
      guard useThisSize.waitForNonExistence(timeout: 30) else { continue }
      // Gone for now — but give a re-ask a moment to arrive before moving on.
      if !useThisSize.waitForExistence(timeout: 3) { break }
    }
    XCTAssertFalse(
      useThisSize.exists, "the canvas size sheet never dismissed", file: file, line: line)

    XCTAssertTrue(
      navigationBars.buttons["Export Image"].firstMatch.waitForExistence(timeout: 90),
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
    let marker = buttons["New layer from photo"].firstMatch
    if marker.exists { return true }

    let layers = navigationBars.buttons["Layers"].firstMatch
    if layers.waitForExistence(timeout: 30), layers.isHittable {
      layers.tap()
      if marker.waitForExistence(timeout: 30) { return true }
    }

    for toggle in ["ToggleSidebar", "SidebarToggle"] {
      let button = navigationBars.buttons[toggle].firstMatch
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
    let addText = navigationBars.buttons["Add Text"].firstMatch
    if addText.waitForExistence(timeout: 10), addText.isHittable {
      addText.tap()
    } else {
      let more = navigationBars.buttons["More Actions"].firstMatch
      XCTAssertTrue(
        more.waitForExistence(timeout: 10), "neither Add Text nor a menu holding it is on the bar",
        file: file, line: line)
      more.tap()
      let menuItem = buttons["Add Text"].firstMatch
      XCTAssertTrue(
        menuItem.waitForExistence(timeout: 10), "Add Text is missing from More Actions",
        file: file, line: line)
      menuItem.tap()
    }

    let field = textFields["Type something"].firstMatch
    XCTAssertTrue(
      field.waitForExistence(timeout: 20), "the text sheet never appeared", file: file, line: line)
    field.tap()
    field.typeText(body)

    let add = buttons["Add"].firstMatch
    XCTAssertTrue(add.waitForExistence(timeout: 10), "no Add button", file: file, line: line)
    add.tap()
    XCTAssertTrue(
      add.waitForNonExistence(timeout: 20), "the text sheet never dismissed", file: file, line: line)
  }

  /// Reach About, which sits on the bar at regular width and in the actions menu
  /// at compact width.
  @discardableResult
  func openAbout() -> Bool {
    let about = navigationBars.buttons["About Photoslop"].firstMatch
    if about.waitForExistence(timeout: 10), about.isHittable {
      about.tap()
    } else {
      let more = navigationBars.buttons["More Actions"].firstMatch
      guard more.waitForExistence(timeout: 10) else { return false }
      more.tap()
      let menuAbout = buttons["About Photoslop"].firstMatch
      guard menuAbout.waitForExistence(timeout: 10) else { return false }
      menuAbout.tap()
    }
    // Tapping is not arriving: the sheet has to be up before anything is read
    // off it.
    return navigationBars["About"].waitForExistence(timeout: 15)
  }
}

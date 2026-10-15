// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Shared setup for the UI tests.
///
/// One launched app is shared across every test that only needs *the editor*,
/// which is most of them. Launching from scratch — install, launch scene,
/// Create Document, the canvas-size sheet, first editor — costs 20–60 seconds
/// on a CI runner, and paying it once per test put 30+ cold launches in every
/// run. That is where the whole class of "the editor never came up" /
/// "Timed out while evaluating UI query" failures lived: not one broken test,
/// but three-quarters of an hour of launch dances, any one of which could lose
/// a race at a test-method boundary (#238).
///
/// The contract that makes sharing safe:
///
/// - `openEditor()` hands a test the running editor when the previous test
///   left it there, and does the full launch dance only when it did not.
/// - `tearDown` restores the baseline — every sheet, menu and alert dismissed,
///   the editor's own Export button hittable — and *verifies* it. If the
///   baseline cannot be proven, the app is terminated so the next test starts
///   from a launch it owns, exactly as before. Reuse is an optimisation over
///   the old behaviour, never a substitute for it.
/// - A test that **fails** always tears the app down. A retried test therefore
///   starts cold, inheriting nothing from the attempt that failed.
/// - Tests about document *creation* (`NewDocumentUITests`) opt out through
///   `openLaunchScene()`, which invalidates the shared editor first.
///
/// Tests share one document, so no test may assume the canvas is untouched:
/// assert on deltas (a count measured before and after) or on state the test
/// itself establishes, never on the leftovers of an assumed-fresh document.
/// Every assertion this suite exists for — reachability of controls under real
/// device geometry (#227, #242, #246) — is about the chrome around the canvas,
/// which a used document does not change.
class UITestCase: XCTestCase {
  /// The one proxy every test drives. XCTest runs the whole target's tests
  /// sequentially in one runner process, so a static is one app per
  /// per-destination invocation.
  static let app = XCUIApplication()

  /// Whether the shared app is known to be sitting on the editor. Set only
  /// after the editor's Export button has actually been seen; cleared the
  /// moment anything casts doubt.
  private static var editorIsUp = false

  private static var hasWarmedUp = false

  override func setUp() {
    super.setUp()
    continueAfterFailure = false
    Self.warmUpOnce()
  }

  /// Pay the cold-start cost once, before any assertion can be charged for it.
  ///
  /// The first UI test of a run kept failing on CI with "the editor never came
  /// up" — a freshly booted simulator installing the app, launching it, and
  /// creating its first document simply took longer than any per-test wait,
  /// and whichever test ran first paid for all of it. So the first-document
  /// path runs here, once per test-target invocation, deliberately without a
  /// single assertion. If the app is genuinely broken the real tests say so in
  /// their own words.
  ///
  /// Unlike the earlier version, the warm-up no longer terminates the app: the
  /// editor it reaches *is* the shared editor, and the first test starts on
  /// it. Terminating only to relaunch doubled the most expensive step of the
  /// whole run for the privilege of throwing its result away.
  private static func warmUpOnce() {
    guard !hasWarmedUp else { return }
    hasWarmedUp = true

    app.launchArguments = ["-PhotoslopFreshDocumentStore", "-PhotoslopSuppressSessionNotice", "-PhotoslopPixelProbe"]
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
      if app.navigationBars.buttons["Export Image"].firstMatch.waitForExistence(timeout: 180) {
        editorIsUp = restoreEditorBaseline()
      }
    }

    if !editorIsUp {
      app.terminate()
      _ = app.wait(for: .notRunning, timeout: 30)
    }
  }

  /// The editor, on an open document.
  ///
  /// Reuses the running app when the previous test verifiably left the editor
  /// up; otherwise launches fresh and creates a document, exactly as every
  /// test used to. The reused document is not fresh — see the class note.
  @discardableResult
  func openEditor(file: StaticString = #filePath, line: UInt = #line) -> XCUIApplication {
    let app = Self.app
    if Self.editorIsUp, app.state == .runningForeground, Self.restoreEditorBaseline() {
      return app
    }

    Self.editorIsUp = false
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.openNewDocument(file: file, line: line)
    Self.editorIsUp = true
    return app
  }

  /// The editor on a document this test made, not the shared one.
  ///
  /// For tests whose assertion depends on how much is already in the document.
  /// The layer list is a lazy `List`, so only rows on screen reach the
  /// accessibility tree: once earlier tests have stacked enough layers into the
  /// shared document, `cells.count` stops at the screen edge and a "two more
  /// layers" delta never arrives (#394). A new document starts with one layer,
  /// so the whole list fits. Costs one launch; the editor it reaches becomes
  /// the shared one for the tests after it.
  @discardableResult
  func openFreshEditor(file: StaticString = #filePath, line: UInt = #line) -> XCUIApplication {
    let app = Self.app
    Self.editorIsUp = false
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.openNewDocument(file: file, line: line)
    Self.editorIsUp = true
    return app
  }

  /// A fresh launch stopped on the launch scene, for tests about document
  /// creation itself. Invalidates the shared editor: after this, the next
  /// `openEditor()` launches from scratch.
  ///
  /// The document store IS emptied now. It deliberately was not — the held
  /// documents were the state every launch inherited, and these tests passed
  /// against it for as long as the SDK showed the launch scene regardless.
  /// Under the iOS 26 SDK, state restoration of a held document races the
  /// launch scene: Create Document opens an editor that restoration then
  /// tears down, and the app lands back on the launch scene with the new
  /// document stranded in the browser (#290, bisected on makemake). An empty
  /// store has nothing to restore, which is the screen these tests are about.
  func openLaunchScene(file: StaticString = #filePath, line: UInt = #line) -> XCUIApplication {
    let app = Self.app
    Self.editorIsUp = false
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.launchArguments = ["-PhotoslopFreshDocumentStore", "-PhotoslopSuppressSessionNotice", "-PhotoslopPixelProbe"]
    app.launch()
    XCTAssertTrue(
      app.buttons["Create Document"].firstMatch.waitForExistence(timeout: 90),
      "launch scene never appeared", file: file, line: line)
    return app
  }

  /// Dismiss whatever a test left presented and prove the editor is back.
  ///
  /// Every presentation in this app carries its own way out — Cancel on the
  /// export, canvas-size and text sheets and on the system photo picker, Done
  /// on the layer list and About, OK on the export confirmation — and an open
  /// `Menu` puts a scrim over everything, so a tap that reaches nothing else
  /// closes it. The loop takes those exits until the editor's own Export
  /// button is hittable, and reports honestly when it is not: the caller then
  /// terminates, and the next test launches fresh rather than inheriting a
  /// mystery.
  ///
  /// The blind tap runs only while the baseline is provably obscured, so it
  /// lands on a scrim, not the canvas.
  private static func restoreEditorBaseline() -> Bool {
    let export = app.navigationBars.buttons["Export Image"].firstMatch
    // The navigation bar alone is not enough. Crop replaces only the *bottom*
    // bar, so Export stays put and a crop left running looks exactly like the
    // baseline — the next test then fails on "Brush width is not on screen",
    // having inherited a mode it never entered. The palette proves the
    // editor's ordinary chrome is up; the absence of a mode's Cancel proves
    // no mode is. Both are needed now that the palette is a rail beside the
    // canvas and stays put while a mode owns the bottom bar.
    let palette = app.buttons.matching(
      NSPredicate(format: "label BEGINSWITH %@", "Tool, ")
    ).firstMatch
    let modeExit = app.buttons.matching(
      NSPredicate(format: "identifier IN %@", ["Cancel Crop", "Cancel Placement"])
    ).firstMatch
    for _ in 1...4 {
      if export.exists, export.isHittable, palette.exists, !modeExit.exists { return true }

      var tookAnExit = false
      for label in ["Cancel", "Done", "OK"] {
        let exit = app.buttons[label].firstMatch
        if exit.exists, exit.isHittable {
          exit.tap()
          tookAnExit = true
          break
        }
      }
      if !tookAnExit {
        // Nothing dismissible is on screen yet the editor is obscured: a menu.
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.05, dy: 0.5)).tap()
      }
    }
    return export.waitForExistence(timeout: 10) && export.isHittable
      && palette.waitForExistence(timeout: 10) && !modeExit.exists
  }

  override func tearDown() {
    let app = Self.app

    // Orientation is process-global and outlives the test that set it, and a
    // `defer` does not restore it on a failing path. A rotated test that fails
    // otherwise leaves every test after it in landscape, where the iPhone
    // launch scene cannot be operated (#252) — one landscape test took down two
    // unrelated ones that way. This matters more now that the app is shared:
    // the next test may not relaunch at all.
    XCUIDevice.shared.orientation = .portrait

    // A failed test forfeits reuse: it may have stopped anywhere, and its
    // retry (if `-retry-tests-on-failure` grants one) must inherit nothing.
    let failed = (testRun?.totalFailureCount ?? 0) > 0

    if failed || app.state != .runningForeground || !Self.restoreEditorBaseline() {
      Self.editorIsUp = false
      app.terminate()
      // Terminating is not enough: the next launch can race a scene still
      // being torn down, and the app then comes up on a screen nobody asked
      // for. Fifteen consecutive launches inside one test method never flaked;
      // launches across method boundaries did, until this waited.
      _ = app.wait(for: .notRunning, timeout: 20)
    } else {
      Self.editorIsUp = true
    }
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
  /// Timeouts are generous on purpose, and were raised again in August 2026. A
  /// CI runner takes about three times as long as this machine for the same
  /// test, and under load considerably more than that, so limits tuned locally
  /// expire there while the app is still coming up — the failure then reads as
  /// "the editor never came up" when the truth is that nobody waited long
  /// enough. Waiting longer costs nothing on a fast machine, where the element
  /// arrives and the wait returns immediately; deleting coverage to make the
  /// suite fit would cost something real.
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
    launchArguments = ["-PhotoslopFreshDocumentStore", "-PhotoslopSuppressSessionNotice", "-PhotoslopPixelProbe"]
    for attempt in 1...3 {
      if attempt > 1 {
        terminate()
        _ = wait(for: .notRunning, timeout: 30)
      }
      launch()
      if create.waitForExistence(timeout: 150) { break }
    }
    XCTAssertTrue(
      create.waitForExistence(timeout: 60), "launch scene never appeared", file: file, line: line)
    createDocument(file: file, line: line)

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
      navigationBars.buttons["Export Image"].firstMatch.waitForExistence(timeout: 180),
      "the editor never came up", file: file, line: line)
  }

  /// Tap Create Document on the launch scene, and make sure the tap took.
  ///
  /// On the CI runner a tap can land while the launch scene is still settling
  /// and be dropped: nothing happens, the launch scene just sits there, and
  /// whatever the caller waits for next expires — "the editor never came up"
  /// (#408, SelectionClipboardUITests on the iPhone leg), "size sheet never
  /// appeared" (NewDocumentUITests on the iPad leg, which tapped once and
  /// waited). Re-tap only after 45 seconds in which the sheet has not come,
  /// the editor has not come and Create Document has not left. A slow but
  /// live creation does one of those, so it is never tapped twice.
  ///
  /// The document browser's own refusal is handled here too. Seen on the
  /// iPhone leg when a launch followed a terminate closely enough that the
  /// browser's staging package from the last creation was still in the way:
  /// the tap took, the browser put up "Unable to Import Document", and the
  /// editor wait spent its whole 180 seconds on an alert. Dismissed and the
  /// creation retried, rather than waited out.
  ///
  /// And the browser's hang (#430). Intermittently on the runner's iPhone leg,
  /// never on the iPad leg or locally, a launch that follows a `terminate()`
  /// creates `Untitled.photoslop` and then never opens it: the hierarchy
  /// shows the system browser with its one cell greyed out — `Disabled`, its
  /// opening-in-progress state — and no scene of ours, for as long as anyone
  /// waits. The 180-second editor wait then expires, and because every later
  /// test that launches fresh rolls the same dice, one hang became a cascade
  /// that ran the job into its timeout. A relaunch gives the file provider a
  /// fresh client, so after 60 seconds with that cell on screen and nothing
  /// of ours, the app is terminated and launched again and the creation
  /// retried, once. A slow but live creation shows the sheet or the editor
  /// well inside that minute, and is never cut short.
  func createDocument(file: StaticString = #filePath, line: UInt = #line) {
    let create = buttons["Create Document"].firstMatch
    let sizeSheet = buttons["Use This Size"].firstMatch
    let editor = navigationBars.buttons["Export Image"].firstMatch
    let importFailed = alerts["Unable to Import Document"].firstMatch
    // The system browser's cell for the document it is failing to open. Its
    // identifier is the file name with the extension as a second word.
    let stuckDocument = cells["Untitled, photoslop"].firstMatch
    XCTAssertTrue(
      create.waitForExistence(timeout: 60), "no Create Document to tap", file: file, line: line)

    func tapTook() -> Bool {
      for _ in 0..<45 {
        if sizeSheet.waitForExistence(timeout: 1) || editor.exists || !create.exists {
          return true
        }
        if importFailed.exists {
          importFailed.buttons["OK"].firstMatch.tap()
          _ = importFailed.waitForNonExistence(timeout: 10)
          return false
        }
      }
      return false
    }
    func tapUntilItTakes() {
      create.tap()
      for _ in 1...3 {
        if tapTook() { break }
        guard create.waitForExistence(timeout: 5), create.isHittable else { break }
        create.tap()
      }
    }
    /// True once the browser has sat on its greyed-out cell for a minute with
    /// neither the sheet, the editor nor the launch scene arriving.
    func browserIsHung() -> Bool {
      for _ in 0..<60 {
        if sizeSheet.waitForExistence(timeout: 1) || editor.exists || create.exists {
          return false
        }
      }
      return stuckDocument.exists
    }

    tapUntilItTakes()
    if browserIsHung() {
      terminate()
      _ = wait(for: .notRunning, timeout: 30)
      launch()
      guard create.waitForExistence(timeout: 150) else { return }
      tapUntilItTakes()
    }
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

  /// Which submenu of the compact More Actions menu holds an action (#313).
  /// Anything not listed is on the top level at every width.
  private static let submenuHolding: [String: String] = [
    "Canvas Size": "Image",
    "Resize Document…": "Image",
    "Crop…": "Image",
    "Resize Layer…": "Image",
    "Flatten Image": "Image",
    "Add Text": "Text",
    "Edit Text": "Text",
    "Move Text": "Text",
    "Fit Text…": "Text",
    "Effects…": "Text",
    // The Filters submenu (#327) is nested at every width.
    "Sepia": "Filters",
    "Pixelate": "Filters",
    "Denoise (Chroma)": "Filters",
    "Retro Console (8-Bit)": "Filters",
    "Pixel Sort (Glitch)": "Filters",
    "Datamosh + Chromatic Aberration": "Filters",
    "Film Negative → Positive": "Filters",
    "Invert": "Filters",
  ]

  /// Open More Actions and wait until its rows are actually on screen.
  ///
  /// Import Image is on the top level of both the phone's menu and the iPad's,
  /// so its arrival is the menu's: a query for a nested row before this point
  /// finds nothing, and reads as the row being missing.
  func openMoreActions(file: StaticString = #filePath, line: UInt = #line) {
    let more = navigationBars.buttons["More Actions"].firstMatch
    XCTAssertTrue(
      more.waitForExistence(timeout: 15), "no More Actions menu on the bar", file: file, line: line)
    more.tap()
    XCTAssertTrue(
      buttons["Import Image…"].firstMatch.waitForExistence(timeout: 10),
      "More Actions did not open", file: file, line: line)
  }

  /// Close an open menu without choosing anything from it.
  ///
  /// An open `Menu` puts a scrim over everything, so a tap that reaches
  /// nothing else closes it — the same exit `restoreEditorBaseline` takes.
  /// Low and central, though: the menu hangs from the leading side of the
  /// bar, and a tap down its left edge lands on a row of a seven-row menu.
  func dismissMenu() {
    coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.8)).tap()
    _ = buttons["Import Image…"].firstMatch.waitForNonExistence(timeout: 10)
  }

  /// Bring a More Actions row on screen and hand it back, untapped.
  ///
  /// The compact menu nests Image and Text submenus so its top level fits a
  /// phone without scrolling (#313); the iPad menu is flat and holds the same
  /// actions one level up. A nested SwiftUI `Menu` is a row that has to be
  /// tapped before its contents exist in the accessibility tree at all, so an
  /// action is looked for on the top level first and behind its submenu only
  /// when it is not there. Tests name the action; which menu this device
  /// shows is not their business.
  @discardableResult
  func revealAction(
    _ label: String, file: StaticString = #filePath, line: UInt = #line
  ) -> XCUIElement {
    openMoreActions(file: file, line: line)
    let action = buttons[label].firstMatch
    if !action.exists, let submenu = Self.submenuHolding[label] {
      let row = buttons[submenu].firstMatch
      XCTAssertTrue(
        row.waitForExistence(timeout: 10),
        "neither \(label) nor the \(submenu) submenu is in More Actions", file: file, line: line)
      row.tap()
    }
    XCTAssertTrue(
      action.waitForExistence(timeout: 10), "\(label) is missing from More Actions",
      file: file, line: line)
    return action
  }

  /// Choose a document action, wherever this width keeps it.
  ///
  /// On the bar when the bar is provably wide enough for it; otherwise in the
  /// app's own More Actions menu, and on a phone possibly one submenu down.
  /// A test that cares about the *result* of an action should not have to
  /// know which.
  func chooseAction(_ label: String, file: StaticString = #filePath, line: UInt = #line) {
    let onBar = navigationBars.buttons[label].firstMatch
    if onBar.waitForExistence(timeout: 2), onBar.isHittable {
      onBar.tap()
    } else {
      revealAction(label, file: file, line: line).tap()
    }
  }

  /// A menu row by label, whichever element type this runtime reports it as.
  ///
  /// An action is a button. A `Toggle` in a `Menu` becomes a `UIMenu` row with
  /// a checkmark, and whether XCTest calls that a button or a switch has
  /// varied between runtimes, so a query that accepts either is the one that
  /// keeps working.
  func menuRow(_ label: String) -> XCUIElement {
    descendants(matching: .any).matching(
      NSPredicate(
        format: "label == %@ AND (elementType == %d OR elementType == %d)", label,
        XCUIElement.ElementType.button.rawValue, XCUIElement.ElementType.switch.rawValue)
    ).firstMatch
  }

  /// The Finger toggle as More Actions shows it, with the menu left open.
  private func revealFingerToggle(file: StaticString = #filePath, line: UInt = #line)
    -> XCUIElement
  {
    openMoreActions(file: file, line: line)
    let toggle = menuRow("Finger")
    XCTAssertTrue(
      toggle.waitForExistence(timeout: 10), "no Finger toggle in the menu", file: file, line: line)
    return toggle
  }

  /// Whether a menu row with a checkmark is checked.
  private static func isOn(_ toggle: XCUIElement) -> Bool {
    toggle.isSelected || (toggle.value as? String) == "1"
  }

  /// Whether touch draws right now, read off the Finger toggle. Opens and
  /// closes More Actions to look.
  func fingerDrawingIsOn(file: StaticString = #filePath, line: UInt = #line) -> Bool {
    let toggle = revealFingerToggle(file: file, line: line)
    let on = Self.isOn(toggle)
    dismissMenu()
    return on
  }

  /// Make touch draw, or not, whatever it does right now.
  ///
  /// Synthesized touches are finger touches, so a test that draws needs this
  /// on. It used to be a blind tap on the assumption that Finger starts off,
  /// which is true of an iPad and no longer of a phone (#313): the same tap
  /// would have switched drawing *off* there. Reading the toggle first makes
  /// the helper say what it means on both.
  func setFingerDrawing(_ on: Bool, file: StaticString = #filePath, line: UInt = #line) {
    let toggle = revealFingerToggle(file: file, line: line)
    if Self.isOn(toggle) == on {
      dismissMenu()
    } else {
      toggle.tap()
    }
  }

  /// Add a text layer, wherever this width keeps **Add Text**.
  ///
  /// It is on the bar only when the bar is provably wide enough; otherwise it
  /// is in the app's own More Actions menu, alongside Edit Text and Move Text.
  /// A test that cares about the *result* of adding text should not have to
  /// know which.
  func addText(_ body: String, file: StaticString = #filePath, line: UInt = #line) {
    chooseAction("Add Text", file: file, line: line)

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

  /// Choose a drawing tool from the palette.
  ///
  /// Every tool is its own button, on screen at once: the rail beside the
  /// canvas on an iPad, the bottom row of the dock on a phone. A tool's
  /// identifier is its name, and the one in hand is labelled "Tool, <name>",
  /// so picking one is a single tap and proving which one is in hand is a
  /// label query.
  func selectTool(_ name: String, file: StaticString = #filePath, line: UInt = #line) {
    let palette = buttons.matching(
      NSPredicate(format: "label BEGINSWITH %@", "Tool, ")
    ).firstMatch
    XCTAssertTrue(
      palette.waitForExistence(timeout: 15), "the tool palette is not on screen",
      file: file, line: line)
    if palette.label == "Tool, \(name)" { return }

    let choice = buttons[name].firstMatch
    XCTAssertTrue(
      choice.waitForExistence(timeout: 10), "\(name) is missing from the tool palette",
      file: file, line: line)
    choice.tap()
    XCTAssertTrue(
      buttons["Tool, \(name)"].firstMatch.waitForExistence(timeout: 10),
      "tapping \(name) did not make it the tool in hand", file: file, line: line)
  }

  /// Reach About, which sits on the bar at regular width and in the actions menu
  /// at compact width.
  @discardableResult
  func openAbout(file: StaticString = #filePath, line: UInt = #line) -> Bool {
    chooseAction("About Photoslop", file: file, line: line)
    // Tapping is not arriving: the sheet has to be up before anything is read
    // off it.
    return navigationBars["About"].waitForExistence(timeout: 15)
  }
}

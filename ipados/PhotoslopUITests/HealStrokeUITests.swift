// SPDX-License-Identifier: Apache-2.0
import XCTest

/// The interactive retouch stroke tools (#456) as a running app sees them:
/// reach Spot Healing and the Healing Brush without exceeding the iPhone's
/// nine-button palette budget, heal under a tap and a drag, and undo the result.
///
/// The unit tests prove the heal is the desktop's Poisson heal; these prove the
/// gestures reach it and register one undo step. Like the bucket test, they read
/// the active layer's centre pixel through `-PhotoslopPixelProbe` where a pixel
/// assertion is meaningful, and otherwise assert on the undo history.
///
/// The Retouch picker is a SwiftUI `Menu`, which renders as a Button wrapping a
/// Button: its outer wrapper reports `isHittable == false` and `.combine` does not
/// fix it on iOS 18.5 (LESSONSLEARNED.md L-001). So — like CropUITests — these
/// assert the control's geometry and operate it by coordinate, never `isHittable`.
final class HealStrokeUITests: UITestCase {
  /// The canvas element, whose accessibility value names the tool in hand.
  private func canvas(_ app: XCUIApplication) -> XCUIElement {
    app.descendants(matching: .any)
      .matching(NSPredicate(format: "label == %@", "Editable image canvas")).firstMatch
  }

  /// The centre pixel's red byte, parsed from the probe's AARRGGBB hex word.
  private func probeRed(_ app: XCUIApplication) -> Int? {
    let probe = app.staticTexts["Pixel probe"].firstMatch
    guard let hex = probe.value as? String, hex.count == 8 else { return nil }
    return Int(hex.dropFirst(2).prefix(2), radix: 16)
  }

  /// Open the Retouch picker by coordinate (L-001): assert it is inside the
  /// window, then tap its centre the way a finger does, not its outer element.
  private func openRetouchMenu(_ app: XCUIApplication) {
    let menu = app.buttons["Retouch tools"].firstMatch
    XCTAssertTrue(menu.waitForExistence(timeout: 15), "no Retouch picker on the options strip")
    let window = app.windows.firstMatch.frame
    XCTAssertTrue(
      window.contains(menu.frame),
      "the Retouch picker is outside the window at \(menu.frame), window \(window) — "
        + "the options strip is over its budget for this device")
    menu.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
  }

  /// Arm a retouch tool through the Retouch picker in the tool options — the
  /// visible, tappable route that shares the Eraser's palette slot (#456). The
  /// picker only appears once the Eraser (or a heal tool) is in hand, so select
  /// the Eraser first, then choose; prove the choice took via the canvas value,
  /// which names the real tool in hand (the palette slot keeps the Eraser label).
  private func selectRetouchTool(_ app: XCUIApplication, _ name: String) {
    app.selectTool("Eraser")
    openRetouchMenu(app)
    let row = app.buttons[name].firstMatch
    XCTAssertTrue(row.waitForExistence(timeout: 10), "\(name) is missing from the Retouch picker")
    row.tap()
    let expected = name.lowercased()
    let expectation = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value CONTAINS %@", expected), object: canvas(app))
    XCTAssertEqual(
      XCTWaiter().wait(for: [expectation], timeout: 15), .completed,
      "\(name) did not become the tool in hand")
  }

  /// Deposit a black blemish at the canvas centre with the Pen, so a heal has
  /// something to remove and the probe can see it.
  ///
  /// Two things a naive version gets wrong, both proven on the CI 18.5 leg:
  /// the Pen is a PencilKit *stroke* tool, not a tap tool, so a zero-motion
  /// `.tap()` deposits nothing at the probed pixel — a real press-and-drag is
  /// needed (the way FitTextUITests draws). And `setFingerDrawing(true)` leaves
  /// the More Actions menu open when it had to flip the toggle (an iPad's
  /// finger-off default), so the scrim must be dismissed before the stroke can
  /// reach the canvas. The canvas is fitted and `centerCanvas()`-ed, so the
  /// view's centre is the image centre the probe reads; a stroke through it
  /// inks that pixel.
  private func drawBlemishAtCentre(_ app: XCUIApplication) {
    app.selectTool("Pen")
    app.setFingerDrawing(true)
    // Close the menu scrim if the toggle left one up. dismissMenu's own tap is
    // zero-motion, so even when it lands on the canvas it draws no Pen mark.
    app.dismissMenu()
    let probe = app.staticTexts["Pixel probe"].firstMatch
    XCTAssertTrue(probe.waitForExistence(timeout: 10))
    let centre = canvas(app)
    let start = centre.coordinate(withNormalizedOffset: CGVector(dx: 0.4, dy: 0.5))
    let end = centre.coordinate(withNormalizedOffset: CGVector(dx: 0.6, dy: 0.5))
    start.press(forDuration: 0.1, thenDragTo: end)
    let darkened = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value != %@", "FFFFFFFF"), object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [darkened], timeout: 20), .completed,
      "the Pen stroke left no blemish at the centre")
  }

  func testSpotHealingTapHealsABlemishAndIsUndoable() {
    let app = openFreshEditor()
    drawBlemishAtCentre(app)
    let probe = app.staticTexts["Pixel probe"].firstMatch
    // Pen ink is anti-aliased, so the blemish is dark but not the bucket's pure
    // FF000000; capture what was actually drawn and assert against that.
    let blemishHex = probe.value as? String ?? ""
    let blemishRed = probeRed(app) ?? 0
    XCTAssertLessThan(blemishRed, 128, "the blemish should be dark before healing")

    selectRetouchTool(app, "Spot Healing")
    // The retouch tools take a dab radius from the width control.
    XCTAssertTrue(
      app.sliders["Brush width"].firstMatch.waitForExistence(timeout: 10),
      "Spot Healing has no brush width control")

    canvas(app).coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()

    // The blemish heals back toward the white field: one undo step, named.
    let healed = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value != %@", blemishHex), object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [healed], timeout: 20), .completed,
      "the centre pixel did not change after the spot-heal tap")
    XCTAssertGreaterThan(probeRed(app) ?? 0, 150, "the blemish did not heal toward the surrounding white")

    let undo = app.buttons["Undo"].firstMatch
    XCTAssertTrue(undo.waitForExistence(timeout: 10))
    XCTAssertTrue(undo.isEnabled, "the spot-heal tap did not register an undo step")
    undo.tap()
    let restored = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value == %@", blemishHex), object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [restored], timeout: 20), .completed,
      "undo did not restore the blemish")

    app.selectTool("Pen")
  }

  func testSpotHealingDragHealsAndIsUndoable() {
    let app = openFreshEditor()
    drawBlemishAtCentre(app)
    selectRetouchTool(app, "Spot Healing")

    // A drag across the centre: the trail commits as one heal on release.
    let start = canvas(app).coordinate(withNormalizedOffset: CGVector(dx: 0.4, dy: 0.5))
    let end = canvas(app).coordinate(withNormalizedOffset: CGVector(dx: 0.6, dy: 0.5))
    start.press(forDuration: 0.1, thenDragTo: end)

    let undo = app.buttons["Undo"].firstMatch
    XCTAssertTrue(undo.waitForExistence(timeout: 10))
    let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "isEnabled == true"), object: undo)
    XCTAssertEqual(
      XCTWaiter().wait(for: [enabled], timeout: 20), .completed,
      "the spot-heal drag did not register an undo step")
    // The drag crossed the centre, so the blemish there healed toward white.
    XCTAssertGreaterThan(probeRed(app) ?? 0, 150, "the spot-heal drag did not heal the centre blemish")
    undo.tap()
    XCTAssertTrue(app.buttons["Redo"].firstMatch.isEnabled, "undoing the stroke should make redo available")

    app.selectTool("Pen")
  }

  func testHealingBrushPicksASourceAndHealsAndIsUndoable() {
    let app = openFreshEditor()
    drawBlemishAtCentre(app)
    selectRetouchTool(app, "Healing Brush")

    // The source pick is armed from the options strip, then taken on the canvas.
    let pick = app.buttons["Pick Heal Source"].firstMatch
    XCTAssertTrue(pick.waitForExistence(timeout: 10), "no Pick Source control for the Healing Brush")
    pick.tap()
    // Sample clean white texture away from the blemish.
    canvas(app).coordinate(withNormalizedOffset: CGVector(dx: 0.25, dy: 0.25)).tap()

    // Heal the blemish at the centre from the picked source.
    canvas(app).coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()

    // The blemish heals toward the sampled white texture, not merely an empty undo.
    let healed = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value != %@", "FF000000"), object: app.staticTexts["Pixel probe"].firstMatch)
    XCTAssertEqual(
      XCTWaiter().wait(for: [healed], timeout: 20), .completed,
      "the centre pixel did not change after the healing-brush dab")
    XCTAssertGreaterThan(probeRed(app) ?? 0, 150, "the healing brush did not heal the blemish toward the source")

    let undo = app.buttons["Undo"].firstMatch
    XCTAssertTrue(undo.waitForExistence(timeout: 10))
    XCTAssertTrue(undo.isEnabled, "the healing-brush dab did not register an undo step")
    undo.tap()
    XCTAssertTrue(app.buttons["Redo"].firstMatch.isEnabled, "undoing the heal should make redo available")

    app.selectTool("Pen")
  }

  /// The retouch tools are reachable on a phone without growing the palette past
  /// nine buttons: the Eraser hosts them, and the Retouch picker offers both heal
  /// tools. Choosing one closes the menu and arms it (no blind-coordinate dismiss).
  func testRetouchToolsAreReachableWithinThePaletteBudget() {
    let app = openFreshEditor()
    app.selectTool("Eraser")
    // The palette keeps exactly one in-hand button — the slot the heal tools share.
    let inHand = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Tool, "))
    XCTAssertEqual(inHand.count, 1, "the palette must show exactly one tool in hand")

    openRetouchMenu(app)
    XCTAssertTrue(app.buttons["Spot Healing"].firstMatch.waitForExistence(timeout: 10))
    XCTAssertTrue(app.buttons["Healing Brush"].firstMatch.waitForExistence(timeout: 10))
    // Choose Spot Healing: the menu closes and the tool is in hand, proven by the
    // canvas value (the palette slot still reads "Tool, Eraser").
    app.buttons["Spot Healing"].firstMatch.tap()
    let expectation = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value CONTAINS %@", "spot healing"), object: canvas(app))
    XCTAssertEqual(
      XCTWaiter().wait(for: [expectation], timeout: 15), .completed,
      "Spot Healing did not become the tool in hand from the Retouch picker")
    XCTAssertEqual(inHand.count, 1, "arming a heal tool must not add a second in-hand palette button")

    app.selectTool("Pen")
  }
}
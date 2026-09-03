// SPDX-License-Identifier: Apache-2.0
import XCTest

/// The Effects… sheet on a text layer (#316).
///
/// The renderer and the model have unit coverage against the desktop's own
/// output; what only a running app can answer is whether the sheet is
/// reachable from the text tool on both widths, whether a preset fills the
/// stack, and whether Apply closes it.
final class TextEffectsUITests: UITestCase {
  func testAPresetFillsTheStackAndApplyCloses() {
    let app = openEditor()
    app.addText("Shadowed")

    // Adding text leaves Move Text mode running; leave it the way a person
    // would, or the editor is not in its resting state for the menu.
    let doneMoving = app.buttons["Done"].firstMatch
    if doneMoving.exists, doneMoving.isHittable { doneMoving.tap() }

    app.chooseAction("Effects…")
    XCTAssertTrue(
      app.navigationBars["Effects"].waitForExistence(timeout: 20),
      "the Effects sheet never appeared")
    XCTAssertTrue(
      app.buttons["Add Effect"].firstMatch.waitForExistence(timeout: 10),
      "the sheet has no Add Effect")

    // The preset row's label is its name followed by its stack ("Sticker,
    // Drop Shadow + Outline"), and a stack row is whatever element type this
    // runtime makes of a NavigationLink in a List, so both are matched loosely.
    let sticker = app.buttons.matching(
      NSPredicate(format: "label BEGINSWITH %@", "Sticker")
    ).firstMatch
    XCTAssertTrue(sticker.waitForExistence(timeout: 10), "the Sticker preset is missing")
    sticker.tap()
    func row(_ identifier: String) -> XCUIElement {
      app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
    XCTAssertTrue(
      row("Effect Drop Shadow").waitForExistence(timeout: 10),
      "the Sticker preset did not put a drop shadow in the stack")
    XCTAssertTrue(
      row("Effect Outline").exists,
      "the Sticker preset did not put an outline in the stack")

    app.buttons["Apply"].firstMatch.tap()
    XCTAssertTrue(
      app.navigationBars["Effects"].waitForNonExistence(timeout: 10),
      "Apply should close the sheet")
  }
}

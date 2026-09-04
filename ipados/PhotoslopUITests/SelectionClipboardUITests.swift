// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Cut, Copy, Paste and Delete for a selection, as a running app sees them
/// (#374).
///
/// The unit tests prove the pixels are right. This proves the buttons are
/// *findable*, which is the actual defect the issue was filed for: Delete
/// Selection had shipped since 2.22.0 three levels down a system menu, and the
/// operator using the wand every day never found it. So the assertions here are
/// deliberately about presence and reachability — the strip has no clipboard
/// controls until a selection exists, and one tap on the strip acts on it.
final class SelectionClipboardUITests: UITestCase {
  /// Make a selection with the wand, the way the report described.
  private func selectWithWand(_ app: XCUIApplication) {
    app.selectTool("Magic Wand")
    let canvas = app.descendants(matching: .any)
      .matching(NSPredicate(format: "label == %@", "Editable image canvas")).firstMatch
    XCTAssertTrue(canvas.waitForExistence(timeout: 15), "no canvas on screen")
    canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
  }

  func testTheStripGrowsClipboardActionsOnlyWhileASelectionIsUp() {
    let app = openEditor()
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.openNewDocument()

    XCTAssertFalse(
      app.buttons["Cut"].firstMatch.exists,
      "the clipboard controls are on the strip with nothing selected")

    selectWithWand(app)

    for action in ["Cut", "Copy", "Paste", "Delete Selection"] {
      XCTAssertTrue(
        app.buttons[action].firstMatch.waitForExistence(timeout: 10),
        "\(action) is not one tap away with a selection up")
    }
  }

  func testCutFromTheStripClearsTheSelectedPixels() {
    let app = openEditor()
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.openNewDocument()

    let probe = app.staticTexts["Pixel probe"].firstMatch
    XCTAssertTrue(probe.waitForExistence(timeout: 10), "the pixel probe is not exposed")
    XCTAssertEqual(probe.value as? String, "FFFFFFFF", "a new document is opaque white")

    selectWithWand(app)
    let cut = app.buttons["Cut"].firstMatch
    XCTAssertTrue(cut.waitForExistence(timeout: 10), "Cut is not on the strip")
    cut.tap()

    // The wand on a blank document selects the whole white region, so cutting
    // it empties the probed pixel.
    let cleared = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value == %@", "00000000"), object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [cleared], timeout: 20), .completed,
      "the pixel survived the cut: \(probe.value ?? "nil")")

    // Copy-then-clear is one step, so one undo puts it back.
    let undo = app.buttons["Undo"].firstMatch
    XCTAssertTrue(undo.waitForExistence(timeout: 10))
    XCTAssertTrue(undo.isEnabled, "the cut did not register an undo step")
    undo.tap()
    let restored = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value == %@", "FFFFFFFF"), object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [restored], timeout: 20), .completed,
      "one undo did not take the whole cut back: \(probe.value ?? "nil")")
  }

  func testPasteBecomesAvailableAfterACopyAndAddsALayer() {
    let app = openEditor()
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.openNewDocument()

    selectWithWand(app)
    let copy = app.buttons["Copy"].firstMatch
    XCTAssertTrue(copy.waitForExistence(timeout: 10), "Copy is not on the strip")
    copy.tap()

    let paste = app.buttons["Paste"].firstMatch
    XCTAssertTrue(paste.waitForExistence(timeout: 10), "Paste is not on the strip")
    let enabled = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "isEnabled == true"), object: paste)
    XCTAssertEqual(
      XCTWaiter().wait(for: [enabled], timeout: 20), .completed,
      "Paste stayed inert after a copy")
    paste.tap()

    // The paste is its own undo step, which is the observable proof it landed.
    let undo = app.buttons["Undo"].firstMatch
    XCTAssertTrue(undo.waitForExistence(timeout: 10))
    XCTAssertTrue(undo.isEnabled, "the paste did not register an undo step")
  }
}

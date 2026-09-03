// SPDX-License-Identifier: Apache-2.0
import XCTest

/// The Filters menu (#327) as a running app sees it: More Actions holds a
/// Filters submenu, a row opens the parameter sheet, Apply changes the active
/// layer's pixels, and Undo puts them back.
///
/// The unit tests prove each filter is the desktop's filter; this proves the
/// menu reaches one. The pixel probe (`EditorView.pixelProbe`) reads one word
/// of the active layer, and sepia at its default over opaque white is
/// `FFFFE8B1` on every platform — the desktop wrote that value.
final class FilterUITests: UITestCase {
  func testSepiaFromTheFiltersMenuChangesTheLayerAndUndoRestoresIt() {
    let app = openEditor()
    // A fresh document, so the active layer is the white Background rather
    // than a text layer an earlier test may have left active.
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.openNewDocument()

    let probe = app.staticTexts["Pixel probe"].firstMatch
    XCTAssertTrue(probe.waitForExistence(timeout: 10), "the pixel probe is not exposed")
    XCTAssertEqual(probe.value as? String, "FFFFFFFF", "a new document's background is opaque white")

    app.chooseAction("Sepia")
    let apply = app.buttons["Apply filter"].firstMatch
    XCTAssertTrue(apply.waitForExistence(timeout: 10), "the Sepia parameter sheet did not open")
    // Every parameter control is identified `Filter <the desktop param name>`,
    // so Sepia's one `ParamSpec` — amount, 0…100, default 80 — is this slider.
    XCTAssertTrue(
      app.sliders["Filter amount"].firstMatch.exists, "the sheet has no Amount slider")
    apply.tap()

    let toned = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value == %@", "FFFFE8B1"), object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [toned], timeout: 20), .completed,
      "the probe pixel is not the desktop's sepia of white: \(probe.value ?? "nil")")

    let undo = app.buttons["Undo"].firstMatch
    XCTAssertTrue(undo.waitForExistence(timeout: 10))
    XCTAssertTrue(undo.isEnabled, "the filter did not register an undo step")
    undo.tap()
    let restored = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "value == %@", "FFFFFFFF"), object: probe)
    XCTAssertEqual(
      XCTWaiter().wait(for: [restored], timeout: 20), .completed,
      "undo did not restore the white background")
  }

  func testCancelLeavesTheLayerAlone() {
    let app = openEditor()
    app.terminate()
    _ = app.wait(for: .notRunning, timeout: 30)
    app.openNewDocument()
    let probe = app.staticTexts["Pixel probe"].firstMatch
    XCTAssertTrue(probe.waitForExistence(timeout: 10))

    app.chooseAction("Pixel Sort (Glitch)")
    let cancel = app.buttons["Cancel filter"].firstMatch
    XCTAssertTrue(cancel.waitForExistence(timeout: 10), "the Pixel Sort sheet did not open")
    cancel.tap()
    XCTAssertTrue(cancel.waitForNonExistence(timeout: 10), "the sheet did not close")
    XCTAssertEqual(probe.value as? String, "FFFFFFFF", "Cancel changed a pixel")
  }
}

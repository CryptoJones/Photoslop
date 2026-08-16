// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Fitting a text layer with the placement box (#261).
///
/// The report, in the user's words: "The fit text control can't be resized
/// even with the constrain proportions unchecked", and while it moves, no
/// preview of the text follows the box. The arithmetic already has unit
/// coverage; what only a running app can answer is whether a finger on the
/// box actually changes the rectangle it is aimed at — the corner must
/// resize, the interior must move, and the two must not trade places just
/// because a caption's box is shorter than a fingertip.
final class FitTextUITests: UITestCase {
  /// Open Fit Text on a fresh text layer and hand back the app.
  private func openFitText() -> XCUIApplication {
    let app = openEditor()
    app.addText("Fit me across the picture")

    let more = app.navigationBars.buttons["More Actions"].firstMatch
    XCTAssertTrue(more.waitForExistence(timeout: 15), "no More Actions menu")
    more.tap()

    let fit = app.buttons["Fit Text…"].firstMatch
    XCTAssertTrue(fit.waitForExistence(timeout: 10), "Fit Text… is missing from the menu")
    fit.tap()

    XCTAssertTrue(
      app.buttons["Apply Placement"].waitForExistence(timeout: 20),
      "Fit Text did not open the placement box")
    return app
  }

  /// "Layer size 1,095 by 128" → (1095, 128). The label is a
  /// `LocalizedStringKey`, so the numbers carry grouping separators.
  private func boxSize(_ app: XCUIApplication) -> CGSize? {
    let readout = app.staticTexts["Layer size"].firstMatch
    guard readout.exists else { return nil }
    let numbers = readout.label
      .replacingOccurrences(of: ",", with: "")
      .components(separatedBy: CharacterSet.decimalDigits.inverted)
      .compactMap { Double($0) }
    guard numbers.count >= 2 else { return nil }
    return CGSize(width: numbers[0], height: numbers[1])
  }

  /// The corner handle must resize the box — that is the entire feature — and
  /// text keeps its own shape while it does.
  func testDraggingACornerResizesTheFitTextBox() {
    let app = openFitText()

    guard let before = boxSize(app) else {
      return XCTFail("no Layer size readout while fitting text")
    }

    let corner = app.otherElements["Transform bottom right"].firstMatch
    XCTAssertTrue(corner.exists, "the fit-text box has no bottom-right handle")

    let start = corner.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
    start.press(forDuration: 0.1, thenDragTo: start.withOffset(CGVector(dx: 90, dy: 90)))

    guard let after = boxSize(app) else {
      return XCTFail("the Layer size readout vanished during the drag")
    }
    XCTAssertNotEqual(
      before.width, after.width,
      "dragging the corner handle did not resize the fit-text box")
    // The readout rounds to whole pixels, so on a short box the ratio wobbles
    // by a few tenths without the shape actually drifting.
    XCTAssertEqual(
      before.width / before.height, after.width / after.height, accuracy: 0.5,
      "resizing the fit-text box did not hold the words' own shape")

    app.buttons["Cancel Placement"].tap()
  }

  /// Type has one shape, so the constrain toggle is locked while fitting text:
  /// a free box would promise a stretch the renderer cannot draw, which is how
  /// "fit text can't be resized" was experienced in the first place.
  func testConstrainProportionsIsLockedForText() {
    let app = openFitText()

    let constrain = app.descendants(matching: .any)
      .matching(identifier: "Constrain proportions").firstMatch
    XCTAssertTrue(constrain.exists, "there is no constrain-proportions control")
    XCTAssertFalse(constrain.isEnabled, "the constrain toggle must be locked for text")
    XCTAssertEqual(
      constrain.label, "Constrain proportions, on",
      "text placement must open with proportions held")

    // An edge drag must still resize — proportionally — rather than dead-end
    // the way the old height-only drag did.
    guard let before = boxSize(app) else {
      return XCTFail("no Layer size readout while fitting text")
    }
    let bottom = app.otherElements["Transform bottom"].firstMatch
    XCTAssertTrue(bottom.exists, "the fit-text box has no bottom edge handle")
    let start = bottom.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
    start.press(forDuration: 0.1, thenDragTo: start.withOffset(CGVector(dx: 0, dy: 60)))

    guard let after = boxSize(app) else {
      return XCTFail("the Layer size readout vanished during the drag")
    }
    XCTAssertNotEqual(
      before.height, after.height,
      "dragging the bottom edge did not resize the fit-text box")
    XCTAssertNotEqual(
      before.width, after.width,
      "an edge drag on locked proportions must scale both sides, not dead-end")

    app.buttons["Cancel Placement"].tap()
  }

  /// Dragging the interior moves the box without resizing it — even though a
  /// caption's box is far shorter than the 44pt handle radius.
  func testDraggingTheInteriorMovesTheBox() {
    let app = openFitText()

    let topLeft = app.otherElements["Transform top left"].firstMatch
    let bottomRight = app.otherElements["Transform bottom right"].firstMatch
    XCTAssertTrue(topLeft.exists && bottomRight.exists, "the fit-text box is missing handles")
    let cornerBefore = bottomRight.frame.origin
    guard let sizeBefore = boxSize(app) else {
      return XCTFail("no Layer size readout while fitting text")
    }

    // Dead centre of the box, reached from the top-left handle so the offset
    // is in screen points rather than guessed window coordinates.
    let toCentre = CGVector(
      dx: (bottomRight.frame.midX - topLeft.frame.midX) / 2,
      dy: (bottomRight.frame.midY - topLeft.frame.midY) / 2)
    let grab = topLeft.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
      .withOffset(toCentre)
    grab.press(forDuration: 0.1, thenDragTo: grab.withOffset(CGVector(dx: 60, dy: 40)))

    let cornerAfter = bottomRight.frame.origin
    XCTAssertNotEqual(cornerBefore, cornerAfter, "dragging the interior did not move the box")
    guard let sizeAfter = boxSize(app) else {
      return XCTFail("the Layer size readout vanished during the drag")
    }
    XCTAssertEqual(sizeBefore, sizeAfter, "an interior drag must move the box, not resize it")

    app.buttons["Cancel Placement"].tap()
  }
}

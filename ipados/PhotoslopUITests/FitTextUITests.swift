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
    XCTAssertNotEqual(
      before.height, after.height,
      "a corner drag scales both of its planes")

    app.buttons["Cancel Placement"].tap()
  }

  /// The box is a free container for text, so it opens unconstrained: each
  /// of the eight handles moves only its own plane unless the lock is chosen
  /// (#296). A version that opened locked made edge drags move both planes.
  func testUnconstrainedResizeChangesHeightIndependently() {
    let app = openFitText()

    let constrain = app.descendants(matching: .any)
      .matching(identifier: "Constrain proportions").firstMatch
    XCTAssertTrue(constrain.exists, "there is no constrain-proportions control")
    XCTAssertTrue(constrain.isEnabled, "the constrain toggle must be usable for text")
    XCTAssertEqual(
      constrain.label, "Constrain proportions, off",
      "a text box opens free — each handle moves only its own plane")

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
      "with constrain off, dragging the bottom edge did not change the height")
    XCTAssertEqual(
      before.width, after.width,
      "with constrain off, a bottom-edge drag must leave the width alone")

    app.buttons["Cancel Placement"].tap()
  }

  /// While the box is up, the words themselves must be visible inside it —
  /// device testing caught a preview that never appeared, leaving nothing to
  /// judge the size by until Done.
  func testTheWordsAreVisibleInsideTheBox() {
    let app = openFitText()
    let preview = app.descendants(matching: .any).matching(identifier: "Text preview").firstMatch
    XCTAssertTrue(preview.exists, "no live text preview inside the fit-text box")
    XCTAssertGreaterThan(preview.frame.width, 1, "the text preview has no size")
    app.buttons["Cancel Placement"].tap()
  }

  /// The face is part of the text sheet: every family the OS offers, plus the
  /// system font, chosen where the words are typed.
  func testTheTextSheetOffersAFontChoice() {
    let app = openEditor()
    // Add Text lives on the bar where there is room and in More Actions where
    // there is not — the same route `addText` takes.
    let barButton = app.navigationBars.buttons["Add Text"].firstMatch
    if barButton.waitForExistence(timeout: 10), barButton.isHittable {
      barButton.tap()
    } else {
      let more = app.navigationBars.buttons["More Actions"].firstMatch
      XCTAssertTrue(more.waitForExistence(timeout: 15), "no More Actions menu")
      more.tap()
      let addText = app.buttons["Add Text"].firstMatch
      XCTAssertTrue(addText.waitForExistence(timeout: 10), "Add Text is missing from the menu")
      addText.tap()
    }

    XCTAssertTrue(
      app.textFields["Type something"].waitForExistence(timeout: 20),
      "the text sheet never appeared")
    XCTAssertTrue(
      app.descendants(matching: .any).matching(identifier: "Font").firstMatch.exists,
      "the text sheet has no font control")
    app.buttons["Cancel"].firstMatch.tap()
  }

  /// The right edge scales the box on the very first grab (#298) — on device
  /// it "kept moving the box instead of scaling it" when the edge had been
  /// carried off screen, so the first touch after opening must already work.
  func testTheRightEdgeScalesOnTheFirstGrab() {
    let app = openFitText()
    guard let before = boxSize(app) else {
      return XCTFail("no Layer size readout while fitting text")
    }

    let right = app.otherElements["Transform right"].firstMatch
    XCTAssertTrue(right.exists, "the fit-text box has no right edge handle")
    let start = right.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
    start.press(forDuration: 0.1, thenDragTo: start.withOffset(CGVector(dx: 70, dy: 0)))

    guard let after = boxSize(app) else {
      return XCTFail("the Layer size readout vanished during the drag")
    }
    XCTAssertNotEqual(
      before.width, after.width, "the first grab of the right edge must scale, not move")
    // A caption's box is shorter than the corner-priority radius, so this
    // grab may land a right corner instead of the edge — still a scale of
    // the horizontal plane, with only drag wobble on the vertical.
    XCTAssertEqual(
      before.height, after.height, accuracy: 3,
      "a right-side drag must not meaningfully change the vertical plane")

    app.buttons["Cancel Placement"].tap()
  }

  /// A size that runs past the canvas asks before it cuts words off (#298):
  /// Shrink to Fit, keep it knowing the overflow is cut, or keep editing.
  func testAnOverflowingEditAsksBeforeCuttingWordsOff() {
    let app = openFitText()

    // Fit the caption to the box as it opened, so the layer has a container.
    app.buttons["Apply Placement"].tap()
    XCTAssertTrue(
      app.buttons["Apply Placement"].firstMatch.waitForNonExistence(timeout: 20),
      "applying the fit did not close the placement bar")

    // Adding text leaves Move Text mode running; leave it the way a person
    // would, or the editor is not in its resting state for the menu.
    let doneMoving = app.buttons["Done"].firstMatch
    if doneMoving.exists, doneMoving.isHittable { doneMoving.tap() }

    let more = app.navigationBars.buttons["More Actions"].firstMatch
    XCTAssertTrue(more.waitForExistence(timeout: 15), "no More Actions menu")
    more.tap()
    let edit = app.buttons["Edit Text"].firstMatch
    XCTAssertTrue(edit.waitForExistence(timeout: 10), "Edit Text is missing from the menu")
    edit.tap()

    XCTAssertTrue(
      app.navigationBars["Edit Text"].waitForExistence(timeout: 20),
      "the text sheet never appeared")
    // A filled multi-line TextField is exposed as a text view, unlike the
    // empty one the Add flow queries. Enough words typed into it that,
    // wrapped at the fitted box's width, the layout runs far past the
    // canvas bottom at the current size.
    // Once filled, the field keeps neither its placeholder identifier nor a
    // label — it is simply the sheet's one text field.
    var field = app.textFields["Type something"].firstMatch
    if !field.waitForExistence(timeout: 5) { field = app.textFields.firstMatch }
    XCTAssertTrue(field.waitForExistence(timeout: 5), "the text sheet has no editable words")
    field.tap()
    field.typeText(
      String(repeating: " why are we all so afraid of being a minority in america", count: 25))

    app.buttons["Save"].firstMatch.tap()
    // On iPad the dialog is a popover, which drops the cancel-role button —
    // the offer itself is what must exist. Shrinking commits and closes.
    let shrink = app.buttons.matching(
      NSPredicate(format: "label BEGINSWITH %@", "Shrink to Fit")
    ).firstMatch
    XCTAssertTrue(
      shrink.waitForExistence(timeout: 10),
      "an edit that runs past the canvas must ask before cutting words off")
    shrink.tap()
    XCTAssertTrue(
      app.navigationBars["Edit Text"].waitForNonExistence(timeout: 10),
      "choosing Shrink to Fit should save and close the sheet")
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

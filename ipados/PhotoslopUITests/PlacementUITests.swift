// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Placing and resizing what is on the canvas.
///
/// The arithmetic belongs to `PlacementAndScaleTests`, which can assert on
/// pixels without a screen. What only a running app can answer is whether a
/// single imported photo actually stops to be placed instead of being stretched
/// to the canvas behind your back (#266), whether a layer already in the
/// document can be resized at all (#262), and whether the document can be
/// scaled rather than merely padded (#269).
final class PlacementUITests: UITestCase {
  private func skipUnlessCompact() throws {
    try XCTSkipUnless(
      UIDevice.current.userInterfaceIdiom == .phone,
      "the layer list is a sheet at compact width, which is the deterministic route to import")
  }

  /// The user's report, in their words: "importing an image into a layer is
  /// still scaling that layer to the entire canvas. I want it to import as its
  /// original size and automatically be in the crop dialog with a constrain
  /// proportions toggle."
  func testASingleImportedPhotoStopsToBePlaced() throws {
    try skipUnlessCompact()
    let app = openEditor()

    XCTAssertTrue(app.openLayerList(), "the layer list could not be reached")
    app.buttons["New layer from photo"].firstMatch.tap()
    XCTAssertTrue(app.buttons["Choose"].waitForExistence(timeout: 20), "no import source sheet")
    app.buttons["Choose"].tap()

    let thumbnails = app.images.matching(NSPredicate(format: "label BEGINSWITH 'Photo,'"))
    try XCTSkipUnless(
      thumbnails.element(boundBy: 0).waitForExistence(timeout: 25),
      "this simulator's photo library is empty")
    thumbnails.element(boundBy: 0)
      .coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    if app.buttons["Add"].waitForExistence(timeout: 10) { app.buttons["Add"].tap() }

    // The placement bar, not the tool strip: the import is waiting to be put
    // somewhere rather than already committed at the canvas's size.
    XCTAssertTrue(
      app.buttons["Apply Placement"].waitForExistence(timeout: 30),
      "a single imported photo did not stop to be placed")
    XCTAssertTrue(
      app.staticTexts["Layer size"].firstMatch.exists,
      "no live pixel readout while placing — the size being chosen is invisible")

    // Constrain proportions is on by default, and is one tap to release.
    // Queried across element types: a Toggle with `.button` style is reported
    // as a button on some versions and a switch on others, and which one it is
    // says nothing about whether a finger can use it.
    let constrain = app.descendants(matching: .any)
      .matching(identifier: "Constrain proportions").firstMatch
    XCTAssertTrue(constrain.exists, "there is no constrain-proportions control")
    XCTAssertEqual(
      constrain.label, "Constrain proportions, on",
      "constrain proportions should start on — a distorted import is never the default")

    let window = app.windows.firstMatch.frame
    for name in ["Cancel Placement", "Constrain proportions", "Apply Placement"] {
      let control = app.descendants(matching: .any).matching(identifier: name).firstMatch
      XCTAssertTrue(
        window.contains(control.frame),
        "\(name) is outside the window at \(control.frame) — the placement bar is over budget")
    }

    app.buttons["Apply Placement"].tap()
    XCTAssertTrue(
      app.buttons["Tool, Pen"].firstMatch.waitForExistence(timeout: 20),
      "applying the placement did not return to the editor")
  }

  /// A layer that came in the wrong size has to be fixable afterwards (#262):
  /// "One image was too small for the canvas and one was too big."
  func testAnExistingLayerCanBeResized() {
    let app = openEditor()

    let more = app.navigationBars.buttons["More Actions"].firstMatch
    XCTAssertTrue(more.waitForExistence(timeout: 15), "no More Actions menu")
    more.tap()

    let resize = app.buttons["Resize Layer…"].firstMatch
    XCTAssertTrue(resize.waitForExistence(timeout: 10), "there is no way to resize a placed layer")
    resize.tap()

    XCTAssertTrue(
      app.buttons["Apply Placement"].waitForExistence(timeout: 20),
      "Resize Layer did not open the placement box")
    XCTAssertTrue(
      app.otherElements["Transform bottom right"].firstMatch.exists,
      "the placement box has no corner handle to drag")

    // Leave the document exactly as it was found: this target shares one.
    app.buttons["Cancel Placement"].tap()
    XCTAssertTrue(
      app.buttons["Tool, Pen"].firstMatch.waitForExistence(timeout: 20),
      "cancelling the placement did not return to the editor")
  }

  /// Resize Document scales the picture; Canvas Size pads it. Both have to be
  /// on the menu, and they have to say which is which (#269).
  func testResizeDocumentIsOfferedAlongsideCanvasSize() {
    let app = openEditor()

    let more = app.navigationBars.buttons["More Actions"].firstMatch
    XCTAssertTrue(more.waitForExistence(timeout: 15), "no More Actions menu")
    more.tap()

    let resize = app.buttons["Resize Document…"].firstMatch
    XCTAssertTrue(
      resize.waitForExistence(timeout: 10),
      "there is no way to scale a document — only to pad it or crop it")
    resize.tap()

    XCTAssertTrue(
      app.navigationBars["Resize Document"].waitForExistence(timeout: 20),
      "Resize Document did not open the size sheet")
    XCTAssertTrue(
      app.buttons["Scale"].firstMatch.exists,
      "the confirm button should say Scale, not Resize — the difference is the whole point")
    XCTAssertTrue(
      app.staticTexts.containing(
        NSPredicate(format: "label CONTAINS %@", "Scales the whole picture")
      ).firstMatch.exists,
      "the sheet does not say what it will do, and Canvas Size looks identical")

    app.buttons["Cancel"].firstMatch.tap()
  }
}

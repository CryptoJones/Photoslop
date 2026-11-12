// SPDX-License-Identifier: Apache-2.0
import XCTest

/// A design tour: drives the editor through its states and photographs each.
///
/// Not a test of anything — it exists so the chrome can be looked at, on a
/// real device, at the size a person holds it. Skipped unless asked for by
/// name (`PHOTOSLOP_DESIGN_TOUR=1`).
final class DesignTourUITests: UITestCase {
  private func shoot(_ app: XCUIApplication, _ name: String) {
    let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
    attachment.name = name
    attachment.lifetime = .keepAlways
    add(attachment)
  }

  func testTourTheEditor() throws {
    try XCTSkipUnless(
      ProcessInfo.processInfo.environment["PHOTOSLOP_DESIGN_TOUR"] == "1",
      "the design tour runs only when explicitly asked for")
    let app = openEditor()
    shoot(app, "a-editor")

    app.buttons["Bucket"].firstMatch.tap()
    shoot(app, "b-bucket")

    app.buttons["Magic Wand"].firstMatch.tap()
    let canvas = app.descendants(matching: .any)
      .matching(NSPredicate(format: "label == %@", "Editable image canvas")).firstMatch
    if canvas.waitForExistence(timeout: 15) {
      canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    }
    shoot(app, "c-selection")

    app.buttons["Deselect"].firstMatch.tap()
    app.buttons["Pen"].firstMatch.tap()
    shoot(app, "d-pen")

    if app.navigationBars.buttons["Layers"].firstMatch.waitForExistence(timeout: 5) {
      app.navigationBars.buttons["Layers"].firstMatch.tap()
      shoot(app, "e-layers")
      app.buttons["Done"].firstMatch.tap()
    }

    // Crop replaces the whole dock on a phone, so the crop bar has to stand on
    // its own.
    app.revealAction("Crop…").tap()
    shoot(app, "g-crop")
    app.buttons["Cancel Crop"].firstMatch.tap()

    app.openMoreActions()
    shoot(app, "f-menu")
    app.dismissMenu()
  }
}

// SPDX-License-Identifier: Apache-2.0
import XCTest

/// About is where someone looks to confirm what they are running, so the name it
/// shows has to be the truth. It read "Photoslop for iPad" on every device,
/// including every iPhone.
///
/// The fix names no platform, matching the desktop edition. That is why this
/// asserts the absence of a device name rather than the presence of the right
/// one: there is no per-device answer to get wrong.
final class AboutUITests: UITestCase {
  func testAboutNamesNoDevice() {
    let app = XCUIApplication()
    app.openNewDocument()

    XCTAssertTrue(app.openAbout(), "could not reach About")
    XCTAssertTrue(
      app.staticTexts["Photoslop"].waitForExistence(timeout: 10),
      "About does not name the app")

    for wrong in ["Photoslop for iPad", "Photoslop for iPhone", "Photoslop for Mac"] {
      XCTAssertFalse(app.staticTexts[wrong].exists, "About claims to be \(wrong)")
    }
  }

  /// The version rows are what actually identify the build, so they carry more
  /// weight now that the headline says less.
  func testAboutReportsVersionAndBuild() {
    let app = XCUIApplication()
    app.openNewDocument()

    XCTAssertTrue(app.openAbout(), "could not reach About")
    for row in ["Version", "Build"] {
      XCTAssertTrue(
        app.staticTexts.matching(
          NSPredicate(format: "label BEGINSWITH %@", "\(row), ")
        ).firstMatch.waitForExistence(timeout: 10),
        "About does not report \(row)")
    }
  }
}

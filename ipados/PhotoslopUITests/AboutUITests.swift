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
    let app = openEditor()

    XCTAssertTrue(app.openAbout(), "could not reach About")
    XCTAssertTrue(
      app.staticTexts["Photoslop"].waitForExistence(timeout: 10),
      "About does not name the app")

    for wrong in ["Photoslop for iPad", "Photoslop for iPhone", "Photoslop for Mac"] {
      XCTAssertFalse(app.staticTexts[wrong].exists, "About claims to be \(wrong)")
    }
  }

  /// The desktop About carries a description, a licence, a repo link and the
  /// mascot. These are the same, so the two editions introduce the app alike.
  func testAboutCarriesWhatTheDesktopAboutCarries() {
    let app = openEditor()

    XCTAssertTrue(app.openAbout(), "could not reach About")
    XCTAssertTrue(
      app.images["Photoslop mascot"].waitForExistence(timeout: 10),
      "About is missing the mascot")
    XCTAssertTrue(
      app.staticTexts["A memory-frugal, multiplatform, layered raster image editor."]
        .waitForExistence(timeout: 10),
      "About is missing the description the desktop leads with")

    // The sheet opens at its medium detent, so the lower rows start below the
    // fold. It can be dragged up now, which is the point of the large detent.
    app.swipeUp()
    XCTAssertTrue(
      app.staticTexts["License, Apache-2.0"].waitForExistence(timeout: 10),
      "About does not state the licence")
    // A `Link` whose title is not the URL is exposed as a button, not a link;
    // only the xkcd one, which shows its own URL, comes through as both.
    XCTAssertTrue(
      app.buttons["github.com/CryptoJones/Photoslop"].waitForExistence(timeout: 10),
      "About does not link the repository")
  }

  /// About is the one sheet whose content grows, and it was pinned to a single
  /// medium detent — half height on a phone with no way to drag up.
  func testAboutCanBeExpanded() {
    let app = openEditor()

    XCTAssertTrue(app.openAbout(), "could not reach About")
    XCTAssertTrue(
      app.buttons["Sheet Grabber"].waitForExistence(timeout: 10),
      "About offers no way to expand; it has more than one detent or it has none")
  }

  /// The version rows are what actually identify the build, so they carry more
  /// weight now that the headline says less.
  func testAboutReportsVersionAndBuild() {
    let app = openEditor()

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

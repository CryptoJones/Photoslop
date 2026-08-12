// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Exporting into the Photos library.
///
/// Export reached only the Files hierarchy, because `fileExporter` presents a
/// document picker. On a phone that is the wrong destination for a finished
/// picture — Photos is what the camera roll and the share sheet mean by "my
/// photos" — and the only way there was to save into Files and import by hand.
///
/// The permission is granted ahead of the run with
/// `xcrun simctl privacy <device> grant photos-add io.ronin48.photoslop.ipad`,
/// so these tests exercise the save rather than the system consent dialog. A
/// denied library is a different path and is reported through the error alert.
final class ExportDestinationUITests: UITestCase {
  func testExportOffersPhotosAsWellAsFiles() {
    let app = XCUIApplication()
    app.openNewDocument()

    app.navigationBars.buttons["Export Image"].firstMatch.tap()
    XCTAssertTrue(
      app.navigationBars["Export Image"].waitForExistence(timeout: 15),
      "the export sheet never appeared")

    for destination in ["Files", "Photos"] {
      XCTAssertTrue(
        app.buttons[destination].firstMatch.waitForExistence(timeout: 10),
        "\(destination) is not offered as an export destination")
    }
  }

  /// Choosing Photos and saving has to say so. The picture leaves for another
  /// app's library and nothing on this screen changes, so without the
  /// confirmation a successful export is indistinguishable from having done
  /// nothing at all.
  func testSavingToPhotosConfirmsItWorked() {
    let app = XCUIApplication()
    app.openNewDocument()

    app.navigationBars.buttons["Export Image"].firstMatch.tap()
    XCTAssertTrue(
      app.navigationBars["Export Image"].waitForExistence(timeout: 15),
      "the export sheet never appeared")

    app.buttons["Photos"].firstMatch.tap()
    app.buttons["Export"].firstMatch.tap()

    XCTAssertTrue(
      app.staticTexts["Saved to Photos"].waitForExistence(timeout: 60),
      "saving to Photos gave no confirmation, so it cannot be told from doing nothing")
    app.buttons["OK"].firstMatch.tap()
  }

  /// Photos does not reliably accept BMP, GIF or TIFF, and a rejected
  /// `addResource` fails after the render with an opaque error. The format list
  /// narrows instead of failing late.
  func testPhotosOffersOnlyTheFormatsItAccepts() {
    let app = XCUIApplication()
    app.openNewDocument()

    app.navigationBars.buttons["Export Image"].firstMatch.tap()
    XCTAssertTrue(
      app.navigationBars["Export Image"].waitForExistence(timeout: 15),
      "the export sheet never appeared")

    app.buttons["Photos"].firstMatch.tap()

    // A Picker row in a Form is a button labelled "Format, <value>", not one
    // labelled "Format".
    let formatRow = app.buttons.matching(
      NSPredicate(format: "label BEGINSWITH %@", "Format")
    ).firstMatch
    XCTAssertTrue(formatRow.waitForExistence(timeout: 10), "no Format row on the export sheet")
    formatRow.tap()

    for accepted in ["PNG", "JPEG", "HEIC"] {
      XCTAssertTrue(
        app.buttons[accepted].firstMatch.waitForExistence(timeout: 10),
        "\(accepted) should be offered for Photos")
    }
    for rejected in ["BMP", "GIF", "TIFF"] {
      XCTAssertFalse(
        app.buttons[rejected].firstMatch.exists,
        "\(rejected) is not reliably accepted by Photos and must not be offered")
    }
  }
}

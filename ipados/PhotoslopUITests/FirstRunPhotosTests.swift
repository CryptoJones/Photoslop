// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Saving to Photos on a first run, with the permission still undecided.
///
/// Every other export test runs against a simulator that was granted
/// `photos-add` beforehand, so the branch a real first-time user takes —
/// system prompt, Allow, then the save — has never been exercised. That is the
/// state App Review is in.
final class FirstRunPhotosTests: UITestCase {
  func testAllowingAtTheSystemPromptStillSaves() throws {
    let app = openEditor()
    app.navigationBars.buttons["Export Image"].firstMatch.tap()
    XCTAssertTrue(
      app.navigationBars["Export Image"].waitForExistence(timeout: 15),
      "the export sheet never appeared")
    app.buttons["Photos"].firstMatch.tap()
    app.buttons["Export"].firstMatch.tap()

    // The permission alert belongs to Springboard, not to this app, so it has
    // to be reached there. An interruption monitor is the documented route and
    // is unreliable when the alert is already up by the time it is installed.
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    // Exact labels, not a CONTAINS: the add-only prompt's two buttons are
    // "Allow" and "Don't Allow", and a substring match on "Allow" happily
    // picks the wrong one.
    let allow = springboard.buttons.matching(
      NSPredicate(format: "label ==[c] 'Allow' OR label ==[c] 'Allow Full Access'")
    ).firstMatch
    // The prompt must be the ADD-ONLY one. Without
    // NSPhotoLibraryAddUsageDescription iOS falls back to the read/write key
    // and asks for full library access instead — thumbnails of the user's
    // photos, a "Limit Access" option, and the *import* usage string shown to
    // someone who is trying to save. That is a privacy over-ask and a
    // Guideline 5.1.1 risk, and it is invisible to every other test here
    // because they run against a simulator that was granted the permission
    // beforehand.
    let readPrompt = springboard.buttons["Limit Access…"].firstMatch
    XCTAssertFalse(
      readPrompt.waitForExistence(timeout: 8),
      "this is the full-library READ prompt; the app only asks for add-only access")

    if allow.waitForExistence(timeout: 25) {
      allow.tap()
    } else {
      // No prompt means the decision has already been made on this device —
      // an earlier test in the run reached the same code path, or the
      // simulator was granted up front. That is a precondition this test
      // cannot create for itself (permissions cannot be reset from inside a
      // test), so it skips rather than reporting an app fault it has not
      // observed. `xcrun simctl privacy <device> reset photos-add
      // io.ronin48.photoslop.ipad` before an isolated run.
      throw XCTSkip("photo-add permission is already decided on this device")
    }

    XCTAssertTrue(
      app.staticTexts["Saved to Photos"].waitForExistence(timeout: 60),
      "allowed at the prompt and the save still never confirmed")
    app.buttons["OK"].firstMatch.tap()
  }
}

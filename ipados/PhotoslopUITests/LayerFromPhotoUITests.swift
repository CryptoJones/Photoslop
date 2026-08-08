// SPDX-License-Identifier: Apache-2.0
import XCTest

/// The route to "new layer from photo".
///
/// What the layers get filled with is covered by `EditorStoreTests`, which can
/// assert on pixels and undo. What only a running app can answer is whether the
/// button is reachable and whether it actually raises the photo picker — the
/// picker is a separate process, so a plain unit test cannot see it at all.
final class LayerFromPhotoUITests: UITestCase {
  func testNewLayerFromPhotoIsReachableAndOpensThePicker() {
    let app = XCUIApplication()
    app.openNewDocument()

    // On a phone the layer list is a sheet; on iPad it is already beside the
    // canvas.
    let layers = app.navigationBars.buttons["Layers"]
    if layers.waitForExistence(timeout: 10), layers.isHittable {
      layers.tap()
    }

    let button = app.buttons["New layer from photo"]
    XCTAssertTrue(
      button.waitForExistence(timeout: 15),
      "there is no way to make a layer from a photo")
    XCTAssertTrue(button.isHittable, "the button is present but cannot be tapped")
    button.tap()

    // The picker belongs to another process, so match on its chrome rather than
    // on anything of ours.
    let picker = XCUIApplication(bundleIdentifier: "com.apple.mobileslideshow")
    let cancel = app.buttons["Cancel"]
    XCTAssertTrue(
      picker.wait(for: .runningForeground, timeout: 20)
        || cancel.waitForExistence(timeout: 5),
      "tapping it did not raise the photo picker")
  }
}

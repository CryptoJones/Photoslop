// SPDX-License-Identifier: Apache-2.0
import XCTest

/// The crop mode.
///
/// The arithmetic is `CropGeometryTests`' job and the canvas operation is
/// `EditorStoreTests`' — what only a running app can answer is whether the
/// handles are reachable, whether dragging one moves the rectangle rather than
/// painting a stroke underneath it, and whether the mode can be left without
/// changing the document.
final class CropUITests: UITestCase {
  @discardableResult
  private func beginCrop() -> XCUIApplication {
    // Shared app: the editor is reused when the previous test provably left it
    // there, so crop pays a launch only when it has to (#254).
    let app = openEditor()

    let more = app.navigationBars.buttons["More Actions"].firstMatch
    XCTAssertTrue(more.waitForExistence(timeout: 15), "no More Actions menu on the bar")
    more.tap()

    let crop = app.buttons["Crop…"].firstMatch
    XCTAssertTrue(crop.waitForExistence(timeout: 10), "Crop is missing from the menu")
    crop.tap()
    return app
  }

  func testCropModeOffersHandlesASizeReadoutAndAnAspectLock() {
    let app = beginCrop()

    XCTAssertTrue(
      app.staticTexts["Crop size"].firstMatch.waitForExistence(timeout: 15),
      "no live pixel readout — the point of cropping by eye is knowing the size you land on")
    // Reachability is asserted as geometry, not as `isHittable`.
    //
    // XCUITest reports a SwiftUI Menu as a Button wrapping a Button, and
    // `isHittable` on the outer one is false because the tap belongs to the
    // inner. That is a fact about the framework's hit-test model, not about
    // whether a finger can reach the control — the hierarchy shows the bar
    // correctly placed, with Cancel at x=16, the aspect menu at x=381 and Crop
    // at x=756, all inside the window and nothing above them in the tree.
    //
    // Chasing that `isHittable` cost four fixes to a fault that did not exist
    // (see LESSONSLEARNED.md L-001). What the test actually needs to know is
    // that the control is inside the window and that operating it works, and
    // both are checked without relying on the framework's notion of hittable.
    let window = app.windows.firstMatch.frame
    for name in ["Crop aspect", "Apply Crop", "Cancel Crop"] {
      let control = app.buttons[name].firstMatch
      XCTAssertTrue(control.exists, "\(name) is missing from the crop bar")
      XCTAssertTrue(
        window.contains(control.frame),
        """
        \(name) is outside the window at \(control.frame), window \(window) — \
        the crop bar is over its budget for this device.
        """)
    }

    // Every corner and edge has to be grabbable, not just the corners.
    for handle in [
      "top left", "top", "top right", "left", "right", "bottom left", "bottom", "bottom right",
    ] {
      let element = app.otherElements["Crop \(handle)"].firstMatch
      XCTAssertTrue(element.exists, "the \(handle) handle is missing")
    }
  }

  /// Landscape is where this broke on CI and portrait never showed it.
  ///
  /// The crop controls rendered at y=1147 on a screen 834 tall — in the
  /// hierarchy, outside the window, impossible to tap. Every crop test until now
  /// ran portrait, and the reachability assertion cannot fire on a screen that
  /// happens to be tall enough.
  func testTheCropBarIsReachableInLandscapeToo() throws {
    // iPad only. The fault this covers was an iPad one, and on a phone the
    // launch scene's Create Document cannot be tapped in landscape at all —
    // a separate problem, filed rather than worked around here, and not
    // something this test should be the one to discover.
    try XCTSkipUnless(
      UIDevice.current.userInterfaceIdiom == .pad,
      "the phone launch scene has its own landscape fault; see the tracker")

    XCUIDevice.shared.orientation = .landscapeLeft
    let app = beginCrop()

    let window = app.windows.firstMatch.frame
    for name in ["Crop aspect", "Apply Crop", "Cancel Crop"] {
      let control = app.buttons[name].firstMatch
      XCTAssertTrue(control.waitForExistence(timeout: 15), "\(name) is missing in landscape")
      XCTAssertTrue(
        window.contains(control.frame),
        "\(name) is outside the window at y=\(control.frame.minY), window height \(window.height)")
    }
  }

  /// Cancel has to be a true no-op. A crop mode that alters the document on the
  /// way out is worse than one that does nothing.
  func testCancellingLeavesTheDocumentAlone() {
    let app = beginCrop()

    XCTAssertTrue(app.buttons["Cancel Crop"].firstMatch.waitForExistence(timeout: 15))
    app.buttons["Cancel Crop"].firstMatch.tap()

    // Back to the editor, with the tool strip rather than the crop bar.
    XCTAssertTrue(
      app.buttons["Tool, Pen"].firstMatch.waitForExistence(timeout: 15),
      "cancelling crop did not return to the editor")
    XCTAssertFalse(
      app.buttons["Apply Crop"].firstMatch.exists, "the crop bar is still up after cancelling")
  }

  /// Locking an aspect ratio reshapes the rectangle immediately rather than
  /// waiting for the next drag, so the choice is visible when it is made.
  func testLockingAnAspectRatioReshapesTheRectangle() {
    let app = beginCrop()

    let readout = app.staticTexts["Crop size"].firstMatch
    XCTAssertTrue(readout.waitForExistence(timeout: 15))
    let before = readout.label

    // By coordinate: XCUITest refuses to tap the Menu's outer element directly
    // and tries to scroll it into view first, which fails. A coordinate tap is
    // what a finger does.
    app.buttons["Crop aspect"].firstMatch
      .coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    let square = app.buttons["1:1"].firstMatch
    XCTAssertTrue(square.waitForExistence(timeout: 10), "the aspect menu offers no square")
    square.tap()

    XCTAssertTrue(
      readout.waitForExistence(timeout: 10),
      "the readout disappeared after locking an aspect ratio")
    XCTAssertNotEqual(
      readout.label, before,
      "locking 1:1 on a non-square canvas should have reshaped the rectangle")
  }

  /// Dragging a handle has to resize the crop, not draw on the layer under it.
  func testDraggingAHandleResizesTheCropInsteadOfDrawing() {
    let app = beginCrop()

    let readout = app.staticTexts["Crop size"].firstMatch
    XCTAssertTrue(readout.waitForExistence(timeout: 15))
    let before = readout.label

    let handle = app.otherElements["Crop bottom right"].firstMatch
    XCTAssertTrue(handle.exists, "no bottom right handle to drag")
    handle.press(
      forDuration: 0.1,
      thenDragTo: app.otherElements["Crop top left"].firstMatch,
      withVelocity: .slow,
      thenHoldForDuration: 0.1)

    XCTAssertNotEqual(readout.label, before, "dragging the corner did not resize the crop")
  }

  /// Zooming while cropping (#270).
  ///
  /// The canvas froze the moment a crop began, because suspending drawing was
  /// done by switching off hit-testing for the whole scroll view — which took
  /// pinch, zoom and pan with it. Choosing a crop edge precisely is exactly
  /// when you want to zoom in, and it was the one moment the app refused.
  ///
  /// The assertion is deliberately in two halves, because together they are
  /// also the proof that the overlay and the document share a coordinate
  /// space: after a pinch the rectangle must be **bigger on screen** and the
  /// same **size in pixels**. If the readout moved, the box is being measured
  /// against the wrong thing, which is how #260 and #268 happened.
  func testPinchingZoomsTheCanvasWhileCropping() {
    let app = beginCrop()

    let readout = app.staticTexts["Crop size"].firstMatch
    XCTAssertTrue(readout.waitForExistence(timeout: 15))
    let sizeInPixels = readout.label

    let handle = app.otherElements["Crop top left"].firstMatch
    XCTAssertTrue(handle.exists, "no handle to measure")
    let opposite = app.otherElements["Crop bottom right"].firstMatch
    XCTAssertTrue(opposite.exists)
    let spanBefore = opposite.frame.midX - handle.frame.midX
    XCTAssertGreaterThan(spanBefore, 0, "the crop box has no width on screen to begin with")

    app.scrollViews.firstMatch.pinch(withScale: 2.5, velocity: 2)

    let spanAfter =
      app.otherElements["Crop bottom right"].firstMatch.frame.midX
      - app.otherElements["Crop top left"].firstMatch.frame.midX
    XCTAssertGreaterThan(
      spanAfter, spanBefore * 1.2,
      """
      pinching did not zoom the canvas during a crop: the box spans \(spanAfter)pt \
      where it spanned \(spanBefore)pt before.
      """)
    XCTAssertEqual(
      readout.label, sizeInPixels,
      "zooming changed the crop size in pixels, so the box is measured against the screen")
  }

  /// A second crop has to start from the canvas the first one produced (#268).
  ///
  /// It started from the original instead, because the overlay was told the
  /// canvas's on-screen rectangle asynchronously while the canvas size updated
  /// synchronously — so a crop begun before the news arrived divided the new,
  /// smaller canvas by the old, larger rectangle.
  func testASecondCropStartsFromTheCroppedDocument() {
    let app = beginCrop()

    let readout = app.staticTexts["Crop size"].firstMatch
    XCTAssertTrue(readout.waitForExistence(timeout: 15))

    // Shrink the rectangle so the crop actually changes the canvas.
    app.otherElements["Crop bottom right"].firstMatch.press(
      forDuration: 0.1,
      thenDragTo: app.otherElements["Crop top left"].firstMatch,
      withVelocity: .slow,
      thenHoldForDuration: 0.1)
    let croppedSize = readout.label

    app.buttons["Apply Crop"].firstMatch.tap()
    XCTAssertTrue(
      app.buttons["Tool, Pen"].firstMatch.waitForExistence(timeout: 15),
      "the crop never applied")

    beginCrop()
    let reopened = app.staticTexts["Crop size"].firstMatch
    XCTAssertTrue(reopened.waitForExistence(timeout: 15), "the crop bar did not come back")
    XCTAssertEqual(
      reopened.label, croppedSize,
      """
      the second crop opened on \(reopened.label) when the document is now \
      \(croppedSize) — it is still working from the canvas before the first crop.
      """)

    // Put the document back. Every test in this target shares one document, and
    // this is the only test that shrinks the canvas to its minimum — on a
    // 16-pixel canvas the eight crop handles land on top of one another and the
    // *next* test fails on a handle it cannot reach. A test that changes the
    // shared document owns undoing it.
    app.buttons["Cancel Crop"].firstMatch.tap()
    let undo = app.buttons["Undo"].firstMatch
    if undo.waitForExistence(timeout: 15), undo.isHittable { undo.tap() }
  }
}

// SPDX-License-Identifier: Apache-2.0
import XCTest

/// Toolbar reachability, which only a running app can answer.
///
/// The unit tests cover what export produces; they cannot see whether the
/// control that starts it survives a phone-width navigation bar. It did not.
/// Every document action went on one bar, and at iPhone width UIKit collapsed
/// the leading group into an overflow menu and dropped the trailing group —
/// Undo, Redo, Export and About — entirely, leaving no way to export at all.
final class EditorToolbarUITests: UITestCase {
  /// Export has to be on the bar itself on every device, not behind a menu and
  /// certainly not missing: it is the only way to get artwork out of the app.
  func testExportIsOnTheToolbarAndOpensTheExportSheet() {
    let app = openEditor()

    let export = app.navigationBars.buttons["Export Image"]
    XCTAssertTrue(export.waitForExistence(timeout: 10), "Export is not on the navigation bar")
    XCTAssertTrue(export.isHittable, "Export is on the bar but cannot be tapped")
    export.tap()

    XCTAssertTrue(
      app.navigationBars["Export Image"].waitForExistence(timeout: 10),
      "tapping Export did not open the export sheet")
    XCTAssertTrue(app.buttons["Export"].waitForExistence(timeout: 10))
  }

  /// Undo and redo are used mid-drawing, so they have to be one tap wherever
  /// they sit — the navigation bar on iPad, the tool strip on a phone.
  func testUndoAndRedoAreOneTapAway() {
    let app = openEditor()

    for label in ["Undo", "Redo"] {
      let button = app.buttons[label]
      XCTAssertTrue(button.waitForExistence(timeout: 10), "\(label) is not on screen")
      XCTAssertTrue(button.isHittable, "\(label) is on screen but cannot be tapped")
    }
  }

  /// What does not fit on a phone goes in one menu the app controls, rather
  /// than being handed to UIKit's overflow and silently losing half of it.
  func testCompactWidthKeepsEveryOtherActionInOneMenu() throws {
    // The iPad has its own More Actions menu now, but a different one: Layers
    // is a sidebar there rather than a bar button, and About stays on the bar.
    try XCTSkipUnless(
      UIDevice.current.userInterfaceIdiom == .phone,
      "the iPad menu holds a different set; this pins the phone's")
    let app = openEditor()

    XCTAssertTrue(
      app.navigationBars.buttons["Layers"].waitForExistence(timeout: 10),
      "Layers is not on the navigation bar; it is the only route to the layer list on a phone")

    let more = app.navigationBars.buttons["More Actions"]
    XCTAssertTrue(more.waitForExistence(timeout: 10), "the overflow menu is not on the bar")
    more.tap()

    for label in [
      "New", "Canvas Size", "Resize Document…", "Crop…", "Flatten Image", "Add Text",
      "Import Image…", "About Photoslop",
    ] {
      XCTAssertTrue(
        app.buttons[label].waitForExistence(timeout: 10), "\(label) is missing from the menu")
    }
  }

  /// Nothing may be handed to UIKit's own overflow, on any device.
  ///
  /// This is the assertion that would have caught the iPad mini: at 744pt the
  /// regular-width layout put five leading and four trailing items on the bar,
  /// UIKit collapsed the trailing group behind a chevron, and Export Image left
  /// the bar. Every other test still passed, because they all reached Export
  /// through a query that does not care whether a button is on the bar or in
  /// the system overflow — the failure only ever showed up as the *next* test
  /// timing out on "the editor never came up".
  func testNothingIsHandedToTheSystemOverflow() {
    let app = openEditor()

    let overflow = app.navigationBars.buttons["OverflowBarButtonItem"]
    XCTAssertFalse(
      overflow.exists,
      """
      UIKit collapsed part of the navigation bar into its own overflow, which \
      hides actions behind an unlabelled chevron. The bar is over budget for \
      this device's width — move something into the app's own More Actions menu.
      """)
  }

  /// The bar's item count may not depend on the document's contents.
  ///
  /// Edit Text and Move Text appear only while a text layer is active, so on a
  /// narrow bar the toolbar fit until the moment someone added text and then
  /// silently overflowed. A bar that changes size as you work is one no test
  /// written before that step can catch, which is why they now live in the
  /// menu at every width that is not provably wide enough.
  func testAddingTextDoesNotPushActionsOffTheBar() {
    let app = openEditor()
    let barItemsBefore = app.navigationBars.buttons.count

    app.addText("Hi")

    XCTAssertFalse(
      app.navigationBars.buttons["OverflowBarButtonItem"].exists,
      "adding a text layer pushed the navigation bar into UIKit's overflow")
    XCTAssertEqual(
      app.navigationBars.buttons.count, barItemsBefore,
      "the navigation bar gained or lost items because a text layer became active")
    XCTAssertTrue(
      app.navigationBars.buttons["Export Image"].exists, "Export left the bar once text was added")
  }

  /// Every tool-strip control must be reachable without scrolling.
  ///
  /// The strip is a horizontal ScrollView with no indicator, so overflow does
  /// not look like overflow — the control is simply not there. Measured before
  /// this test existed: on a 402pt iPhone the brush width slider sat at x=415.7
  /// and on a 744pt iPad mini at x=773.5, while the ink well was not in the
  /// accessibility tree at all. Ink colour and brush width are the two controls
  /// a painting app touches most, and neither was on screen on either device.
  ///
  /// This is the tool strip's equivalent of
  /// `testNothingIsHandedToTheSystemOverflow`: the navigation bar grew a budget
  /// after #227 and #242, and the strip had none. Adding a tool now either fits
  /// or turns this red.
  func testEveryToolStripControlIsReachableWithoutScrolling() {
    let app = openEditor()
    let window = app.windows.firstMatch.frame

    // Ink and width belong to the inking tools, so assert against one of those
    // rather than whatever the app happened to launch with.
    app.selectTool("Pen")

    for name in ["Undo", "Redo", "Ink color", "Brush width"] {
      let control = app.descendants(matching: .any).matching(identifier: name).firstMatch
      XCTAssertTrue(control.waitForExistence(timeout: 10), "\(name) is not on screen at all")
      XCTAssertTrue(
        control.isHittable,
        "\(name) exists but cannot be tapped — it is scrolled out of the tool strip")
      XCTAssertTrue(
        window.contains(control.frame),
        """
        \(name) is outside the window at x=\(control.frame.minX), \
        width \(window.width). The tool strip is over its budget for this \
        device — move something into the More Actions menu.
        """)
    }
  }

  /// Stroke opacity has to be reachable from the strip (#271).
  ///
  /// Opacity existed only as the alpha slider inside the system colour sheet,
  /// two taps deep under a control labelled "Ink color", which is not somewhere
  /// anybody looks for it. It could not simply become a third slider either:
  /// the strip is budgeted for an iPad mini in portrait and overflowed there
  /// once already (#246), so colour and opacity share one popover and one slot.
  /// This test is what stops the next person "fixing" that by adding a control.
  func testInkOpacityIsReachableFromTheToolStrip() {
    let app = openEditor()
    app.selectTool("Pen")

    let ink = app.descendants(matching: .any).matching(identifier: "Ink color").firstMatch
    XCTAssertTrue(ink.waitForExistence(timeout: 10), "the ink control is not on the strip")
    ink.tap()

    let opacity = app.descendants(matching: .any).matching(identifier: "Ink opacity").firstMatch
    XCTAssertTrue(
      opacity.waitForExistence(timeout: 10),
      "there is no opacity control — a translucent stroke is unreachable")
  }

  /// The tool picker must not grow with the number of tools.
  ///
  /// It was a segmented control at a fixed 240pt for four tools, which is most
  /// of a phone's strip and could not have taken a fifth: six in 240pt is 40pt
  /// each, under the 44pt minimum touch target. A palette costs one button
  /// regardless, which is what makes adding a tool a normal change.
  func testToolPickerCostsOneButtonRegardlessOfToolCount() {
    let app = openEditor()

    let picker = app.buttons.matching(
      NSPredicate(format: "label BEGINSWITH %@", "Tool, ")
    ).firstMatch
    XCTAssertTrue(picker.waitForExistence(timeout: 10), "the tool palette is not on the strip")
    XCTAssertLessThan(
      picker.frame.width, 160,
      "the tool control is wide enough to be per-tool rather than a palette")

    // Every tool is still reachable through it. One open is enough: the claim is
    // that the palette holds them all at a fixed width, not that switching works
    // four times — and cycling all four cost enough time on a loaded runner to
    // time out the launch of the *next* test.
    picker.tap()
    for name in ["Pen", "Pencil", "Marker", "Eraser"] {
      XCTAssertTrue(
        app.buttons[name].firstMatch.waitForExistence(timeout: 10),
        "\(name) is missing from the tool palette")
    }
    // Leave the palette closed so the next test starts from the editor.
    app.buttons["Eraser"].firstMatch.tap()
    XCTAssertTrue(
      app.buttons["Tool, Eraser"].firstMatch.waitForExistence(timeout: 10),
      "selecting from the palette did not change the tool")
  }
}

// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Noticing, after the fact, that the app was killed (#311).
final class SessionLifecycleTests: XCTestCase {

  private var suite: String!
  private var defaults: UserDefaults!

  override func setUp() {
    super.setUp()
    suite = "SessionLifecycleTests.\(UUID().uuidString)"
    defaults = UserDefaults(suiteName: suite)
  }

  override func tearDown() {
    defaults.removePersistentDomain(forName: suite)
    super.tearDown()
  }

  /// A first ever launch has nothing to report.
  func testAFirstLaunchReportsNothing() {
    let lifecycle = SessionLifecycle(defaults: defaults)
    XCTAssertFalse(lifecycle.previousSessionEndedUnexpectedly)
  }

  /// Backgrounded, then relaunched: an orderly exit, nothing to explain.
  func testAnOrderlyExitIsNotReportedAsACrash() {
    let first = SessionLifecycle(defaults: defaults)
    first.begin(notificationCenter: NotificationCenter())
    first.markClean()

    let second = SessionLifecycle(defaults: defaults)
    XCTAssertFalse(
      second.previousSessionEndedUnexpectedly,
      "an app that backgrounded normally must not accuse itself of crashing")
  }

  /// Killed mid-session — the marker is still armed at the next launch.
  ///
  /// This is what a jetsam kill looks like from the inside: no notification
  /// arrives, nothing gets to run, the flag is simply never cleared.
  func testAKilledSessionIsReportedOnTheNextLaunch() {
    let first = SessionLifecycle(defaults: defaults)
    first.begin(notificationCenter: NotificationCenter())
    // No markClean() — the process died here.

    let second = SessionLifecycle(defaults: defaults)
    XCTAssertTrue(second.previousSessionEndedUnexpectedly)
  }

  /// Reported once, not on every launch afterwards.
  func testTheReportIsAcknowledgedAndNotRepeated() {
    let first = SessionLifecycle(defaults: defaults)
    first.begin(notificationCenter: NotificationCenter())

    let second = SessionLifecycle(defaults: defaults)
    XCTAssertTrue(second.previousSessionEndedUnexpectedly)
    second.acknowledgePreviousSession()
    XCTAssertFalse(second.previousSessionEndedUnexpectedly)

    // And once this session ends cleanly, the next one is quiet too.
    second.begin(notificationCenter: NotificationCenter())
    second.markClean()
    XCTAssertFalse(SessionLifecycle(defaults: defaults).previousSessionEndedUnexpectedly)
  }

  /// Backgrounding is what clears the marker, because that is the notification
  /// a deliberate quit delivers and a kill does not.
  func testBackgroundingClearsTheMarker() {
    let center = NotificationCenter()
    let lifecycle = SessionLifecycle(defaults: defaults)
    lifecycle.begin(notificationCenter: center)

    center.post(name: UIApplication.didEnterBackgroundNotification, object: nil)

    XCTAssertFalse(
      SessionLifecycle(defaults: defaults).previousSessionEndedUnexpectedly,
      "swiping the app away from the switcher is not a crash")
  }

  /// The message must name the likely cause without overclaiming it.
  func testTheMessageOffersACauseWithoutAssertingIt() {
    let message = SessionLifecycle.unexpectedExitMessage
    XCTAssertTrue(message.contains("closed unexpectedly"))
    XCTAssertTrue(message.contains("most likely"), "a debugger detach looks the same")
    XCTAssertTrue(message.lowercased().contains("memory"))
  }
}

/// Saying something when memory is given back, rather than doing it silently.
final class MemoryPressureNoticeTests: XCTestCase {

  func testSheddingMemoryWithHistoryExplainsThatUndoWasReleased() {
    let store = EditorStore()
    let undo = UndoManager()
    store.undoManager = undo
    _ = store.addTextLayer("Something", fontSize: 64, color: .white, at: CGPoint(x: 10, y: 10))
    XCTAssertTrue(undo.canUndo, "precondition: there is history to lose")

    store.shedMemory()

    XCTAssertFalse(undo.canUndo)
    let notice = store.memoryPressureNotice ?? ""
    XCTAssertTrue(notice.contains("undo history"), "the user must learn why Undo went quiet")
    XCTAssertTrue(notice.contains("untouched"), "and that the picture itself is safe")
  }

  func testSheddingMemoryWithNoHistoryStillWarns() {
    let store = EditorStore()
    store.undoManager = UndoManager()
    store.shedMemory()
    let notice = store.memoryPressureNotice ?? ""
    XCTAssertFalse(notice.isEmpty)
    XCTAssertFalse(
      notice.contains("undo history"),
      "do not claim history was released when there was none")
  }
}

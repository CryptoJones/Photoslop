// SPDX-License-Identifier: Apache-2.0
import Foundation
import UIKit

/// Whether the previous run of the app ended on its own terms (#311).
///
/// A jetsam kill is `SIGKILL`. Nothing can be caught, nothing can be drawn, and
/// no crash report is written under the app's name — the only record is a
/// system-wide `JetsamEvent` listing hundreds of processes. From the user's
/// side the app simply stops existing mid-tap, which is how #309 went
/// undiagnosed long enough for its reporter to wonder whether he had imagined
/// it.
///
/// The app cannot speak at the moment it is killed. It can notice afterwards.
/// A marker is set while running and cleared when the app backgrounds or
/// terminates normally; finding it still set at launch means the previous
/// session did not get to do either.
///
/// Deliberately conservative about what it claims. It reports that the last
/// session ended abnormally, which is a fact, and leaves memory as the *likely*
/// cause rather than asserting it — a debugger detach or a power-off looks the
/// same from here.
final class SessionLifecycle {
  static let shared = SessionLifecycle(defaults: .standard)

  private enum Key {
    static let running = "session.running"
  }

  private let defaults: UserDefaults
  private var observers: [NSObjectProtocol] = []

  /// True when the previous session was killed rather than closed.
  ///
  /// Read once at startup, before the marker is re-armed, so it describes the
  /// run before this one and does not change underfoot.
  private(set) var previousSessionEndedUnexpectedly = false

  init(defaults: UserDefaults) {
    self.defaults = defaults
    previousSessionEndedUnexpectedly = defaults.bool(forKey: Key.running)
  }

  /// Arm the marker for this session and clear it on an orderly exit.
  ///
  /// `didEnterBackground` is the load-bearing one: an app the user swipes away
  /// from the switcher is backgrounded first, so a deliberate quit is not
  /// mistaken for a kill. `willTerminate` is not delivered for a jetsam kill,
  /// which is precisely why it cannot be relied on alone.
  func begin(notificationCenter: NotificationCenter = .default) {
    defaults.set(true, forKey: Key.running)
    for name in [
      UIApplication.didEnterBackgroundNotification,
      UIApplication.willTerminateNotification,
    ] {
      observers.append(
        notificationCenter.addObserver(forName: name, object: nil, queue: .main) {
          [weak self] _ in
          self?.markClean()
        })
    }
  }

  /// Record that this session reached an orderly stopping point.
  func markClean() {
    defaults.set(false, forKey: Key.running)
  }

  /// Acknowledge the report so it is shown once, not on every launch.
  func acknowledgePreviousSession() {
    previousSessionEndedUnexpectedly = false
  }

  /// What to tell the user about a session that vanished.
  static let unexpectedExitMessage =
    "Photoslop closed unexpectedly last time. The most likely reason is that "
    + "the device ran low on memory — importing fewer photos at once, or "
    + "working on a smaller canvas, will help."

  deinit {
    for observer in observers { NotificationCenter.default.removeObserver(observer) }
  }
}

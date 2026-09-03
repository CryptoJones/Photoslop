// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Whether touch draws before anyone has touched the Finger toggle (#313).
///
/// The toggle used to start off everywhere. On an iPad that is right: a Pencil
/// can exist, and a resting palm should pan rather than paint. On an iPhone it
/// meant a fresh install could not draw at all — no Pencil, every stroke a
/// pan — and the only fix was a switch below the fold of a menu that did not
/// say it scrolled. The default is a function of the idiom so this can be
/// pinned without a device of each kind.
final class FingerDrawingDefaultTests: XCTestCase {
  func testAPhoneDrawsWithTheFingerOutOfTheBox() {
    XCTAssertTrue(
      EditorView.defaultDrawsWithFinger(idiom: .phone),
      "an iPhone has no Apple Pencil; with finger drawing off it cannot draw at all")
  }

  func testAnIPadStillStartsWithThePencil() {
    XCTAssertFalse(
      EditorView.defaultDrawsWithFinger(idiom: .pad),
      "an iPad can have a Pencil, and a resting palm should pan rather than paint")
  }

  /// Nothing else is a phone. A Mac (Catalyst) or a headset is a pointer or a
  /// gaze, not a fingertip on glass, and gets the conservative default.
  func testOnlyThePhoneIdiomTurnsFingerDrawingOn() {
    for idiom in [UIUserInterfaceIdiom.unspecified, .mac, .tv, .carPlay, .vision] {
      XCTAssertFalse(
        EditorView.defaultDrawsWithFinger(idiom: idiom),
        "\(idiom.rawValue) is not a phone and should keep the Pencil-first default")
    }
  }
}

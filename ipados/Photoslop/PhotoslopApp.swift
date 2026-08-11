// SPDX-License-Identifier: Apache-2.0
import SwiftUI

@main
struct PhotoslopApp: App {
  init() {
    PhotoslopApp.emptyDocumentStoreIfAskedTo()
  }

  /// `-PhotoslopFreshDocumentStore` empties the on-device document directory at
  /// launch. Only the UI tests pass it.
  ///
  /// `DocumentGroup` keeps every document a test creates, so by the end of a run
  /// the launch scene and browser are backed by a folder holding "Untitled 1"
  /// through "Untitled 15". Each test then starts from a different state than
  /// the last, the browser takes longer to come up the further into the run it
  /// is, and a relaunch can restore the previous document instead of showing
  /// the launch scene — which is the "came up on a screen nobody asked for"
  /// half of #238. Starting from empty makes every test's first screen the same
  /// screen.
  private static func emptyDocumentStoreIfAskedTo() {
    guard ProcessInfo.processInfo.arguments.contains("-PhotoslopFreshDocumentStore") else { return }
    let manager = FileManager.default
    guard
      let documents = manager.urls(for: .documentDirectory, in: .userDomainMask).first,
      let contents = try? manager.contentsOfDirectory(
        at: documents, includingPropertiesForKeys: nil)
    else { return }
    for url in contents {
      try? manager.removeItem(at: url)
    }
  }

  var body: some Scene {
    DocumentGroup(newDocument: { EditorStore() }) { file in
      EditorView(store: file.document)
    }

    // Without a launch scene, DocumentGroup opens straight into the file
    // browser, so the app greets you with a directory listing before you have
    // said whether you want to create or open anything. Declaring one puts a
    // landing page first, and the browser appears only once Open is chosen.
    //
    // iOS 18 and newer. SceneBuilder has no buildLimitedAvailability, but an
    // availability check wrapping a whole scene does compile, so iPadOS 17
    // keeps the previous behaviour instead of the app dropping those devices.
    if #available(iOS 18.0, *) {
      DocumentGroupLaunchScene("Photoslop") {
        // The standard pair — create a document, or open an existing one —
        // wired to DocumentGroup's own creation and browsing rather than
        // reimplemented here.
        DefaultDocumentGroupLaunchActions()
      }
    }
  }
}

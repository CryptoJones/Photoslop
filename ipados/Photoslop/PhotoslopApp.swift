// SPDX-License-Identifier: Apache-2.0
import SwiftUI

@main
struct PhotoslopApp: App {
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

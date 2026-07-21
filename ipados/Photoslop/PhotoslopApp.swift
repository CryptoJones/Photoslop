// SPDX-License-Identifier: Apache-2.0
import SwiftUI

@main
struct PhotoslopApp: App {
  var body: some Scene {
    DocumentGroup(newDocument: { EditorStore() }) { file in
      EditorView(store: file.document)
    }
  }
}

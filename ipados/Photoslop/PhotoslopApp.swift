// SPDX-License-Identifier: Apache-2.0
import SwiftUI

@main
struct PhotoslopApp: App {
  var body: some Scene {
    WindowGroup {
      EditorView()
    }
    .commands {
      CommandGroup(replacing: .newItem) {}
    }
  }
}

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
      } background: {
        // Deliberately here rather than on the launch *screen*. Apple's
        // guidance is that a launch screen mimics the first real screen and
        // carries no text, so a version string there is the sort of thing App
        // Review flags. This scene is the app's own first screen, the one a
        // reviewer meets before any document exists, and it is built to be
        // branded.
        LinearGradient(
          colors: [
            Color(red: 0.09, green: 0.11, blue: 0.16),
            Color(red: 0.02, green: 0.03, blue: 0.05),
          ],
          startPoint: .top,
          endPoint: .bottom
        )
        .ignoresSafeArea()
      } overlayAccessoryView: { _ in
        // Overlay, not background: the background accessory sits *behind* the
        // system's title and actions, where the document browser's own sheet
        // covers it — the first attempt at this compiled, ran, and showed
        // nothing. The overlay draws above that, which is where identity
        // belongs anyway.
        // Anchored to the top. The system's document browser owns the bottom
        // of this scene and draws above the overlay, so anything placed there
        // is rendered and then covered — the second attempt at this put the
        // mascot behind a frosted sheet.
        VStack {
          LaunchIdentity()
          Spacer(minLength: 0)
        }
      }
    }
  }
}

/// Who this is, what version, under what licence, and where the source lives.
///
/// The launch scene otherwise says only "Photoslop" over two buttons, which is
/// a thin first impression and, to App Review, an app that appears to do nothing
/// until you guess a document has to be made. Naming the licence and linking the
/// repository also puts the Apache-2.0 terms one tap from the first screen
/// rather than buried in About.
private struct LaunchIdentity: View {
  private var version: String {
    let info = Bundle.main.infoDictionary ?? [:]
    let short = info["CFBundleShortVersionString"] as? String ?? "unknown"
    let build = info["CFBundleVersion"] as? String ?? "0"
    return "\(short) (\(build))"
  }

  var body: some View {
    // A compact bar in the strip above the system's card. The system owns the
    // middle of this scene — its title, its Create Document button, and the
    // document browser below — so identity goes in the margin it leaves rather
    // than fighting it. A stacked block here straddled the card's edge and put
    // the version above the app's own name, which read like a mistake.
    HStack(spacing: 10) {
      // Drawn in code by `photoslop/appicon.py` and exported into the asset
      // catalogue by `scripts/render-ios-mascot.py`; the CI quality job fails
      // if the committed asset drifts from the code that draws it.
      Image("Mascot")
        .resizable()
        .scaledToFit()
        .frame(width: 34, height: 34)
        .accessibilityLabel("Le Basilisk, the Photoslop mascot")

      VStack(alignment: .leading, spacing: 1) {
        Text("Photoslop \(version) · Apache-2.0")
        Link("github.com/CryptoJones/Photoslop", destination: Photoslop.repositoryURL)
      }
      .font(.caption2)
      .foregroundStyle(.white.opacity(0.75))
    }
    .padding(.horizontal, 16)
    .padding(.top, 6)
    .accessibilityElement(children: .contain)
    .accessibilityIdentifier("Launch identity")
  }
}

enum Photoslop {
  static let repositoryURL = URL(string: "https://github.com/CryptoJones/Photoslop")!
}

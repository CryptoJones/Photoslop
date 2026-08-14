// SPDX-License-Identifier: Apache-2.0
import SwiftUI
import UIKit

/// The splash Photoslop shows on launch: mascot, name, version, licence, source.
///
/// A real full-screen splash, not decoration on the document launch scene. The
/// first attempt put an identity bar in the margin around
/// `DocumentGroupLaunchScene`, because the system owns that scene's middle — its
/// title, its Create Document button, and the document browser below. The result
/// was a caption above someone else's screen, which is not a splash screen.
struct SplashScreen: View {
  var body: some View {
    ZStack {
      LinearGradient(
        colors: [
          Color(red: 0.10, green: 0.12, blue: 0.18),
          Color(red: 0.02, green: 0.03, blue: 0.06),
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
      )
      .ignoresSafeArea()

      VStack(spacing: 18) {
        // Drawn in code by `photoslop/appicon.py` and exported into the asset
        // catalogue by `scripts/render-ios-mascot.py`; the CI quality job fails
        // if the committed asset drifts from the code that draws it.
        Image("Mascot")
          .resizable()
          .scaledToFit()
          .frame(width: 176, height: 176)
          .shadow(color: .black.opacity(0.4), radius: 18, y: 8)
          .accessibilityLabel("Le Basilisk, the Photoslop mascot")

        Text("Photoslop")
          .font(.system(size: 52, weight: .bold, design: .rounded))
          .foregroundStyle(.white)

        Text("A memory-frugal, multiplatform, layered raster image editor.")
          .font(.callout)
          .multilineTextAlignment(.center)
          .foregroundStyle(.white.opacity(0.7))
          .frame(maxWidth: 420)
          .padding(.horizontal, 32)

        VStack(spacing: 6) {
          Text(Self.version)
          Text("Apache-2.0 licensed")
          Text("github.com/CryptoJones/Photoslop")
        }
        .font(.footnote)
        .foregroundStyle(.white.opacity(0.55))
        .padding(.top, 6)
      }
    }
    .accessibilityElement(children: .contain)
    .accessibilityIdentifier("Splash screen")
  }

  static var version: String {
    let info = Bundle.main.infoDictionary ?? [:]
    let short = info["CFBundleShortVersionString"] as? String ?? "unknown"
    let build = info["CFBundleVersion"] as? String ?? "0"
    return "Version \(short) (\(build))"
  }
}

/// Puts `SplashScreen` in a window of its own, above the app, and takes it away.
///
/// A window rather than an overlay because the document launch scene is the
/// app's root and the system's document browser draws above anything placed
/// inside it. A window sits above both, so the splash is the whole screen for as
/// long as it is up.
///
/// It dismisses itself. A launch experience should get out of the way, and a
/// splash that has to be tapped past is worse than none — so it fades after a
/// beat, and a tap skips the rest of that beat.
@MainActor
enum SplashWindow {
  private static var window: UIWindow?
  private static var shown = false

  /// Long enough to read the version, short enough not to be in the way.
  static let hold: TimeInterval = 1.6
  private static let fade: TimeInterval = 0.35

  static func showOnce() {
    guard !shown, !isRunningUITests else { return }
    shown = true

    let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
    guard let scene = scenes.first(where: { $0.activationState == .foregroundActive })
      ?? scenes.first
    else { return }

    let host = UIHostingController(rootView: SplashScreen())
    let splash = UIWindow(windowScene: scene)
    splash.rootViewController = host
    splash.windowLevel = .alert + 1
    splash.isHidden = false
    splash.makeKeyAndVisible()
    splash.addGestureRecognizer(
      UITapGestureRecognizer(target: SplashDismisser.shared, action: #selector(SplashDismisser.skip))
    )
    window = splash

    DispatchQueue.main.asyncAfter(deadline: .now() + hold) { dismiss() }
  }

  static func dismiss() {
    guard let splash = window else { return }
    window = nil
    UIView.animate(withDuration: fade) {
      splash.alpha = 0
    } completion: { _ in
      splash.isHidden = true
    }
  }

  /// The UI tests drive the launch scene directly and would otherwise spend part
  /// of their budget waiting this out on every launch.
  private static var isRunningUITests: Bool {
    let arguments = ProcessInfo.processInfo.arguments
    return arguments.contains("-PhotoslopSkipSplash")
      || arguments.contains("-PhotoslopFreshDocumentStore")
  }
}

@MainActor
private final class SplashDismisser: NSObject {
  static let shared = SplashDismisser()
  @objc func skip() { SplashWindow.dismiss() }
}

// SPDX-License-Identifier: Apache-2.0
import SwiftUI
import UIKit

/// The editor's look: a dark studio around the artwork.
///
/// Drawing apps are dark for a reason that is not fashion. Chrome in a neutral
/// dark grey has no colour of its own to cast on the picture, and it recedes
/// behind it; the system's light grey the editor used to sit on tinted every
/// judgement of a colour made against it, and read as a sample app besides.
/// The one accent is the basilisk's green, desaturated enough to sit beside
/// any artwork, and it marks *state* — the selected tool, the active layer,
/// the one prominent action in a mode — rather than every control.
enum Studio {
  /// The surround behind the canvas. Dark but not black, so a black-filled
  /// layer still has an edge.
  static let backdrop = UIColor(white: 0.11, alpha: 1)
  /// Panels, docks and bars.
  static let chrome = Color(white: 0.15)
  /// A surface inside the chrome: a pressed button, a raised strip. One step
  /// lighter than the chrome so it reads as sitting *on* it.
  static let raised = Color(white: 0.21)
  /// The line between chrome and canvas, and around a thumbnail.
  static let hairline = Color.white.opacity(0.10)
  /// Selected tool, active layer, prominent action.
  static let accent = Color(red: 0.49, green: 0.84, blue: 0.42)
  static let panelRadius: CGFloat = 14
  /// The square a tool or icon button draws itself in; its hit area is the
  /// 44pt around it.
  static let iconSide: CGFloat = 40
  /// The smallest thing a finger is meant to hit. Apple's guidance, and the
  /// floor the UI tests measure every control against.
  static let touchSide: CGFloat = 44
  /// The height of one strip of the dock.
  static let stripHeight: CGFloat = 44
  /// The type used for a control's own name — the tool in hand, a layer's kind.
  static func label(_ size: CGFloat, _ weight: Font.Weight = .semibold) -> Font {
    .system(size: size, weight: weight)
  }
}

/// A panel floating over the backdrop: material, rounded, a hairline edge and
/// a soft shadow, so it reads as a thing resting on the surround rather than a
/// strip cut out of the window.
struct FloatingPanel: ViewModifier {
  func body(content: Content) -> some View {
    let shape = RoundedRectangle(cornerRadius: Studio.panelRadius, style: .continuous)
    return
      content
      .background(.regularMaterial, in: shape)
      .overlay(shape.strokeBorder(Studio.hairline))
      .shadow(color: .black.opacity(0.35), radius: 12, y: 4)
  }
}

extension View {
  func floatingPanel() -> some View { modifier(FloatingPanel()) }
}

/// An icon in a square, highlighted while pressed and dimmed while disabled.
/// Undo, redo, the selection actions and the layer panel's actions all wear
/// this so the chrome is one vocabulary of 40pt squares.
struct IconButtonStyle: ButtonStyle {
  @Environment(\.isEnabled) private var isEnabled

  func makeBody(configuration: Configuration) -> some View {
    configuration.label
      .labelStyle(.iconOnly)
      .font(.system(size: 18, weight: .medium))
      .frame(width: Studio.iconSide, height: Studio.iconSide)
      .foregroundStyle(
        configuration.role == .destructive ? Color.red : Color.primary
      )
      .opacity(isEnabled ? 1 : 0.3)
      .background(
        configuration.isPressed ? Color.white.opacity(0.14) : Color.clear,
        in: RoundedRectangle(cornerRadius: 10, style: .continuous)
      )
      .contentShape(Rectangle())
  }
}

extension ButtonStyle where Self == IconButtonStyle {
  static var icon: IconButtonStyle { IconButtonStyle() }
}

/// A vertical rule between two groups of controls in a row.
///
/// Drawn as a view rather than a `Divider` so it can stand *between* two
/// groups — a rule with the groups on either side of it — instead of running
/// the full width of a stack.
///
/// Its height is fixed rather than left to fill the row: a shape that is
/// greedy in both directions takes the row's whole proposed height, and the
/// row then takes the height it was offered — which is how a one-point rule
/// once made a palette 300pt tall and pushed the canvas off the screen.
struct VerticalRule: View {
  /// How tall the rule is. Short of the 44pt row it stands in, so it reads
  /// as a separator rather than a divider down the middle of a control.
  var height: CGFloat = 28

  var body: some View {
    Rectangle()
      .fill(Studio.hairline)
      .frame(width: 1, height: height)
  }
}

/// A horizontal rule between two groups of controls in a column.
struct HorizontalRule: View {
  /// How wide the rule is. Short rules read as separators; full-width ones
  /// read as the edge of a section.
  var width: CGFloat = 24

  var body: some View {
    Rectangle()
      .fill(Studio.hairline)
      .frame(width: width, height: 1)
      .padding(.vertical, 6)
  }
}

/// A short label above a group of controls, in the chrome's own voice.
///
/// Used where a control needs a name the icon cannot carry — "Size", "Tolerance"
/// — and deliberately quiet: the accent is for state, not for captions.
struct ChromeCaption: View {
  let text: String

  var body: some View {
    Text(text)
      .font(.system(size: 11, weight: .medium))
      .foregroundStyle(.secondary)
      .lineLimit(1)
      .fixedSize()
      .accessibilityHidden(true)
  }
}

// SPDX-License-Identifier: Apache-2.0
import SwiftUI

/// One tool in the palette: an icon in a square, filled with the accent while
/// it is the tool in hand.
///
/// Every tool is on screen at once, which is what a palette is. The tools used
/// to sit behind one menu button showing only the current one, so the set on
/// offer was invisible until the menu opened and every switch cost two taps —
/// a layout chosen to fit a phone's strip, and the single thing that most made
/// the editor look like a demo rather than something to draw in.
///
/// The accessibility contract the UI tests drive: the identifier is the tool's
/// name, so `buttons["Eraser"]` is this button; the label is "Tool, Eraser"
/// while it is selected and the plain name otherwise, so the one button whose
/// label begins "Tool, " is the tool in hand.
struct ToolButton: View {
  let tool: BrushTool
  let isSelected: Bool
  let action: () -> Void

  var body: some View {
    Button(action: action) {
      Image(systemName: tool.symbolName)
        .font(.system(size: 18, weight: .medium))
        .frame(width: Studio.iconSide, height: Studio.iconSide)
        .foregroundStyle(isSelected ? Color.black : Color.primary)
        .background(
          isSelected ? Studio.accent : Color.clear,
          in: RoundedRectangle(cornerRadius: 10, style: .continuous)
        )
        .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .frame(minWidth: 44, minHeight: 44)
    .accessibilityIdentifier(tool.displayName)
    .accessibilityLabel(isSelected ? "Tool, \(tool.displayName)" : tool.displayName)
    .accessibilityAddTraits(isSelected ? .isSelected : [])
  }
}

/// The tools, one button each, in the order they are listed.
struct ToolButtons: View {
  @Binding var tool: BrushTool
  /// Stretch each button to share the width — the phone dock's layout, where
  /// nine tools divide the row rather than scrolling off it.
  var fills = false

  var body: some View {
    ForEach(BrushTool.allCases) { candidate in
      ToolButton(tool: candidate, isSelected: candidate == tool) { tool = candidate }
        .frame(maxWidth: fills ? .infinity : nil)
    }
  }
}

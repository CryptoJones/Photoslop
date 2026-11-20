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
///
/// A button is a physical dock *slot*, and a slot can host sub-tools: Lasso hosts
/// Magnetic Lasso, Eraser hosts Spot Healing and the Healing Brush (#456). While a
/// hosted sub-tool is in hand its host slot stays lit and keeps the slot's own
/// label ("Tool, Eraser"), so `selectTool` can still find the slot by name and the
/// nine-button budget never grows. The sub-tool actually in hand is named by the
/// canvas accessibility value and the tool-identity strip, not by the slot label —
/// a deliberate trade-off, the same one Magnetic Lasso already makes.
struct ToolButton: View {
  let tool: BrushTool
  let isSelected: Bool
  /// Put the tool's name under its icon, for the places with room for one.
  var showsCaption = false
  /// Share the width of the slot the palette gives it, rather than taking a
  /// fixed one. Nine fixed 44pt buttons are 396pt, which overflows a 375pt
  /// phone and pushes the last tool off the edge; sharing the width keeps all
  /// nine on screen at any phone size, and the smallest of them still clears
  /// the 40pt floor a finger needs.
  var fillsWidth = false
  let action: () -> Void

  var body: some View {
    Button(action: action) {
      VStack(spacing: 2) {
        Image(systemName: tool.symbolName)
          .font(.system(size: 18, weight: .medium))
          .foregroundStyle(isSelected ? Color.black : Color.primary)
          .frame(width: Studio.iconSide, height: Studio.iconSide)
          .frame(maxWidth: fillsWidth ? .infinity : nil)
          .background(
            isSelected ? Studio.accent : Color.clear,
            in: RoundedRectangle(cornerRadius: 10, style: .continuous)
          )
        if showsCaption {
          Text(tool.caption)
            .font(.system(size: 9, weight: .medium))
            .foregroundStyle(isSelected ? Studio.accent : Color.secondary)
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .accessibilityHidden(true)
        }
      }
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .frame(
      minWidth: fillsWidth ? nil : Studio.touchSide,
      minHeight: Studio.touchSide
    )
    .accessibilityIdentifier(tool.displayName)
    .accessibilityLabel(isSelected ? "Tool, \(tool.displayName)" : tool.displayName)
    .accessibilityAddTraits(isSelected ? .isSelected : [])
    // What the finger should do with this tool. Three of the nine answer a tap
    // and the rest answer a drag, and an icon does not say which.
    .accessibilityHint(tool.usageHint)
  }
}

/// The tools, one button each, in the order they are listed.
struct ToolButtons: View {
  @Binding var tool: BrushTool
  /// Stretch each button to share the width — the phone dock's layout, where
  /// nine tools divide the row rather than scrolling off it.
  var fills = false
  /// Name each tool under its icon. The rail on an iPad has the height for it;
  /// the phone's dock has the width but not the height.
  var showsCaption = false
  /// Hairlines between the families of tool — draw, fill, select, pick.
  var showsGroups = false

  /// The tools with a rule in front of each new family.
  private var entries: [(tool: BrushTool, startsFamily: Bool)] {
    var result: [(tool: BrushTool, startsFamily: Bool)] = []
    var previous: BrushTool.Family?
    for candidate in BrushTool.primaryPaletteTools {
      result.append((candidate, previous != nil && candidate.family != previous))
      previous = candidate.family
    }
    return result
  }

  var body: some View {
    ForEach(entries, id: \.tool.id) { entry in
      if showsGroups, entry.startsFamily {
        VerticalRule()
      }
      ToolButton(
        tool: entry.tool,
        isSelected: entry.tool == tool
          || (entry.tool == .lasso && tool == .magneticLasso)
          || (entry.tool == .eraser && tool.isHealTool),
        showsCaption: showsCaption,
        fillsWidth: fills
      ) {
        if entry.tool == .lasso && tool == .lasso {
          tool = .magneticLasso
        } else if entry.tool == .lasso && tool == .magneticLasso {
          tool = .lasso
        } else if entry.tool == .eraser && tool.isHealTool {
          // Tapping the host while a retouch sub-tool is in hand returns to the
          // eraser, the way tapping Lasso returns from Magnetic Lasso. The
          // sub-tools themselves are picked from the long-press menu below or
          // the Retouch picker in the tool options (#456).
          tool = .eraser
        } else {
          tool = entry.tool
        }
      }
      .frame(maxWidth: fills ? .infinity : nil)
      .contextMenu {
        if entry.tool == .lasso {
          Button {
            tool = .lasso
          } label: {
            Label("Freehand Lasso", systemImage: "lasso")
          }
          Button {
            tool = .magneticLasso
          } label: {
            Label("Magnetic Lasso", systemImage: "lasso")
          }
        }
        if entry.tool == .eraser {
          // The retouch tools share the eraser's slot to keep the iPhone dock
          // at nine buttons (#456). Long-press to pick one, exactly as Magnetic
          // Lasso lives under Lasso.
          Button {
            tool = .eraser
          } label: {
            Label("Eraser", systemImage: "eraser")
          }
          Button {
            tool = .spotHeal
          } label: {
            Label("Spot Healing", systemImage: "bandage")
          }
          Button {
            tool = .healBrush
          } label: {
            Label("Healing Brush", systemImage: "cross.case")
          }
        }
      }
    }
  }
}

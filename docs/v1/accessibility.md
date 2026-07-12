# Accessibility

Photoslop targets WCAG 2.2 AA interaction principles adapted to native Qt on
macOS, Windows, and Linux. Standard controls expose native Qt roles; custom
canvas and ruler widgets have explicit names and descriptions. Status messages
are emitted as polite accessibility announcements.

## Keyboard workflow

- `Ctrl+Shift+P` searches commands and explains unavailable prerequisites.
- Tool flyouts and Properties fields are reachable by Tab/Shift+Tab.
- Arrow keys nudge with Move; Shift+Arrow nudges by ten pixels.
- `Alt+Shift+H` and `Alt+Shift+V` create centered horizontal/vertical guides;
  View → Clear Guides removes them without dragging a ruler.
- Enter commits compatible tools and Escape cancels the active operation.

Preferences → Accessibility offers high contrast, reduced motion, and 100–200%
control scaling. High contrast adds a visible yellow focus indicator and
non-color checked state; reduced motion slows marching ants.

## Versioned screen-reader smoke procedure (v1)

Run this script with VoiceOver (macOS), NVDA (Windows), and Orca/AT-SPI (Linux):

1. Launch without a document. Confirm menus, grouped toolbox, docks, options,
   and status bar are announced.
2. Open Command Palette, create a 640×480 document, and confirm canvas focus.
3. Select Brush from its flyout, enter Size 32 and Opacity 50 by keyboard, then
   reset the tool options.
4. Add a layer; rename it in Properties; toggle visibility; set opacity to 75%;
   undo/redo; confirm name, value, and state announcements.
5. Add both centered guides with shortcuts, clear them from Command Palette,
   and verify the status announcements.
6. Enable 200% controls, high contrast, and reduced motion; restart and verify
   persistence, focus visibility, no clipped actions, and no color-only state.
7. Save, close, and reopen. Confirm named dialog fields, predictable focus, and
   that Cancel returns without changing pixels.

Record OS, Qt/Photoslop version, screen reader version, pass/fail for each step,
and announcement defects. Automated accessible-tree coverage runs in CI; the
manual script remains required because reading order cannot be proven from the
object tree alone.

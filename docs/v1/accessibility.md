# Accessibility

Photoslop uses WCAG 2.2 AA interaction principles as a design target for its
native Qt and iPad interfaces; this is not a conformance certification.
Standard controls expose native roles, while the custom canvas and rulers
publish explicit, stateful names and descriptions. Status messages are emitted
as polite accessibility announcements.

## Keyboard workflow

- `Ctrl+Shift+P` searches commands and explains unavailable prerequisites.
- `Ctrl+Alt+Shift+D` focuses and describes the canvas, including size, DPI,
  active layer, selection, pointer coordinates, zoom, tool, and guide count.
- Tool flyouts and Properties fields are reachable by Tab/Shift+Tab.
- Arrow keys nudge with Move and Free Transform; Shift+Arrow nudges by ten
  pixels.
- `Alt+Shift+H` and `Alt+Shift+V` create centered horizontal/vertical guides;
  View → Clear Guides removes them without dragging a ruler.
- Enter commits compatible tools. Escape first cancels an active gesture and
  restores its pre-gesture pixels/selection; a subsequent Escape clears the
  selection.
- The layer stack announces layer type, visibility, opacity, and position.
  Arrow keys choose a layer, Space toggles visibility, and F2 renames it.

Preferences → Accessibility offers high contrast, reduced motion, and 100–200%
control and font scaling. High contrast adds a visible yellow focus indicator,
larger handles, and a non-color checked state; reduced motion stops marching
ants.

## Versioned assistive-technology smoke procedure (v3)

Run the desktop steps with NVDA and JAWS on Windows, VoiceOver on macOS, and
Orca/AT-SPI on Linux. Run the corresponding document, layer, draw, undo,
save/reopen, and export steps with VoiceOver and Switch Control on iPadOS.

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
8. Create two vector shapes, choose Vector Selection with `A`, add the second
   object with Shift-click, switch to Direct Selection with `Shift+A`, and
   confirm tool names, selection changes, and undo/redo are announced.
9. Open an SVG containing supported shapes plus an unsupported polygon. Confirm
   the editable layers and fallback layer have distinct names and that keyboard
   navigation never enters an unlabelled control.
10. Begin a selection drag and press Escape. Confirm the prior selection is
    restored; press Escape again and confirm it is cleared. Repeat during Brush,
    Liquify, Crop, and Free Transform and confirm no partial edit remains.
11. Focus the canvas, run Describe Canvas, move a transform with Arrow and
    Shift+Arrow, and confirm state/coordinate announcements stay current.

Record OS, Qt/Photoslop version, assistive-technology version, input method,
pass/fail for each step, and announcement defects. The repository does not
claim these manual rows have passed until that release record exists.
Automated accessible-tree coverage runs in CI; the manual script remains
required because reading order and spoken output cannot be proven from the
object tree alone.

| Platform | Required manual combinations | Release evidence |
|---|---|---|
| Windows | NVDA + keyboard; JAWS + keyboard | Versioned smoke record |
| macOS | VoiceOver + keyboard | Versioned smoke record |
| Linux | Orca/AT-SPI + keyboard | Versioned smoke record |
| iPadOS | VoiceOver + touch/keyboard; Switch Control | Versioned smoke record |

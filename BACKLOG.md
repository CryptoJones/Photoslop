# Backlog

A second view of the GitHub [Issues](https://github.com/CryptoJones/Photoslop/issues)
tab. Every backlog item has a matching issue and vice versa; the two stay in
sync — check an item here when its issue closes.

## Open

- [ ] **P1:** Implement cross-platform accessibility semantics and keyboard
  workflows for standard and custom Qt widgets
  ([#151](https://github.com/CryptoJones/Photoslop/issues/151))
- [ ] **P1:** Add a cancellable, memory-bounded background task service for
  filters, I/O, RAW, exports, subprocesses, and model requests
  ([#152](https://github.com/CryptoJones/Photoslop/issues/152))
- [ ] **P1:** Reduce canvas repaint and preview overhead with dirty overlays,
  generation-aware thumbnails, proxy previews, and bounded caches
  ([#153](https://github.com/CryptoJones/Photoslop/issues/153))
- [ ] **P1:** Split UI responsibilities into action, tool, workspace, and
  service registries while preserving GUI/CLI/MCP engine parity
  ([#154](https://github.com/CryptoJones/Photoslop/issues/154))
- [ ] **P2:** Introduce a versioned native vector object model with Bézier
  geometry, appearance, transforms, hierarchy, migration, and crisp rendering
  ([#155](https://github.com/CryptoJones/Photoslop/issues/155))
- [ ] **P2:** Build vector selection, node editing, appearance, Boolean,
  alignment, snapping, text, and construction workflows
  ([#156](https://github.com/CryptoJones/Photoslop/issues/156))
- [ ] **P2:** Add SVG import/export and editable artboard interchange while
  retaining OpenRaster raster fallbacks
  ([#157](https://github.com/CryptoJones/Photoslop/issues/157))
- [ ] **P1/P2:** Add accessibility, performance, cursor, UI, and vector workflow
  verification plus honest feature-parity documentation
  ([#158](https://github.com/CryptoJones/Photoslop/issues/158))

## Done

- [x] Streamline workspace actions and contextual tool options through an
  action registry, command palette, Properties panel, and responsive controls
  ([#150](https://github.com/CryptoJones/Photoslop/issues/150)) — shipped v1.18.0
- [x] Replace toolbox iconography and group tools into keyboard-accessible
  flyouts with theme/HiDPI states and licensed SVG assets
  ([#149](https://github.com/CryptoJones/Photoslop/issues/149)) — shipped v1.17.0
- [x] Add contextual tool cursors and pointer states — brush-radius, tool glyph,
  modifier, handle, target-validity, and temporary-pan cursors
  ([#148](https://github.com/CryptoJones/Photoslop/issues/148)) — shipped v1.16.0
- [x] Fix text-size keyboard entry up to 999 pt — retain numeric-field focus
  during multi-digit edits, validate 6–999, and add regression coverage
  ([#147](https://github.com/CryptoJones/Photoslop/issues/147)) — shipped v1.15.1
- [x] Open dialog: extend the "Open images" window to fill the internal workable
  image area (central canvas region) instead of floating as a smaller inset box
  ([#144](https://github.com/CryptoJones/Photoslop/issues/144)) — shipped v1.15.0
- [x] macOS installer script (`scripts/install-macos.sh`) that builds a clickable
  `Photoslop.app` launcher and installs it into `/Applications`
  ([#142](https://github.com/CryptoJones/Photoslop/issues/142))
- [x] Create MCP server for Photoslop — `photoslop-mcp` exposes the engine as MCP
  tools (`list_operations`, `edit_image`, `document_info`) mirroring `photoslop-cli`
  ([#134](https://github.com/CryptoJones/Photoslop/issues/134)) — shipped v1.13.0
- [x] Open dialog: always show all columns (Name/Size/Kind/Date Modified) without
  truncation ([#135](https://github.com/CryptoJones/Photoslop/issues/135)) — shipped v1.12.1
- [x] Move Zoom In / Zoom Out to the top options bar of the main window,
  alongside the existing top options
  ([#136](https://github.com/CryptoJones/Photoslop/issues/136)) — shipped v1.12.1
- [x] Credits window: rename the "Programming" section heading to "Contributors"
  ([#137](https://github.com/CryptoJones/Photoslop/issues/137)) — shipped v1.12.1
- [x] Retro Console (8-Bit) filter — pixelate + palette crush + dither
  ([#130](https://github.com/CryptoJones/Photoslop/issues/130)) — shipped v1.12.0
- [x] Consolidated Preferences dialog (Model Backend + Color), native macOS ⌘,
  ([#131](https://github.com/CryptoJones/Photoslop/issues/131)) — shipped v1.12.0

---

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

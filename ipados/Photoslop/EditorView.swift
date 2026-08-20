// SPDX-License-Identifier: Apache-2.0
import PencilKit
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

struct EditorView: View {
  @ObservedObject var store: EditorStore
  @Environment(\.undoManager) private var undoManager
  @State private var selectedPhoto: PhotosPickerItem?
  @State private var showPhotosPicker = false
  @State private var selectedLayerPhotos: [PhotosPickerItem] = []
  @State private var showLayerPhotosPicker = false
  @State private var pendingLayerPhotoPick = false
  @State private var isAddingLayerPhotos = false
  @State private var showFileImporter = false
  @State private var showLayerFileImporter = false
  @State private var showExporter = false
  @State private var showImportOptions = false
  @State private var showLayerImportOptions = false
  @State private var importSource = ImportSource.photos
  @State private var layerImportSource = ImportSource.photos
  @State private var exportDestination = ExportDestination.files
  @State private var savedToPhotos = false
  @State private var showExportOptions = false
  @State private var showNewDocumentOptions = false
  @State private var canvasSheetMode = CanvasSheetMode.newDocument
  @State private var showAbout = false
  @State private var showTextOptions = false
  @State private var textBody = ""
  @State private var textSize = 48.0
  @State private var textColor = Color.black
  @State private var isMovingText = false
  @State private var isCropping = false
  @State private var cropRect = CGRect.zero
  @State private var cropAspect = CropAspect.free
  /// The zoom scale, so the overlay's handles stay finger-sized however far in
  /// the canvas is zoomed. The overlay itself is in document pixels and needs
  /// nothing else from the canvas.
  @State private var canvasZoom: CGFloat = 1
  /// The layer currently being placed and resized, if any.
  @State private var placement: Placement?
  /// The glyphs of the text layer being fitted, cropped from its rendering
  /// when the box opened, so the live preview can scale them into the box.
  @State private var textPlacementPreview: UIImage?
  /// A one-shot ask for the canvas to bring a freshly opened box on screen —
  /// or, after a drag, back on screen without touching the zoom.
  @State private var boxReveal: (id: Int, rect: CGRect, zooms: Bool)?
  /// Nil is the system font; kept across uses so the next caption starts from
  /// the last face chosen, the way size and colour already behave.
  @State private var textFontFamily: String?
  /// An import whose size disagrees with the canvas, waiting on the person to
  /// choose between expanding the canvas, cropping, and scaling (#293).
  @State private var pendingImport: PendingImport?
  /// A committed placement that hangs over the canvas edge, waiting on the
  /// same expand-or-crop choice (#293).
  @State private var overhangPlacement: Placement?

  struct PendingImport: Equatable {
    let data: Data
    let name: String
    let size: CGSize
  }

  /// An edited size that wraps past the canvas edge, waiting on the person to
  /// shrink it, keep it knowing words will be cut, or keep editing (#298).
  struct TextOverflow: Equatable {
    let chosen: Double
    let fitting: Double
  }
  @State private var pendingTextOverflow: TextOverflow?
  /// On by default: a non-proportional resize distorts a picture, which is
  /// occasionally what someone wants and never what they want by accident.
  @State private var constrainProportions = true
  /// The part of the box a drag took hold of, and the rectangle it started
  /// from. Held here rather than in the box, which is now only a renderer.
  @State private var dragHandle: CropHandle?
  @State private var dragOrigin = CGRect.zero
  @State private var editingTextLayerID: UUID?
  @State private var canvasPreset = CanvasPreset.standard
  @State private var customWidth = "2048"
  @State private var customHeight = "1536"
  @State private var exportDocument = ExportedImageDocument()
  /// Keep transparent areas, or flatten them onto white. In Photoslop a
  /// transparent region sat over the window's own light backdrop and read as
  /// white; a PNG carried it as real transparency, which other viewers show
  /// as black — "what it looks like in Photoslop vs what it looks like when
  /// exported" (#300).
  @State private var exportOnWhite = false
  @State private var exportName = "Photoslop Export"
  @State private var exportFormat = ExportFormat.png
  @State private var exportQuality = 0.9
  @State private var isRenderingExport = false
  @State private var errorMessage: String?
  @State private var explainUnexpectedExit = false
  @State private var inkColor = Color.black
  /// Stroke opacity, separate from the colour so the swatch can show both and
  /// neither hides inside the other.
  @State private var inkOpacity = 1.0
  @State private var showInkOptions = false
  /// Sized from the canvas on first appearance rather than hardcoded (#314);
  /// 8 is what the old constant was, and what a default canvas still resolves
  /// to, so this initial value is only ever seen before the canvas is known.
  @State private var inkWidth = 8.0
  /// Set once the canvas has had its say, so reappearing does not overwrite a
  /// width the user chose.
  @State private var inkWidthEstablished = false
  @State private var tool = BrushTool.pen
  @State private var drawsWithFinger = false
  @State private var showLayers = false
  @Environment(\.horizontalSizeClass) private var horizontalSizeClass

  /// A phone has no room for a permanent sidebar beside the canvas.
  private var isCompact: Bool { horizontalSizeClass == .compact }

  /// A layer being positioned and sized on the canvas.
  ///
  /// One mode covers three things that were three separate gaps: a freshly
  /// imported image arriving at its own size and needing to be put somewhere
  /// (#266), a layer that came in too big or too small being fixed after the
  /// fact (#262), and a text layer being fitted to what is underneath it
  /// (#261). They are the same gesture, so they are the same mode.
  struct Placement: Equatable {
    let layerID: UUID
    var rect: CGRect
    /// The shape to hold when proportions are constrained.
    let ratio: CGFloat
    let isText: Bool
    /// True for an import that has just landed, where Cancel means "I did not
    /// want this layer at all" rather than "leave it where it was".
    let isNew: Bool
  }

  var body: some View {
    Group {
      if isCompact {
        // NavigationSplitView collapses its sidebar into a pushed column at
        // compact width, so reaching the layer list would navigate away from
        // the drawing. A sheet keeps the canvas on screen underneath.
        NavigationStack { editorSurface }
      } else {
        NavigationSplitView {
          layerSidebar
            .navigationTitle("Layers")
        } detail: {
          editorSurface
        }
      }
    }
    .fileImporter(
      isPresented: $showFileImporter,
      allowedContentTypes: [.image],
      allowsMultipleSelection: false,
      onCompletion: importFile
    )
    .fileImporter(
      isPresented: $showLayerFileImporter,
      allowedContentTypes: [.image],
      allowsMultipleSelection: false,
      onCompletion: importLayerFile
    )
    .photosPicker(isPresented: $showPhotosPicker, selection: $selectedPhoto, matching: .images)
    .photosPicker(
      isPresented: $showLayerPhotosPicker,
      selection: $selectedLayerPhotos,
      maxSelectionCount: nil,
      matching: .images
    )
    .onChange(of: selectedLayerPhotos) { _, items in
      guard !items.isEmpty else { return }
      addLayers(from: items)
    }
    .fileExporter(
      isPresented: $showExporter,
      document: exportDocument,
      contentType: exportFormat.utType,
      defaultFilename: "\(exportName).\(exportFormat.fileExtension)"
    ) { result in
      if case .failure(let error) = result { errorMessage = error.localizedDescription }
    }
    .sheet(isPresented: $showImportOptions) {
      importSourceSheet(title: "Import Image", source: $importSource) { chosen in
        switch chosen {
        case .photos: showPhotosPicker = true
        case .files: showFileImporter = true
        }
      }
    }
    .sheet(isPresented: $showLayerImportOptions) {
      importSourceSheet(title: "New Layer from Image", source: $layerImportSource) { chosen in
        switch chosen {
        case .photos: showLayerPhotosPicker = true
        case .files: showLayerFileImporter = true
        }
      }
    }
    .sheet(isPresented: $showExportOptions) { exportOptionsSheet }
    .sheet(isPresented: $showNewDocumentOptions) { newDocumentSheet }
    .sheet(isPresented: $showAbout) { aboutSheet }
    .sheet(isPresented: $showTextOptions) { textOptionsSheet }
    .onChange(of: selectedPhoto) { _, item in
      guard let item else { return }
      Task {
        do {
          guard let data = try await item.loadTransferable(type: Data.self) else {
            throw EditorStore.ImportError.invalidImage
          }
          offerImport(data: data, name: "Photo")
        } catch {
          errorMessage = error.localizedDescription
        }
      }
    }
    // The import-size question (#293). The old importer scaled to fit without
    // asking, which read as auto-cropping to the canvas.
    .confirmationDialog(
      "This image is a different size",
      isPresented: Binding(
        get: { pendingImport != nil },
        set: { if !$0 { pendingImport = nil } }
      ),
      titleVisibility: .visible,
      presenting: pendingImport
    ) { request in
      Button("Expand Canvas to \(Int(request.size.width)) × \(Int(request.size.height))") {
        finishImport(request, sizing: .expandCanvas)
      }
      Button("Crop to Canvas") { finishImport(request, sizing: .cropToCanvas) }
      Button("Scale to Fit") { finishImport(request, sizing: .fit) }
      Button("Cancel", role: .cancel) {}
    } message: { request in
      Text(
        "The image is \(Int(request.size.width)) × \(Int(request.size.height)) px; "
          + "the canvas is \(Int(store.canvasSize.width)) × "
          + "\(Int(store.canvasSize.height)) px.")
    }
    // The same question at placement time, for a layer dragged over the edge.
    .confirmationDialog(
      "The image hangs over the canvas",
      isPresented: Binding(
        get: { overhangPlacement != nil },
        set: { if !$0 { overhangPlacement = nil } }
      ),
      titleVisibility: .visible,
      presenting: overhangPlacement
    ) { pending in
      Button("Expand Canvas to Fit") {
        commitPlacement(pending, expandingCanvas: true)
      }
      Button("Crop to Canvas") {
        commitPlacement(pending, expandingCanvas: false)
      }
      Button("Keep Placing", role: .cancel) {}
    } message: { _ in
      Text(
        "Expand Canvas keeps every pixel and grows the document; "
          + "Crop to Canvas cuts whatever hangs over the edge.")
    }
    .alert(
      "Photoslop",
      isPresented: Binding(
        get: { errorMessage != nil },
        set: { if !$0 { errorMessage = nil } }
      )
    ) {
      Button("OK", role: .cancel) { errorMessage = nil }
    } message: {
      Text(errorMessage ?? "")
    }
    // Saving to Photos hands the picture to another app's library, where
    // nothing on this screen changes to show it worked. Without this the export
    // is indistinguishable from having done nothing.
    .alert("Saved to Photos", isPresented: $savedToPhotos) {
      Button("OK", role: .cancel) { savedToPhotos = false }
    } message: {
      Text("The picture is in your photo library.")
    }
    .modifier(MemoryMessageAlerts(store: store, explainUnexpectedExit: $explainUnexpectedExit))
    .modifier(
      BrushWidthForCanvas(
        store: store, inkWidth: $inkWidth, established: $inkWidthEstablished))
    .onAppear {
      store.undoManager = undoManager
      offerCanvasSizeForNewDocument()
      if SessionLifecycle.shared.previousSessionEndedUnexpectedly {
        SessionLifecycle.shared.acknowledgePreviousSession()
        explainUnexpectedExit = true
      }
    }
    .onChange(of: store.awaitingCanvasSizeChoice) { _, _ in
      offerCanvasSizeForNewDocument()
    }
    .onChange(of: undoManager) { _, manager in store.undoManager = manager }
  }

  private var editorSurface: some View {
    VStack(spacing: 0) {
      PencilCanvas(
        backgroundImage: store.canvasBackground,
        canvasSize: store.canvasSize,
        drawing: store.activeLayer?.drawing ?? PKDrawing(),
        inkColor: UIColor(inkColor.opacity(inkOpacity)),
        inkWidth: inkWidth,
        tool: tool,
        drawsWithFinger: drawsWithFinger,
        drawingOpacity: store.activeLayer?.isVisible == true
          ? (store.activeLayer?.opacity ?? 1)
          : 0,
        onCanvasDragged: isMovingText ? moveText : nil,
        onZoomScaleChanged: { canvasZoom = $0 },
        // Drawing is suspended while a box owns the canvas, so a drag moves the
        // rectangle rather than painting under it. Pinch, zoom and two-finger
        // pan keep working throughout — switching off hit-testing for the whole
        // scroll view is what took them away before (#270).
        overlayIsActive: isCropping || placement != nil,
        onBoxDrag: handleBoxDrag,
        reveal: boxReveal,
        onDrawingChanged: store.setDrawing
      ) {
        canvasOverlay
      }
      if isMovingText { placementBanner }
      // Layout priority so the bar is allocated its height before the canvas
      // takes the rest. Without it the canvas is greedy and the bar is pushed
      // below the visible area — which is how the crop controls ended up at
      // y=1147 on a screen 834 tall in landscape, present in the hierarchy and
      // impossible to tap.
      Group {
        if isCropping {
          cropBar
        } else if placement != nil {
          placementBar
        } else {
          toolStrip
        }
      }
      .layoutPriority(1)
      // Above the canvas in z-order as well. Belt and braces: clipping stops the
      // overlay reaching down here, and this stops anything else that does from
      // winning the touch.
      .zIndex(1)
    }
    // No .navigationTitle here on purpose. DocumentGroup binds the title to
    // the document's file name and drives Rename through it; setting a
    // constant title replaces that binding, so tapping Rename opened a field
    // with nowhere to write and the keyboard dismissed immediately.
    .navigationBarTitleDisplayMode(.inline)
    .toolbar { documentToolbar }
    .sheet(isPresented: $showLayers) {
      if pendingLayerPhotoPick {
        pendingLayerPhotoPick = false
        showLayerImportOptions = true
      }
    } content: {
      NavigationStack {
        layerSidebar
          .navigationTitle("Layers")
          .navigationBarTitleDisplayMode(.inline)
          .toolbar {
            ToolbarItem(placement: .confirmationAction) {
              Button("Done") { showLayers = false }
            }
          }
      }
    }
  }

  private var layerSidebar: some View {
    VStack(spacing: 0) {
      List(
        selection: Binding(
          get: { store.activeLayerID },
          set: { if let id = $0 { store.select(id) } }
        )
      ) {
        ForEach(Array(store.layers.enumerated()).reversed(), id: \.element.id) { _, layer in
          LayerRow(
            layer: layer,
            isActive: layer.id == store.activeLayerID,
            onSelect: { store.select(layer.id) },
            onVisibleChanged: { store.setVisible($0, for: layer.id) },
            onOpacityChanged: { store.setOpacity($0, for: layer.id) },
            onRename: { store.rename($0, for: layer.id) }
          )
          .tag(layer.id)
        }
        .onMove { source, destination in
          let count = store.layers.count
          let translated = IndexSet(source.map { count - 1 - $0 })
          let target = max(0, min(count, count - destination))
          store.moveLayers(fromOffsets: translated, toOffset: target)
        }
      }

      HStack {
        Button(action: store.addLayer) { Image(systemName: "plus") }
          .accessibilityLabel("Add layer")
        Button {
          // At compact width the layer list is a sheet, and a picker asked for
          // while it is up is silently dropped: the flag flips and nothing
          // appears, the same way #229's canvas sheet was lost. Close the layer
          // list first and let its dismissal raise the picker. On iPad the list
          // is a sidebar rather than a sheet, so it can present straight away.
          if isCompact {
            pendingLayerPhotoPick = true
            showLayers = false
          } else {
            showLayerImportOptions = true
          }
        } label: {

          if isAddingLayerPhotos {
            ProgressView()
          } else {
            Image(systemName: "photo.badge.plus")
          }
        }
        .disabled(isAddingLayerPhotos)
        .accessibilityLabel("New layer from photo")
        Button(action: store.duplicateActiveLayer) {
          Image(systemName: "square.on.square")
        }
        .accessibilityLabel("Duplicate layer")
        Button(action: store.mergeActiveDown) { Image(systemName: "square.3.layers.3d.down.right") }
          .disabled(!store.canMergeDown)
          .accessibilityLabel("Merge layer down")
        Spacer()
        EditButton()
        Button(role: .destructive, action: store.deleteActiveLayer) {
          Image(systemName: "trash")
        }
        .disabled(!store.canDeleteLayer)
        .accessibilityLabel("Delete layer")
      }
      .buttonStyle(.bordered)
      .padding(10)
    }
  }

  /// Colour and opacity, in one control the width of a swatch.
  ///
  /// Opacity had no control at all: the alpha slider inside the system colour
  /// sheet was the only way to a translucent stroke, two taps deep under a
  /// button labelled "Ink color", which is not somewhere anyone looks for it
  /// (#271). A third inline slider was the obvious answer and the wrong one —
  /// the strip is budgeted for an iPad mini in portrait, where it already
  /// overflowed once and put the ink controls off the edge of the screen
  /// (#246). So the two things that describe the ink share one popover and one
  /// slot, and the strip's item count does not change.
  private var inkButton: some View {
    Button {
      showInkOptions = true
    } label: {
      // The swatch shows the ink as it will actually paint — colour *and*
      // opacity — over white, so a nearly transparent ink does not read as a
      // pale one.
      ZStack {
        Circle().fill(.white)
        Circle().fill(inkColor.opacity(inkOpacity))
        Circle().strokeBorder(.secondary, lineWidth: 1)
      }
      .frame(width: 28, height: 28)
    }
    .buttonStyle(.plain)
    .accessibilityIdentifier("Ink color")
    .accessibilityLabel("Ink, \(Int((inkOpacity * 100).rounded())) percent opacity")
    // A popover rather than a Menu: menu content is limited to buttons, toggles
    // and pickers, and a Slider placed in one simply does not appear — the
    // control was in the hierarchy and invisible to hand and test alike. A
    // popover holds ordinary views, and its anchor stays a plain Button, which
    // is also hittable in the way a Menu's wrapper never is (L-001).
    .popover(isPresented: $showInkOptions) {
      VStack(alignment: .leading, spacing: 14) {
        ColorPicker("Colour", selection: $inkColor, supportsOpacity: false)

        VStack(alignment: .leading, spacing: 4) {
          Text("Opacity \(Int((inkOpacity * 100).rounded()))%")
            .font(.subheadline)
          Slider(value: $inkOpacity, in: 0.05...1, step: 0.05)
            .accessibilityLabel("Ink opacity")
            .accessibilityIdentifier("Ink opacity")
        }
      }
      .padding(20)
      .frame(width: 280)
      // Without this a popover becomes a sheet on a phone, which is a lot of
      // screen for two controls and covers the canvas they are being judged
      // against.
      .presentationCompactAdaptation(.popover)
    }
  }

  /// What is drawn on the canvas, in the canvas's own pixels.
  @ViewBuilder
  private var canvasOverlay: some View {
    if isCropping {
      CanvasBox(
        rect: cropRect,
        bounds: CGRect(origin: .zero, size: store.canvasSize),
        ratio: cropAspect.ratio(canvas: store.canvasSize),
        scale: canvasZoom)
    } else if let current = placement {
      ZStack(alignment: .topLeading) {
        // The picture follows the box while it is being dragged, drawn from the
        // layer's original pixels straight into the rectangle. The committed
        // copy underneath is suppressed for the duration, or the layer would
        // appear twice — once where it is, once where it is going.
        //
        // An image fills the box — distorting is what a free resize means for
        // pixels. Text rides along as the glyphs cropped from its own
        // rendering, and the box is its *container*: type keeps its shape, so
        // the preview scales to fit from the top-left corner, showing the
        // exact size Done will commit — including that a drag which grows the
        // box past the words' shape grows the words only as far as they fit.
        if let preview = placementPreviewImage(current) {
          if current.isText {
            Image(uiImage: preview)
              .resizable()
              .interpolation(.high)
              .scaledToFit()
              .frame(
                width: current.rect.width, height: current.rect.height,
                alignment: .topLeading)
              .offset(x: current.rect.minX, y: current.rect.minY)
              .allowsHitTesting(false)
              .accessibilityIdentifier("Text preview")
          } else {
            Image(uiImage: preview)
              .resizable()
              .interpolation(.high)
              .frame(width: current.rect.width, height: current.rect.height)
              .offset(x: current.rect.minX, y: current.rect.minY)
              .allowsHitTesting(false)
          }
        }

        CanvasBox(
          rect: current.rect,
          // A layer being placed may hang over the edge — that is how you fill
          // a canvas with the middle of a photograph. A crop may not, and
          // neither may text (#315).
          bounds: placementBounds(isText: current.isText),
          ratio: placementRatio(current),
          scale: canvasZoom,
          dimsOutside: false,
          showsThirds: false,
          identifier: "Transform",
          readoutLabel: "Layer size")
      }
    }
  }

  /// The room a placed layer is allowed to occupy.
  ///
  /// An **image** gets a canvas's worth of slack on every side, so it can be
  /// pushed mostly off the edge without being able to wander somewhere it can
  /// never be dragged back from. That is how you fill a canvas with the middle
  /// of a photograph.
  ///
  /// **Text** is held inside the canvas (#315). Type set large enough — 400 pt
  /// on a phone-sized canvas will do it — grew a box past the canvas edge, and
  /// its corner handles went with it: drawn, but off the artwork and out of
  /// reach, so the box could only be dragged around and never resized. Slack
  /// earns its keep for a photograph, where the overhang is the point. For text
  /// the overhang is just a way to lose the handles, and words placed outside
  /// the canvas would not be in the picture anyway.
  private func placementBounds(isText: Bool) -> CGRect {
    let canvas = CGRect(origin: .zero, size: store.canvasSize)
    guard !isText else { return canvas }
    return canvas.insetBy(dx: -store.canvasSize.width, dy: -store.canvasSize.height)
  }

  /// The shape the box is held to while this layer is placed. The toggle
  /// rules for text too: the box is a container the type scales to fit
  /// inside, so its shape is free even though the type's own is not.
  private func placementRatio(_ current: Placement) -> CGFloat? {
    constrainProportions ? current.ratio : nil
  }

  /// The pixels the placement box is scaling, or nil when there is nothing
  /// sensible to draw live.
  ///
  /// For text this is the glyphs cropped out of the layer's own rendering when
  /// the box opened, so the words visibly follow the rectangle being dragged
  /// instead of sitting behind it at their old size and place.
  private func placementPreviewImage(_ current: Placement) -> UIImage? {
    if current.isText { return textPlacementPreview }
    guard let layer = store.layers.first(where: { $0.id == current.layerID })
    else { return nil }
    return layer.source ?? layer.image
  }

  /// The placement mode's own bar.
  ///
  /// Constrain proportions lives here rather than in a sheet because it is a
  /// thing you change *while* dragging — locked for most of a resize, released
  /// for the one stretch that needs it, locked again.
  private var placementBar: some View {
    HStack(spacing: 14) {
      Button("Cancel", role: .cancel, action: cancelPlacement)
        .accessibilityIdentifier("Cancel Placement")

      Spacer(minLength: 0)

      Toggle(isOn: $constrainProportions) {
        Label(
          "Constrain",
          systemImage: constrainProportions ? "lock" : "lock.open")
      }
      .toggleStyle(.button)
      .accessibilityIdentifier("Constrain proportions")
      .accessibilityLabel(
        "Constrain proportions, \(constrainProportions ? "on" : "off")"
      )
      .onChange(of: constrainProportions) { _, locked in
        // Re-shape what is already on screen rather than waiting for the next
        // drag, so the choice is visible the moment it is made.
        guard locked, let current = placement else { return }
        placement?.rect = CropGeometry.corrected(
          current.rect, to: current.ratio, handle: .interior,
          bounds: placementBounds(isText: current.isText))
      }

      Spacer(minLength: 0)

      Button("Done", action: applyPlacement)
        .buttonStyle(.borderedProminent)
        .accessibilityIdentifier("Apply Placement")
    }
    .padding(.horizontal, 16)
    .padding(.vertical, 10)
    .background(.bar)
  }

  /// The crop mode's own bar, replacing the tool strip while it is up.
  ///
  /// Confirm and cancel live here rather than on the navigation bar, which has
  /// no free slot on a phone — putting them there is what #227, #242 and #246
  /// each did in turn. A mode that owns the bottom of the screen can afford
  /// them, and they sit next to the control that shapes the crop.
  private var cropBar: some View {
    HStack(spacing: 14) {
      Button("Cancel", role: .cancel, action: cancelCrop)
        .accessibilityIdentifier("Cancel Crop")

      Spacer(minLength: 0)

      // The aspect lock. Free is the default because cropping to a custom
      // canvas size is the point; the presets are what you reach for when the
      // destination has a shape.
      Menu {
        Picker("Aspect ratio", selection: $cropAspect) {
          ForEach(CropAspect.allCases) { option in
            Text(option.displayName).tag(option)
          }
        }
        .pickerStyle(.inline)
      } label: {
        Label(
          cropAspect.displayName,
          systemImage: cropAspect.isLocked ? "lock" : "lock.open")
      }
      // SwiftUI renders a Menu as a Button wrapping a Button, so this identifier
      // lands on the outer wrapper and XCUITest reports it as not hittable — the
      // tap belongs to the inner one. `.accessibilityElement(children: .combine)`
      // does not collapse the pair on this iOS version; it was tried and changed
      // nothing. The tests assert the bar's geometry and tap by coordinate
      // instead, which is what a finger does. See LESSONSLEARNED.md L-001.
      .accessibilityIdentifier("Crop aspect")
      .accessibilityLabel("Aspect ratio, \(cropAspect.displayName)")
      .onChange(of: cropAspect) { _, shape in
        // Changing the lock reshapes what is already on screen rather than
        // waiting for the next drag, so the choice is visible immediately.
        guard let ratio = shape.ratio(canvas: store.canvasSize) else { return }
        cropRect = CropGeometry.corrected(
          cropRect, to: ratio, handle: .interior, canvas: store.canvasSize)
      }

      Spacer(minLength: 0)

      Button("Crop", action: { applyCrop(cropRect) })
        .buttonStyle(.borderedProminent)
        .accessibilityIdentifier("Apply Crop")
    }
    .padding(.horizontal, 16)
    .padding(.vertical, 10)
    .background(.bar)
  }

  private var toolStrip: some View {
    ScrollView(.horizontal, showsIndicators: false) {
      HStack(spacing: 14) {
        // Undo and redo are used mid-drawing and cannot go behind a menu, so
        // they live here rather than on the bar — at the leading edge, which is
        // the part of the strip that never has to be scrolled to. This is every
        // width, not just the phone: no navigation bar in the app has a spare
        // slot for them now that each one is budgeted for its narrowest device.
        undoButton.labelStyle(.iconOnly).accessibilityIdentifier("Undo")
        redoButton.labelStyle(.iconOnly).accessibilityIdentifier("Redo")
        Divider().frame(height: 24)

        // A palette, not a segmented control. The segmented picker was a fixed
        // 240pt for four tools, which is most of a phone's strip and the reason
        // the ink well and width slider were scrolled off the end of it. It also
        // could not have taken a fifth tool: six in 240pt is 40pt each, under
        // the 44pt minimum touch target. A menu costs one button's width no
        // matter how many tools there are, so adding one stops being a layout
        // question.
        Menu {
          Picker("Tool", selection: $tool) {
            ForEach(BrushTool.allCases) { brush in
              Label(brush.displayName, systemImage: brush.symbolName).tag(brush)
            }
          }
          .pickerStyle(.inline)
        } label: {
          Label(tool.displayName, systemImage: tool.symbolName)
        }
        .accessibilityLabel("Tool, \(tool.displayName)")

        // Only the options this tool actually uses, which is how the desktop
        // contextual options bar already works. The eraser has no ink or width,
        // and showing both disabled cost ~170pt of a strip that did not have it
        // to spare.
        if tool.usesInk {
          inkButton

          Slider(
            value: $inkWidth,
            in: BrushMetrics.minimumWidth...BrushMetrics.maximumWidth(for: store.canvasSize),
            step: 1)
            .frame(width: isCompact ? 130 : 180)
            .accessibilityLabel("Brush width")
            .accessibilityIdentifier("Brush width")
          Text("\(Int(inkWidth))")
            .font(.caption.monospacedDigit())
            .frame(width: 24, alignment: .leading)
            .accessibilityHidden(true)
        }
      }
      .padding(.horizontal, 16)
      .padding(.vertical, 10)
    }
    .background(.bar)
  }

  /// Two layouts, because a phone's navigation bar cannot hold the iPad's.
  ///
  /// Everything used to go on the bar unconditionally. A phone bar has room for
  /// about two items a side, so UIKit collapsed the leading group into its own
  /// overflow menu and dropped the trailing group outright — Undo, Redo, Export
  /// and About were not on the bar and not in the menu either, so on iPhone
  /// there was no way at all to export. Grouped items overflow; the contents of
  /// a single `ToolbarItem` cannot, which is why the `HStack` that held them
  /// disappeared whole. Choosing the phone's own split keeps the actions worth
  /// a tap on the bar and puts the rest in one menu we control.
  ///
  /// The compact budget is three: a fourth costs the document title and sends
  /// the trailing side back into UIKit's overflow.
  @ToolbarContentBuilder
  private var documentToolbar: some ToolbarContent {
    if isCompact {
      ToolbarItemGroup(placement: .topBarLeading) {
        // On iPad the sidebar is always beside the canvas, so this would be
        // redundant; on a phone it is the only way to reach layers.
        layersButton
        Menu {
          newDocumentButton
          canvasSizeButton
          resizeDocumentButton
          cropButton
          Divider()
          resizeLayerButton
          flattenImageButton
          textButtons
          Divider()
          importImageButton
          Divider()
          canvasModeButtons
          Divider()
          aboutButton
        } label: {
          Label("More Actions", systemImage: "ellipsis.circle")
        }
      }

      // Export earns the one trailing slot: it is how artwork leaves the app,
      // and a second item here costs the document title and pushes both into
      // UIKit's overflow. Undo and redo live in the tool strip for that reason.
      ToolbarItemGroup(placement: .topBarTrailing) {
        exportButton
      }
    } else {
      // One iPad layout, sized for the narrowest iPad rather than the widest.
      //
      // This used to put five leading and four trailing items on the bar, on the
      // assumption that `.regular` means *wide*. It does not: an iPad mini in
      // portrait is 744pt, UIKit had nowhere to put nine items, and it collapsed
      // the trailing group behind an unlabelled chevron — Export Image left the
      // bar. That is #227 again, one size class up.
      //
      // A width threshold was the obvious repair and the wrong one. The bar also
      // grows with the *document*: Edit Text and Move Text exist only while a
      // text layer is active, so a 13-inch iPad in portrait fits nine items and
      // overflows at eleven the moment someone adds text. A budget that holds
      // only until the user does something is not a budget, and every test
      // written before that step passes. So: five items, fixed, at every iPad
      // width — provably inside the narrowest iPad's bar and independent of what
      // the document contains. The cost is that Import Image, Photos and the
      // text actions are one tap deeper on a large iPad; the alternative is a
      // margin thin enough for this bug to return the next time an action is
      // added.
      ToolbarItemGroup(placement: .topBarLeading) {
        newDocumentButton
        canvasSizeButton
        Menu {
          cropButton
          resizeDocumentButton
          Divider()
          resizeLayerButton
          flattenImageButton
          textButtons
          Divider()
          importImageButton
          Divider()
          canvasModeButtons
        } label: {
          Label("More Actions", systemImage: "ellipsis.circle")
        }
      }

      ToolbarItemGroup(placement: .topBarTrailing) {
        exportButton
        aboutButton
      }
    }
  }

  /// Drawing mode and the destructive layer action.
  ///
  /// These were on the tool strip, past its right edge: measured at launch the
  /// Finger toggle was not in the accessibility tree at all and Clear had no
  /// valid activation point on an iPad mini. Neither belongs in the hot path
  /// anyway — Finger is a mode you set once, and Clear destroys a layer's work,
  /// which is not something to leave under a thumb beside the brush controls.
  @ViewBuilder
  private var canvasModeButtons: some View {
    Toggle(isOn: $drawsWithFinger) {
      Label("Finger", systemImage: "hand.draw")
    }
    Button("Clear Layer", systemImage: "trash", role: .destructive) {
      store.clearActiveLayer()
    }
  }

  private var layersButton: some View {
    Button {
      showLayers = true
    } label: {
      Label("Layers", systemImage: "square.3.layers.3d")
    }
  }

  private var newDocumentButton: some View {
    Button {
      canvasSheetMode = .newDocument
      showNewDocumentOptions = true
    } label: {
      Label("New", systemImage: "doc.badge.plus")
    }
    .keyboardShortcut("n", modifiers: .command)
  }

  /// Reachable however the document was made. DocumentGroup builds a document
  /// straight from EditorStore() when one is created in the document browser,
  /// so a size chosen only at New would never be offered for the browser's
  /// documents — which is most of them.
  private var cropButton: some View {
    Button {
      beginCrop()
    } label: {
      Label("Crop…", systemImage: "crop")
    }
  }

  /// Scale the whole document. The third of the three size operations, and the
  /// one that was missing: Canvas Size pads, Crop takes a region, this
  /// resamples (#269).
  private var resizeDocumentButton: some View {
    Button {
      canvasSheetMode = .scale
      syncCustomFieldsToCanvas()
      showNewDocumentOptions = true
    } label: {
      Label("Resize Document…", systemImage: "arrow.up.left.and.down.right.magnifyingglass")
    }
  }

  /// Resize the layer that is already there — the fix for an import that came
  /// in too big or too small to be useful (#262).
  private var resizeLayerButton: some View {
    Button {
      if let id = store.activeLayerID { beginPlacement(layerID: id, isNew: false) }
    } label: {
      Label("Resize Layer…", systemImage: "arrow.up.backward.and.arrow.down.forward")
    }
    .disabled(store.activeLayerID == nil || activeTextLayer != nil)
  }

  private var flattenImageButton: some View {
    Button {
      store.flattenImage()
    } label: {
      Label("Flatten Image", systemImage: "square.3.layers.3d.down.right")
    }
    // One layer is already flat; flattening it would only lose its name.
    .disabled(store.layers.count < 2)
  }

  private var canvasSizeButton: some View {
    Button {
      canvasSheetMode = .resize
      syncCustomFieldsToCanvas()
      showNewDocumentOptions = true
    } label: {
      Label("Canvas Size", systemImage: "aspectratio")
    }
  }

  @ViewBuilder
  private var textButtons: some View {
    Button {
      editingTextLayerID = nil
      textBody = ""
      showTextOptions = true
    } label: {
      Label("Add Text", systemImage: "textformat")
    }

    // Only meaningful when the active layer actually holds text.
    if activeTextLayer != nil {
      Button(action: beginEditingActiveText) {
        Label("Edit Text", systemImage: "character.cursor.ibeam")
      }

      Button {
        isMovingText.toggle()
      } label: {
        Label("Move Text", systemImage: "arrow.up.and.down.and.arrow.left.and.right")
      }

      // Moving was the only thing text could do once placed. Fitting is the
      // other half: drag a box and the type scales to span it, which is what
      // sizing a caption to the picture underneath actually requires (#261).
      Button {
        if let id = store.activeLayerID { beginPlacement(layerID: id, isNew: false) }
      } label: {
        Label("Fit Text…", systemImage: "textformat.size")
      }
    }
  }

  /// One entry point, with the source chosen in the sheet.
  ///
  /// This used to be two menu items — "Import Image", which reached Files only,
  /// and "Photos", which read like a destination rather than an action. On a
  /// phone or an iPad most pictures are in the photo library, so the action
  /// named "import an image" led to the one place they usually are not (#265).
  /// Export already asks where a picture is going with a segmented control; this
  /// is the same control asking where one is coming from.
  private var importImageButton: some View {
    Button {
      showImportOptions = true
    } label: {
      Label("Import Image…", systemImage: "photo.badge.plus")
    }
  }

  /// The source sheet, mirroring the export sheet's destination control.
  ///
  /// A plain button drives `.photosPicker` rather than a `PhotosPicker` view:
  /// the compact layout puts these inside a `Menu`, and a picker nested in a
  /// menu dismisses the menu without ever presenting.
  private func importSourceSheet(
    title: String,
    source: Binding<ImportSource>,
    onChoose: @escaping (ImportSource) -> Void
  ) -> some View {
    NavigationStack {
      Form {
        Section {
          Picker("Import from", selection: source) {
            ForEach(ImportSource.allCases) { option in
              Text(option.displayName).tag(option)
            }
          }
          .pickerStyle(.segmented)
        } footer: {
          Text(
            source.wrappedValue == .photos
              ? "Choose a picture from your photo library."
              : "Choose an image file from Files or iCloud Drive."
          )
        }
      }
      .navigationTitle(title)
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { dismissImportSheets() }
        }
        ToolbarItem(placement: .confirmationAction) {
          Button("Choose") {
            let chosen = source.wrappedValue
            dismissImportSheets()
            onChoose(chosen)
          }
        }
      }
    }
    .presentationDetents([.height(220)])
  }

  private func dismissImportSheets() {
    showImportOptions = false
    showLayerImportOptions = false
  }

  private var undoButton: some View {
    Button {
      undoManager?.undo()
    } label: {
      Label("Undo", systemImage: "arrow.uturn.backward")
    }
    .disabled(undoManager?.canUndo != true)
    .keyboardShortcut("z", modifiers: .command)
  }

  private var redoButton: some View {
    Button {
      undoManager?.redo()
    } label: {
      Label("Redo", systemImage: "arrow.uturn.forward")
    }
    .disabled(undoManager?.canRedo != true)
    .keyboardShortcut("z", modifiers: [.command, .shift])
  }

  private var exportButton: some View {
    Button(action: export) {
      Label("Export Image", systemImage: "square.and.arrow.up")
    }
    .keyboardShortcut("e", modifiers: [.command, .shift])
  }

  private var aboutButton: some View {
    Button {
      showAbout = true
    } label: {
      Label("About Photoslop", systemImage: "info.circle")
    }
  }

  /// Load every chosen photo, then hand them to the store together so the whole
  /// selection is a single undo step rather than one per photo.
  private func addLayers(from items: [PhotosPickerItem]) {
    isAddingLayerPhotos = true
    Task {
      defer {
        isAddingLayerPhotos = false
        selectedLayerPhotos = []
      }
      var loaded: [(name: String, image: UIImage)] = []
      var unreadable = 0
      var unaffordable = 0
      let canvas = store.canvasSize
      let single = items.count == 1
      for item in items {
        // Stop before the allocation that would end the process, not after.
        // Budgeting against what this device actually has left means the same
        // code refuses at a different point on a 6 GB phone and a 16 GB iPad,
        // which is the honest behaviour — a fixed count would be wrong on both.
        guard EditorStore.canAffordLayer(canvas: canvas) else {
          unaffordable = items.count - loaded.count - unreadable
          break
        }
        guard let data = try? await item.loadTransferable(type: Data.self) else {
          unreadable += 1
          continue
        }
        // One photo is placed by hand at its own size, so it still decodes in
        // full — the placement box needs every pixel. A batch is fitted to the
        // canvas anyway, so each one decodes straight to that size and is fitted
        // and released before the next is touched (#309).
        //
        // The `await` sits outside the pool deliberately: `autoreleasepool`
        // cannot span a suspension point, and Swift's async tasks do not drain
        // a thread's pool across one — so without this the CoreGraphics
        // intermediates for every photo in the batch pile up until the whole
        // loop ends, which is the behaviour that got the app killed.
        let prepared: UIImage? = autoreleasepool {
          if single { return try? ProjectArchive.decodeImage(data) }
          guard let decoded = try? ProjectArchive.decodeImage(data, fittingInto: canvas)
          else { return nil }
          return EditorStore.fitted(decoded, into: canvas)
        }
        guard let prepared else {
          unreadable += 1
          continue
        }
        loaded.append((name: "Photo", image: prepared))
      }

      guard !loaded.isEmpty else {
        if unaffordable > 0 {
          errorMessage =
            "There is not enough free memory to add a layer this size. "
            + "Close another document or free some space and try again."
        } else {
          errorMessage =
            unreadable == 0
            ? "Nothing was chosen." : "Those photos could not be read as images."
        }
        return
      }

      // One picture is a deliberate choice and gets placed by hand at its own
      // size; several at once are a batch, and nobody wants to place each of
      // twenty photos in turn, so those still arrive fitted to the canvas.
      if loaded.count == 1, unreadable == 0, let only = loaded.first {
        do {
          let placed = try store.addPlaceableLayer(name: only.name, image: only.image)
          beginPlacement(layerID: placed.id, isNew: true)
        } catch {
          errorMessage = error.localizedDescription
        }
        return
      }

      do {
        let added = try store.addImageLayers(loaded)
        // Say so rather than leaving a silent gap in the layer list.
        if unreadable > 0 || unaffordable > 0 {
          var reasons: [String] = []
          if unreadable > 0 { reasons.append("\(unreadable) could not be read as images") }
          if unaffordable > 0 {
            reasons.append("\(unaffordable) were skipped — not enough free memory")
          }
          errorMessage =
            "Added \(added) of \(added + unreadable + unaffordable). "
            + reasons.joined(separator: "; ") + "."
        }
      } catch {
        errorMessage = error.localizedDescription
      }
    }
  }

  /// A file chosen as a new layer, which arrives at its own size and is placed
  /// by hand — the same treatment a single photo gets.
  private func importLayerFile(_ result: Result<[URL], Error>) {
    do {
      guard let url = try result.get().first else { return }
      let access = url.startAccessingSecurityScopedResource()
      defer { if access { url.stopAccessingSecurityScopedResource() } }
      let image = try ProjectArchive.decodeImage(Data(contentsOf: url))
      let placed = try store.addPlaceableLayer(
        name: url.deletingPathExtension().lastPathComponent, image: image)
      beginPlacement(layerID: placed.id, isNew: true)
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  private func importFile(_ result: Result<[URL], Error>) {
    do {
      guard let url = try result.get().first else { return }
      let access = url.startAccessingSecurityScopedResource()
      defer { if access { url.stopAccessingSecurityScopedResource() } }
      offerImport(
        data: try Data(contentsOf: url), name: url.deletingPathExtension().lastPathComponent)
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  /// Import now when the sizes agree; otherwise put up the question (#293).
  ///
  /// The old behaviour scaled every import to fit without asking, which read
  /// as "importing an image is still auto cropping to canvas size".
  private func offerImport(data: Data, name: String) {
    guard let size = EditorStore.importedImageSize(of: data), size != store.canvasSize else {
      do {
        try store.importImage(data: data, suggestedName: name)
      } catch {
        errorMessage = error.localizedDescription
      }
      return
    }
    pendingImport = PendingImport(data: data, name: name, size: size)
  }

  private func finishImport(_ request: PendingImport, sizing: EditorStore.ImportSizing) {
    do {
      try store.importImage(data: request.data, suggestedName: request.name, sizing: sizing)
    } catch {
      errorMessage = error.localizedDescription
    }
  }

  /// The formats this destination accepts. Photos takes fewer than Files.
  private var availableFormats: [ExportFormat] {
    exportDestination == .photos
      ? ExportFormat.allCases.filter(\.canGoToPhotoLibrary)
      : ExportFormat.allCases
  }

  private var exportFooter: String {
    let alpha =
      exportFormat.preservesTransparency
      ? "keeping transparent areas."
      : "\(exportFormat.displayName) has no alpha channel, so transparent areas are "
        + "flattened onto white."
    switch exportDestination {
    case .files:
      return "Saves as \(exportName).\(exportFormat.fileExtension), \(alpha)"
    case .photos:
      return "Adds the picture to your photo library, \(alpha) "
        + "The file name is not used — Photos names its own assets."
    }
  }

  /// Name and format are chosen here rather than in the system save panel:
  /// `fileExporter` presents `UIDocumentPickerViewController`, which offers no
  /// way to add a format control beside its filename field.
  private var exportOptionsSheet: some View {
    NavigationStack {
      Form {
        Section {
          TextField("File name", text: $exportName)
            .autocorrectionDisabled()
            .textInputAutocapitalization(.never)
          Picker("Save to", selection: $exportDestination) {
            ForEach(ExportDestination.allCases) { destination in
              Text(destination.displayName).tag(destination)
            }
          }
          .pickerStyle(.segmented)
          .onChange(of: exportDestination) { _, destination in
            // Photos takes a narrower set than the Files exporter, so a format
            // it will not accept is corrected here rather than failing after
            // the render with an opaque error.
            if destination == .photos, !exportFormat.canGoToPhotoLibrary {
              exportFormat = .png
            }
          }
          Picker("Format", selection: $exportFormat) {
            ForEach(availableFormats) { format in
              Text(format.displayName).tag(format)
            }
          }
          if exportFormat.preservesTransparency {
            Picker("Background", selection: $exportOnWhite) {
              Text("Keep Transparency").tag(false)
              Text("Flatten to White").tag(true)
            }
            .accessibilityIdentifier("Export background")
          }
        } footer: {
          Text(exportFooter)
        }

        if exportFormat.isLossy {
          Section("Quality") {
            HStack {
              Slider(value: $exportQuality, in: 0.1...1.0, step: 0.05)
                .accessibilityLabel("Export quality")
              Text("\(Int((exportQuality * 100).rounded()))%")
                .monospacedDigit()
                .frame(width: 52, alignment: .trailing)
            }
          }
        }
      }
      .navigationTitle("Export Image")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { showExportOptions = false }
        }
        ToolbarItem(placement: .confirmationAction) {
          Button("Export", action: renderAndPresentExporter)
            .disabled(
              isRenderingExport
                || exportName.trimmingCharacters(in: .whitespaces).isEmpty)
        }
      }
    }
    .presentationDetents([.medium])
  }

  private var requestedCanvasSize: CGSize? {
    if let size = canvasPreset.size { return size }
    guard let width = Int(customWidth.trimmingCharacters(in: .whitespaces)),
      let height = Int(customHeight.trimmingCharacters(in: .whitespaces))
    else { return nil }
    return CanvasPreset.validated(width: width, height: height)
  }

  private var newDocumentSheet: some View {
    NavigationStack {
      Form {
        Section {
          Picker("Size", selection: $canvasPreset) {
            ForEach(CanvasPreset.allCases) { preset in
              VStack(alignment: .leading) {
                Text(preset.displayName)
                Text(preset.subtitle).font(.caption).foregroundStyle(.secondary)
              }
              .tag(preset)
            }
          }
          .pickerStyle(.inline)
          .labelsHidden()
        } header: {
          Text("Canvas Size")
        } footer: {
          if let explanation = canvasSheetMode.explanation { Text(explanation) }
        }

        if canvasPreset == .custom {
          Section {
            LabeledContent("Width") {
              TextField("Width", text: $customWidth)
                .keyboardType(.numberPad)
                .multilineTextAlignment(.trailing)
            }
            LabeledContent("Height") {
              TextField("Height", text: $customHeight)
                .keyboardType(.numberPad)
                .multilineTextAlignment(.trailing)
            }
          } footer: {
            Text(
              requestedCanvasSize == nil
                ? "Enter a size up to \(ProjectArchive.maximumDimension) px per side "
                  + "and \(ProjectArchive.maximumPixels / 1_000_000) megapixels in total."
                : "Creates a \(customWidth) by \(customHeight) px canvas."
            )
            .foregroundStyle(requestedCanvasSize == nil ? .red : .secondary)
          }
        }
      }
      .navigationTitle(canvasSheetMode.title)
      .navigationBarTitleDisplayMode(.inline)
      // The question has now actually been put to someone, so stop tracking it
      // as outstanding. Doing this on appearance rather than when the sheet is
      // requested is what makes a dropped presentation retry.
      .onAppear { store.canvasSizeChoiceOffered() }
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { showNewDocumentOptions = false }
        }
        ToolbarItem(placement: .confirmationAction) {
          Button(canvasSheetMode.confirmTitle) {
            guard let size = requestedCanvasSize else { return }
            switch canvasSheetMode {
            case .newDocument: store.newDocument(size: size)
            case .sizeNewDocument, .resize: store.resizeCanvas(to: size)
            case .scale: store.scaleDocument(to: size)
            }
            showNewDocumentOptions = false
          }
          .disabled(requestedCanvasSize == nil)
        }
      }
    }
  }

  /// Whether the canvas sheet creates a document or resizes the open one.
  private enum CanvasSheetMode {
    case newDocument
    /// Sizing the document DocumentGroup just created. It already exists and is
    /// empty, so this resizes rather than creating a second one.
    case sizeNewDocument
    case resize
    /// Scaling the document rather than its border. Same sheet, same presets,
    /// different verb — and the difference between them is the whole of #269.
    case scale

    var title: String {
      switch self {
      case .newDocument, .sizeNewDocument: "New Document"
      case .resize: "Canvas Size"
      case .scale: "Resize Document"
      }
    }

    var confirmTitle: String {
      switch self {
      case .newDocument: "Create"
      case .sizeNewDocument: "Use This Size"
      case .resize: "Resize"
      case .scale: "Scale"
      }
    }

    /// What this mode does to the picture, said plainly. The three operations
    /// are easy to confuse and the consequences differ: one pads, one discards,
    /// one resamples.
    var explanation: String? {
      switch self {
      case .newDocument, .sizeNewDocument: nil
      case .resize:
        "Keeps everything at its current size and pads or trims the border around it."
      case .scale:
        "Scales the whole picture, and everything on it, to the new size."
      }
    }
  }

  /// Start a resize from the size the document already has, so the fields show
  /// the current canvas rather than whatever was typed last.
  private func syncCustomFieldsToCanvas() {
    customWidth = String(Int(store.canvasSize.width))
    customHeight = String(Int(store.canvasSize.height))
    canvasPreset =
      CanvasPreset.allCases.first { $0.size == store.canvasSize } ?? .custom
  }

  private var aboutSheet: some View {
    let info = Bundle.main.infoDictionary ?? [:]
    let version = info["CFBundleShortVersionString"] as? String ?? "unknown"
    let build = info["CFBundleVersion"] as? String ?? "unknown"
    return NavigationStack {
      List {
        Section {
          LabeledContent("Version", value: version)
          LabeledContent("Build", value: build)
        } header: {
          VStack(spacing: 6) {
            // Le Basilisk, the same QPainter original the desktop About shows.
            // Rendered into the asset catalogue by scripts/render-ios-mascot.py
            // rather than reusing the app icon, which is flattened onto white
            // and would sit in a white box here and in dark mode.
            Image("Mascot")
              .resizable()
              .scaledToFit()
              .frame(width: 96, height: 96)
              .accessibilityLabel("Photoslop mascot")
            // Names no platform, matching the desktop edition's "Photoslop
            // <version>". This read "Photoslop for iPad" on every device,
            // including every iPhone. Branching on the idiom would fix that,
            // but one binary that declines to guess is simpler and cannot be
            // wrong on a device nobody has thought about yet.
            Text("Photoslop").font(.headline)
            // The same sentence the desktop About leads with, so the two
            // editions describe themselves in one voice.
            Text("A memory-frugal, multiplatform, layered raster image editor.")
              .font(.footnote)
              .foregroundStyle(.secondary)
              .multilineTextAlignment(.center)
          }
          .frame(maxWidth: .infinity)
          .padding(.vertical, 12)
          .textCase(nil)
        }

        Section("Canvas") {
          LabeledContent("Size", value: "\(Int(store.canvasSize.width)) x \(Int(store.canvasSize.height)) px")
          LabeledContent("Layers", value: "\(store.layers.count)")
        }

        Section {
          LabeledContent("License", value: "Apache-2.0")
          Link(
            "github.com/CryptoJones/Photoslop",
            destination: URL(string: "https://github.com/CryptoJones/Photoslop")!)
        }

        Section {
          Text("Proudly Made in Nebraska. Go Big Red!")
          Link("https://xkcd.com/2347/", destination: URL(string: "https://xkcd.com/2347/")!)
        }
      }
      .navigationTitle("About")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .confirmationAction) {
          Button("Done") { showAbout = false }
        }
      }
    }
    // Medium alone locked a phone to half height with no way to drag up, so
    // anything past the fold was reachable only by scrolling inside it. About is
    // the one sheet here whose content grows, so it gets to expand.
    .presentationDetents([.medium, .large])
  }

  /// The active layer, when it holds text. Editing and moving both need one.
  private var activeTextLayer: RasterLayer? {
    guard let layer = store.activeLayer, layer.isText else { return nil }
    return layer
  }

  private var placementBanner: some View {
    HStack(spacing: 12) {
      Image(systemName: "hand.draw")
      Text("Drag the text to move it")
      Spacer()
      Button("Done") { isMovingText = false }
    }
    .font(.callout)
    .padding(.horizontal, 16)
    .padding(.vertical, 10)
    .background(.tint.opacity(0.15))
  }

  private var textOptionsSheet: some View {
    NavigationStack {
      Form {
        Section("Text") {
          TextField("Type something", text: $textBody, axis: .vertical)
            .lineLimit(1...5)
        }
        Section {
          LabeledContent("Size") {
            HStack {
              Slider(value: $textSize, in: 8...400, step: 1)
                .accessibilityLabel("Text size")
              Text("\(Int(textSize)) pt").monospacedDigit().frame(width: 64, alignment: .trailing)
            }
          }
          Picker("Font", selection: $textFontFamily) {
            Text("System").tag(String?.none)
            ForEach(UIFont.familyNames.sorted(), id: \.self) { family in
              // Each family shown in its own face — the name alone says
              // nothing about what the type looks like.
              Text(family).font(.custom(family, size: 17)).tag(String?.some(family))
            }
          }
          ColorPicker("Color", selection: $textColor, supportsOpacity: true)
        } footer: {
          Text(
            "Text is its own layer, the same as photoslop-cli --text. The words, "
              + "size, and colour are kept with the document, so it can be edited "
              + "or moved again later."
          )
        }
      }
      .navigationTitle(editingTextLayerID == nil ? "Add Text" : "Edit Text")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") {
            showTextOptions = false
            editingTextLayerID = nil
          }
        }
        ToolbarItem(placement: .confirmationAction) {
          Button(editingTextLayerID == nil ? "Add" : "Save") {
            // A fitted layer's words must never be cut off without consent:
            // if this size wraps past the canvas edge, ask before saving.
            if editingTextLayerID != nil, let overflow = editedTextOverflow() {
              pendingTextOverflow = overflow
            } else {
              showTextOptions = false
              if editingTextLayerID == nil {
                addTextCentred()
              } else {
                commitTextEdit()
              }
            }
          }
          .disabled(textBody.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
      }
    }
    .presentationDetents([.medium])
    .confirmationDialog(
      "That size runs past the canvas",
      isPresented: Binding(
        get: { pendingTextOverflow != nil },
        set: { if !$0 { pendingTextOverflow = nil } }
      ),
      titleVisibility: .visible,
      presenting: pendingTextOverflow
    ) { overflow in
      Button("Shrink to Fit (\(Int(overflow.fitting)) pt)") {
        textSize = overflow.fitting
        showTextOptions = false
        commitTextEdit()
      }
      Button("Keep \(Int(overflow.chosen)) pt — Cut Off the Overflow", role: .destructive) {
        showTextOptions = false
        commitTextEdit()
      }
      Button("Keep Editing", role: .cancel) {}
    } message: { overflow in
      Text(
        "At \(Int(overflow.chosen)) pt the words wrap past the bottom of the canvas, "
          + "and whatever does not fit will be cut off the picture.")
    }
  }

  /// The overflow this edit would cause, or nil when everything fits — only a
  /// fitted layer knows its container, so only fitted layers are checked.
  private func editedTextOverflow() -> TextOverflow? {
    guard let id = editingTextLayerID,
      let content = store.layers.first(where: { $0.id == id })?.text,
      let wrap = content.wrapWidth
    else { return nil }
    let available = CGSize(
      width: CGFloat(wrap),
      height: max(1, store.canvasSize.height - CGFloat(content.y)))
    let wrapped = TextLayerRenderer.measure(
      text: textBody, fontSize: textSize, fontFamily: textFontFamily,
      wrapWidth: CGFloat(wrap))
    guard wrapped.height > available.height else { return nil }
    let fitting =
      TextLayerRenderer.fittingFontSize(
        text: textBody, fontFamily: textFontFamily, in: available) ?? 1
    return TextOverflow(chosen: textSize, fitting: Double(fitting))
  }

  /// Add the layer straight away, centred and on top of the stack.
  ///
  /// This used to wait for a tap on the canvas. A tap that landed outside the
  /// artwork — easy when a large photo is zoomed to fit and surrounded by grey —
  /// was silently dropped, so nothing appeared and no layer was created, with
  /// nothing said about why. Placing immediately cannot fail that way, and Move
  /// Text positions it afterwards.
  private func addTextCentred() {
    let anchor = CGPoint(x: store.canvasSize.width / 2, y: store.canvasSize.height / 2)
    let added = store.addTextLayer(
      textBody, fontSize: textSize, color: UIColor(textColor), at: anchor,
      fontFamily: textFontFamily)
    if added {
      isMovingText = true
    } else {
      errorMessage = "There was nothing to render as text."
    }
  }

  private func moveText(to point: CGPoint, isFinal: Bool) {
    guard let id = activeTextLayer?.id else { return }
    store.moveTextLayer(id, to: point, coalesce: !isFinal)
  }

  /// Load the active text layer's own words back into the sheet, so editing
  /// starts from what is on the canvas rather than whatever was typed last.
  private func beginEditingActiveText() {
    guard let layer = activeTextLayer, let content = layer.text else { return }
    editingTextLayerID = layer.id
    textBody = content.string
    textSize = content.fontSize
    textColor = Color(content.color)
    textFontFamily = content.fontFamily
    showTextOptions = true
  }

  private func commitTextEdit() {
    guard let id = editingTextLayerID else { return }
    editingTextLayerID = nil
    let updated = store.updateTextLayer(
      id, string: textBody, fontSize: textSize, color: UIColor(textColor),
      fontFamily: textFontFamily)
    if !updated {
      errorMessage = "There was nothing to render as text."
    }
  }

  /// DocumentGroup creates a document before the editor is ever on screen, so
  /// the size question is asked the moment that document appears. Cancelling
  /// keeps the default, which is why this resizes an existing empty document
  /// rather than gating creation on an answer.
  ///
  /// The flag is deliberately *not* cleared here. DocumentGroup builds the
  /// editor more than once for a document it creates, and only the last of
  /// those is ever on screen. `awaitingCanvasSizeChoice` lives on the store and
  /// survives that; `showNewDocumentOptions` is `@State` and does not. Clearing
  /// the flag here spent it on a view that was then thrown away, so the visible
  /// editor saw an already-answered question and never asked it — the sheet was
  /// requested on an instance nobody could see. The sheet clears it once it has
  /// actually appeared instead, which makes an unpresented offer retry rather
  /// than vanish.
  private func offerCanvasSizeForNewDocument() {
    guard store.awaitingCanvasSizeChoice else { return }
    canvasSheetMode = .sizeNewDocument
    syncCustomFieldsToCanvas()
    showNewDocumentOptions = true
  }

  private func beginCrop() {
    cropAspect = .free
    cropRect = CropGeometry.initialRect(canvas: store.canvasSize, aspect: .free)
    isCropping = true
  }

  private func cancelCrop() { isCropping = false }

  /// Apply a drag reported by the canvas, in document pixels.
  ///
  /// The box is drawn by SwiftUI and dragged by UIKit, so this is where a touch
  /// becomes a rectangle. Which handle was taken is decided once, from where
  /// the finger landed, and held for the rest of the gesture — deciding it
  /// again on every sample would let the grip jump between handles as the
  /// rectangle moves under the finger.
  private func handleBoxDrag(from start: CGPoint, to current: CGPoint, isFinal: Bool) {
    let translation = CGSize(width: current.x - start.x, height: current.y - start.y)

    if isCropping {
      let handle = dragHandle ?? beginBoxDrag(at: start, in: cropRect)
      guard let handle else { return }
      cropRect = CropGeometry.resized(
        dragOrigin,
        handle: handle,
        translation: translation,
        bounds: CGRect(origin: .zero, size: store.canvasSize),
        ratio: cropAspect.ratio(canvas: store.canvasSize))
    } else if let current = placement {
      let handle = dragHandle ?? beginBoxDrag(at: start, in: current.rect)
      guard let handle else { return }
      placement?.rect = CropGeometry.resized(
        dragOrigin,
        handle: handle,
        translation: translation,
        bounds: placementBounds(isText: current.isText),
        ratio: placementRatio(current))
    }

    if isFinal {
      dragHandle = nil
      dragOrigin = .zero
      // The box has settled: re-render the words wrapped to it, so what sits
      // inside the rectangle is the layout Done will commit.
      if let current = placement, current.isText {
        refreshTextPlacementPreview(layerID: current.layerID, box: current.rect.size)
      }
      // And keep its handles reachable: a drag that pushed an edge off the
      // screen made that edge ungrabbable — the touch landed inside the box
      // and moved it instead (#298). Scroll only; the zoom stays the user's.
      if let current = placement {
        boxReveal = (id: (boxReveal?.id ?? 0) + 1, rect: current.rect, zooms: false)
      }
    }
  }

  /// Render the fit-text preview for the box as it stands: the words wrapped
  /// at the box's width, at the largest size the box can hold — the exact
  /// layout Done will commit (#296). Re-rendered when a drag ends rather than
  /// per sample; between renders the last image scales with the box.
  private func refreshTextPlacementPreview(layerID: UUID, box: CGSize) {
    guard let content = store.layers.first(where: { $0.id == layerID })?.text else { return }
    let fitted =
      TextLayerRenderer.fittingFontSize(
        text: content.string, fontFamily: content.fontFamily, in: box)
      ?? CGFloat(content.fontSize)
    if let rendered = TextLayerRenderer.glyphs(
      text: content.string,
      fontSize: fitted,
      color: content.color,
      fontFamily: content.fontFamily,
      wrapWidth: box.width)
    {
      textPlacementPreview = rendered
    }
  }

  /// Decide what a drag has taken hold of, and remember where it started.
  private func beginBoxDrag(at point: CGPoint, in rect: CGRect) -> CropHandle? {
    // 44pt under the finger, converted into document pixels: the box is drawn
    // in the document's units, so the touch radius has to be too.
    let tolerance = 44 / max(canvasZoom, 0.0001)
    guard let handle = CropGeometry.handle(at: point, in: rect, tolerance: tolerance) else {
      return nil
    }
    dragHandle = handle
    dragOrigin = rect
    return handle
  }

  /// Open the placement box on a layer that is already in the document.
  private func beginPlacement(layerID: UUID, isNew: Bool) {
    guard let layer = store.layers.first(where: { $0.id == layerID }) else { return }
    let rect: CGRect
    if layer.isText {
      guard let measured = store.textRect(for: layerID), measured.width > 1 else { return }
      // Held inside the canvas from the moment it opens (#315). Type large
      // enough measures wider than the canvas, and the box's corner handles
      // went out past the artwork with it — drawn, but nowhere a finger could
      // reach, so the box could be dragged and never resized.
      rect = CropGeometry.contained(
        measured, within: CGRect(origin: .zero, size: store.canvasSize))
    } else {
      rect = store.placementRect(for: layerID)
    }
    guard rect.width > 0, rect.height > 0 else { return }
    store.select(layerID)
    // An image opens locked — a distorted picture is never the default. A
    // text box is a free container the type wraps and scales into, so each
    // handle moves only its own plane unless the lock is chosen (#296).
    constrainProportions = !layer.isText
    placement = Placement(
      layerID: layerID,
      rect: rect,
      ratio: rect.width / rect.height,
      isText: layer.isText,
      isNew: isNew)
    // Hide the committed copy so the live preview is the only one on screen.
    // Text gets its preview rendered fresh from its own words, face and
    // colour — cropping the canvas-sized rendering produced nothing to show
    // on device, and a preview that can silently vanish is not a preview.
    if layer.isText {
      refreshTextPlacementPreview(layerID: layerID, box: rect.size)
    }
    store.previewSuppressedLayerID = layerID
    // The box is only a control if its handles are somewhere a finger can
    // reach; whatever the canvas was showing before, it now shows the box.
    boxReveal = (id: (boxReveal?.id ?? 0) + 1, rect: rect, zooms: true)
  }

  private func applyPlacement() {
    guard let current = placement else { return }
    // An image hanging over the edge is a question, not a decision: expand
    // the canvas to hold every pixel, or cut to the canvas (#293). Text is
    // never asked — fitting words to a region is the whole gesture.
    if !current.isText,
      !CGRect(origin: .zero, size: store.canvasSize).contains(current.rect)
    {
      overhangPlacement = current
      return
    }
    commitPlacement(current, expandingCanvas: false)
  }

  private func commitPlacement(_ current: Placement, expandingCanvas: Bool) {
    store.previewSuppressedLayerID = nil
    if current.isText {
      _ = store.fitTextLayer(current.layerID, to: current.rect)
    } else if expandingCanvas {
      if !store.placeLayerExpandingCanvas(current.layerID, in: current.rect) {
        errorMessage = "The canvas cannot grow that large."
        store.previewSuppressedLayerID = current.layerID
        return
      }
    } else {
      store.placeLayer(
        current.layerID,
        in: current.rect,
        actionName: current.isNew ? "Place Layer" : "Resize Layer")
    }
    placement = nil
    textPlacementPreview = nil
  }

  /// Cancelling an import removes the layer it added: the person asked for a
  /// picture, was shown where it would go, and said no. Leaving it behind at
  /// some arbitrary size would be answering a different question.
  private func cancelPlacement() {
    guard let current = placement else { return }
    store.previewSuppressedLayerID = nil
    if current.isNew { store.deleteLayer(current.layerID) }
    placement = nil
    textPlacementPreview = nil
  }

  private func applyCrop(_ rect: CGRect) {
    isCropping = false
    store.crop(to: rect)
  }

  private func export() { showExportOptions = true }

  private func renderAndPresentExporter() {
    isRenderingExport = true
    Task {
      defer { isRenderingExport = false }
      guard
        let data = await store.exportImage(
          format: exportFormat, quality: exportQuality,
          onWhite: exportOnWhite && exportFormat.preservesTransparency)
      else {
        showExportOptions = false
        errorMessage =
          "The document could not be rendered as \(exportFormat.displayName)."
        return
      }

      // One render, two destinations. Photos gets the same encoded bytes the
      // Files exporter writes, so the two cannot drift into producing different
      // pictures from the same choices.
      switch exportDestination {
      case .files:
        exportDocument = ExportedImageDocument(data: data)
        showExportOptions = false
        showExporter = true
      case .photos:
        do {
          try await PhotoLibrarySaver.save(data, format: exportFormat)
          showExportOptions = false
          savedToPhotos = true
        } catch {
          showExportOptions = false
          errorMessage = error.localizedDescription
        }
      }
    }
  }
}

private struct LayerRow: View {
  let layer: RasterLayer
  let isActive: Bool
  let onSelect: () -> Void
  let onVisibleChanged: (Bool) -> Void
  let onOpacityChanged: (Double) -> Void
  let onRename: (String) -> Void
  @State private var name = ""

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Button {
          onVisibleChanged(!layer.isVisible)
        } label: {
          Image(systemName: layer.isVisible ? "eye" : "eye.slash")
        }
        .buttonStyle(.plain)
        .accessibilityLabel(layer.isVisible ? "Hide layer" : "Show layer")

        TextField(
          "Layer name",
          text: Binding(
            get: { name.isEmpty ? layer.name : name },
            set: { name = $0 }
          )
        )
        .onSubmit {
          onRename(name)
          name = ""
        }
        .fontWeight(isActive ? .semibold : .regular)
      }
      Slider(
        value: Binding(get: { layer.opacity }, set: onOpacityChanged),
        in: 0...1
      ) {
        Text("Opacity")
      } minimumValueLabel: {
        Text("0%")
      } maximumValueLabel: {
        Text("100%")
      }
      .controlSize(.small)
    }
    .contentShape(Rectangle())
    .onTapGesture(perform: onSelect)
    .accessibilityElement(children: .contain)
    .accessibilityLabel("\(layer.name) layer")
    .accessibilityValue(
      "\(layer.isVisible ? "visible" : "hidden"), "
        + "\(Int((layer.opacity * 100).rounded())) percent opacity"
    )
    .accessibilityHint("Double tap to make active; use the eye button to toggle visibility")
  }
}

/// Carries already-encoded image bytes to the system save panel. The bytes are
/// produced by `ExportFormat.encode`, so this type stays format-agnostic and
/// the concrete type is supplied to `fileExporter` per export.
struct ExportedImageDocument: FileDocument {
  static var readableContentTypes: [UTType] { ExportFormat.allCases.map(\.utType) }
  var data = Data()

  init(data: Data = Data()) { self.data = data }

  init(configuration: ReadConfiguration) throws {
    guard let data = configuration.file.regularFileContents else {
      throw CocoaError(.fileReadCorruptFile)
    }
    self.data = data
  }

  func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
    FileWrapper(regularFileWithContents: data)
  }
}

/// The two things the app says about memory, kept out of `EditorView.body`.
///
/// Not a style choice: adding these inline tipped the body over the Swift
/// type-checker's limit ("unable to type-check this expression in reasonable
/// time"). A modifier gives the chain a fixed, already-resolved type.
private struct MemoryMessageAlerts: ViewModifier {
  @ObservedObject var store: EditorStore
  @Binding var explainUnexpectedExit: Bool

  func body(content: Content) -> some View {
    content
      // Low memory, said out loud rather than handled in silence (#311).
      .alert(
        "Low Memory",
        isPresented: Binding(
          get: { store.memoryPressureNotice != nil },
          set: { if !$0 { store.memoryPressureNotice = nil } }
        )
      ) {
        Button("OK", role: .cancel) { store.memoryPressureNotice = nil }
      } message: {
        Text(store.memoryPressureNotice ?? "")
      }
      // A jetsam kill leaves no crash report and no message of its own, so the
      // explanation has to come from the next launch (#311).
      .alert("Photoslop Closed Unexpectedly", isPresented: $explainUnexpectedExit) {
        Button("OK", role: .cancel) { explainUnexpectedExit = false }
      } message: {
        Text(SessionLifecycle.unexpectedExitMessage)
      }
  }
}

/// Keeps the brush in proportion to the canvas (#314).
///
/// A modifier rather than inline, for the same reason the memory alerts are
/// one: adding this to `EditorView.body` tipped it past the Swift type-checker
/// ("unable to type-check this expression in reasonable time").
private struct BrushWidthForCanvas: ViewModifier {
  @ObservedObject var store: EditorStore
  @Binding var inkWidth: Double
  @Binding var established: Bool

  func body(content: Content) -> some View {
    content
      .onChange(of: store.canvasSize) { previous, current in
        // Carry the brush across a resize so it keeps its apparent weight
        // against the picture, rather than silently becoming a hairline on a
        // bigger canvas — which is the failure this issue is about.
        inkWidth = BrushMetrics.rescaled(inkWidth, from: previous, to: current)
      }
      .onAppear {
        guard !established else { return }
        inkWidth = BrushMetrics.defaultWidth(for: store.canvasSize)
        established = true
      }
  }
}

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
  @State private var showExporter = false
  @State private var showExportOptions = false
  @State private var showNewDocumentOptions = false
  @State private var canvasSheetMode = CanvasSheetMode.newDocument
  @State private var showAbout = false
  @State private var showTextOptions = false
  @State private var textBody = ""
  @State private var textSize = 48.0
  @State private var textColor = Color.black
  @State private var isMovingText = false
  @State private var editingTextLayerID: UUID?
  @State private var canvasPreset = CanvasPreset.standard
  @State private var customWidth = "2048"
  @State private var customHeight = "1536"
  @State private var exportDocument = ExportedImageDocument()
  @State private var exportName = "Photoslop Export"
  @State private var exportFormat = ExportFormat.png
  @State private var exportQuality = 0.9
  @State private var isRenderingExport = false
  @State private var errorMessage: String?
  @State private var inkColor = Color.black
  @State private var inkWidth = 8.0
  @State private var tool = BrushTool.pen
  @State private var drawsWithFinger = false
  @State private var showLayers = false
  @Environment(\.horizontalSizeClass) private var horizontalSizeClass

  /// A phone has no room for a permanent sidebar beside the canvas.
  private var isCompact: Bool { horizontalSizeClass == .compact }

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
          try store.importImage(data: data, suggestedName: "Photo")
        } catch {
          errorMessage = error.localizedDescription
        }
      }
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
    .onAppear {
      store.undoManager = undoManager
      offerCanvasSizeForNewDocument()
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
        inkColor: UIColor(inkColor),
        inkWidth: inkWidth,
        tool: tool,
        drawsWithFinger: drawsWithFinger,
        drawingOpacity: store.activeLayer?.isVisible == true
          ? (store.activeLayer?.opacity ?? 1)
          : 0,
        onCanvasDragged: isMovingText ? moveText : nil,
        onDrawingChanged: store.setDrawing
      )
      if isMovingText { placementBanner }
      toolStrip
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
        showLayerPhotosPicker = true
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
            showLayerPhotosPicker = true
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

  private var toolStrip: some View {
    ScrollView(.horizontal, showsIndicators: false) {
      HStack(spacing: 14) {
        // A phone's navigation bar has room for three controls beside the
        // document title, and Layers, the actions menu and Export take them.
        // Undo and redo are used mid-drawing and cannot go behind a menu, so
        // they come here instead — at the leading edge, which is the part of
        // the strip that never has to be scrolled to.
        if isCompact {
          // Icon-only: a navigation bar hides a Label's title by itself, an
          // HStack does not, and spelling both out costs a third of the strip.
          undoButton.labelStyle(.iconOnly)
          redoButton.labelStyle(.iconOnly)
          Divider().frame(height: 24)
        }

        Picker("Tool", selection: $tool) {
          ForEach(BrushTool.allCases) { brush in
            Label(brush.displayName, systemImage: brush.symbolName).tag(brush)
          }
        }
        .pickerStyle(.segmented)
        .frame(width: isCompact ? 240 : 300)

        ColorPicker("Ink", selection: $inkColor, supportsOpacity: true)
          .labelsHidden()
          .disabled(!tool.usesInk)
          .accessibilityLabel("Ink color")

        Image(systemName: "circle.fill").font(.system(size: 6))
        Slider(value: $inkWidth, in: 1...80, step: 1)
          .frame(width: isCompact ? 130 : 180)
          .accessibilityLabel("Brush width")
        Image(systemName: "circle.fill").font(.system(size: 18))

        Toggle(isOn: $drawsWithFinger) {
          Label("Finger", systemImage: "hand.draw")
        }
        .toggleStyle(.button)

        Button("Clear", role: .destructive, action: store.clearActiveLayer)
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
          textButtons
          Divider()
          importImageButton
          photosButton
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
      ToolbarItemGroup(placement: .topBarLeading) {
        newDocumentButton
        canvasSizeButton
        textButtons
        importImageButton
        photosButton
      }

      ToolbarItemGroup(placement: .topBarTrailing) {
        undoButton
        redoButton
        exportButton
        aboutButton
      }
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
    }
  }

  private var importImageButton: some View {
    Button {
      showFileImporter = true
    } label: {
      Label("Import Image", systemImage: "photo.badge.plus")
    }
  }

  /// A plain button driving `.photosPicker`, not a `PhotosPicker` view, because
  /// the compact layout puts this inside a `Menu` and a picker nested in a menu
  /// dismisses the menu without ever presenting.
  private var photosButton: some View {
    Button {
      showPhotosPicker = true
    } label: {
      Label("Photos", systemImage: "photo.on.rectangle")
    }
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
      for item in items {
        guard let data = try? await item.loadTransferable(type: Data.self),
          let image = try? ProjectArchive.decodeImage(data)
        else {
          unreadable += 1
          continue
        }
        loaded.append((name: "Photo", image: image))
      }

      guard !loaded.isEmpty else {
        errorMessage =
          unreadable == 0
          ? "Nothing was chosen." : "Those photos could not be read as images."
        return
      }

      do {
        let added = try store.addImageLayers(loaded)
        // Say so rather than leaving a silent gap in the layer list.
        if unreadable > 0 {
          errorMessage =
            "Added \(added) of \(added + unreadable). "
            + "\(unreadable) could not be read as images."
        }
      } catch {
        errorMessage = error.localizedDescription
      }
    }
  }

  private func importFile(_ result: Result<[URL], Error>) {
    do {
      guard let url = try result.get().first else { return }
      let access = url.startAccessingSecurityScopedResource()
      defer { if access { url.stopAccessingSecurityScopedResource() } }
      try store.importImage(
        data: Data(contentsOf: url), suggestedName: url.deletingPathExtension().lastPathComponent)
    } catch {
      errorMessage = error.localizedDescription
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
          Picker("Format", selection: $exportFormat) {
            ForEach(ExportFormat.allCases) { format in
              Text(format.displayName).tag(format)
            }
          }
        } footer: {
          Text(
            exportFormat.preservesTransparency
              ? "Saves as \(exportName).\(exportFormat.fileExtension), keeping transparent areas."
              : "Saves as \(exportName).\(exportFormat.fileExtension). "
                + "\(exportFormat.displayName) has no alpha channel, so transparent "
                + "areas are flattened onto white."
          )
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
        Section("Canvas Size") {
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

    var title: String {
      switch self {
      case .newDocument, .sizeNewDocument: "New Document"
      case .resize: "Canvas Size"
      }
    }

    var confirmTitle: String {
      switch self {
      case .newDocument: "Create"
      case .sizeNewDocument: "Use This Size"
      case .resize: "Resize"
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
            showTextOptions = false
            if editingTextLayerID == nil {
              addTextCentred()
            } else {
              commitTextEdit()
            }
          }
          .disabled(textBody.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
      }
    }
    .presentationDetents([.medium])
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
      textBody, fontSize: textSize, color: UIColor(textColor), at: anchor)
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
    showTextOptions = true
  }

  private func commitTextEdit() {
    guard let id = editingTextLayerID else { return }
    editingTextLayerID = nil
    let updated = store.updateTextLayer(
      id, string: textBody, fontSize: textSize, color: UIColor(textColor))
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

  private func export() { showExportOptions = true }

  private func renderAndPresentExporter() {
    isRenderingExport = true
    Task {
      defer { isRenderingExport = false }
      guard
        let data = await store.exportImage(format: exportFormat, quality: exportQuality)
      else {
        showExportOptions = false
        errorMessage =
          "The document could not be rendered as \(exportFormat.displayName)."
        return
      }
      exportDocument = ExportedImageDocument(data: data)
      showExportOptions = false
      showExporter = true
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

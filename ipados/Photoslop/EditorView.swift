// SPDX-License-Identifier: Apache-2.0
import PencilKit
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

struct EditorView: View {
  @ObservedObject var store: EditorStore
  @Environment(\.undoManager) private var undoManager
  @State private var selectedPhoto: PhotosPickerItem?
  @State private var showFileImporter = false
  @State private var showExporter = false
  @State private var showExportOptions = false
  @State private var showNewDocumentOptions = false
  @State private var canvasSheetMode = CanvasSheetMode.newDocument
  @State private var showAbout = false
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
    .onAppear { store.undoManager = undoManager }
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
        onDrawingChanged: store.setDrawing
      )
      toolStrip
    }
    // No .navigationTitle here on purpose. DocumentGroup binds the title to
    // the document's file name and drives Rename through it; setting a
    // constant title replaces that binding, so tapping Rename opened a field
    // with nowhere to write and the keyboard dismissed immediately.
    .navigationBarTitleDisplayMode(.inline)
    .toolbar { documentToolbar }
    .sheet(isPresented: $showLayers) {
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

  @ToolbarContentBuilder
  private var documentToolbar: some ToolbarContent {
    ToolbarItemGroup(placement: .topBarLeading) {
      // On iPad the sidebar is always beside the canvas, so this would be
      // redundant; on a phone it is the only way to reach layers.
      if isCompact {
        Button {
          showLayers = true
        } label: {
          Label("Layers", systemImage: "square.3.layers.3d")
        }
      }

      Button {
        canvasSheetMode = .newDocument
        showNewDocumentOptions = true
      } label: {
        Label("New", systemImage: "doc.badge.plus")
      }
      .keyboardShortcut("n", modifiers: .command)

      // Reachable however the document was made. DocumentGroup builds a
      // document straight from EditorStore() when one is created in the
      // document browser, so a size chosen only at New would never be offered
      // for the browser's documents — which is most of them.
      Button {
        canvasSheetMode = .resize
        syncCustomFieldsToCanvas()
        showNewDocumentOptions = true
      } label: {
        Label("Canvas Size", systemImage: "aspectratio")
      }

      Button {
        showFileImporter = true
      } label: {
        Label("Import Image", systemImage: "photo.badge.plus")
      }

      PhotosPicker(selection: $selectedPhoto, matching: .images) {
        Label("Photos", systemImage: "photo.on.rectangle")
      }
    }

    ToolbarItem(placement: .topBarTrailing) {
      HStack {
        Button {
          undoManager?.undo()
        } label: {
          Label("Undo", systemImage: "arrow.uturn.backward")
        }
        .disabled(undoManager?.canUndo != true)
        .keyboardShortcut("z", modifiers: .command)

        Button {
          undoManager?.redo()
        } label: {
          Label("Redo", systemImage: "arrow.uturn.forward")
        }
        .disabled(undoManager?.canRedo != true)
        .keyboardShortcut("z", modifiers: [.command, .shift])

        Button(action: export) {
          Label("Export Image", systemImage: "square.and.arrow.up")
        }
        .keyboardShortcut("e", modifiers: [.command, .shift])

        Button {
          showAbout = true
        } label: {
          Label("About Photoslop", systemImage: "info.circle")
        }
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
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { showNewDocumentOptions = false }
        }
        ToolbarItem(placement: .confirmationAction) {
          Button(canvasSheetMode.confirmTitle) {
            guard let size = requestedCanvasSize else { return }
            switch canvasSheetMode {
            case .newDocument: store.newDocument(size: size)
            case .resize: store.resizeCanvas(to: size)
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
    case resize

    var title: String {
      switch self {
      case .newDocument: "New Document"
      case .resize: "Canvas Size"
      }
    }

    var confirmTitle: String {
      switch self {
      case .newDocument: "Create"
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
            Image(systemName: "paintbrush.pointed.fill")
              .font(.system(size: 44))
              .foregroundStyle(.tint)
            Text("Photoslop for iPad").font(.headline)
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
    .presentationDetents([.medium])
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

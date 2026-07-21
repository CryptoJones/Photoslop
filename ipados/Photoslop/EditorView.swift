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
  @State private var exportDocument = PNGDocument()
  @State private var errorMessage: String?
  @State private var inkColor = Color.black
  @State private var inkWidth = 8.0
  @State private var isEraser = false
  @State private var drawsWithFinger = false

  var body: some View {
    NavigationSplitView {
      layerSidebar
        .navigationTitle("Layers")
    } detail: {
      VStack(spacing: 0) {
        PencilCanvas(
          backgroundImage: store.canvasBackground,
          canvasSize: store.canvasSize,
          drawing: store.activeLayer?.drawing ?? PKDrawing(),
          inkColor: UIColor(inkColor),
          inkWidth: inkWidth,
          isEraser: isEraser,
          drawsWithFinger: drawsWithFinger,
          drawingOpacity: store.activeLayer?.isVisible == true
            ? (store.activeLayer?.opacity ?? 1)
            : 0,
          onDrawingChanged: store.setDrawing
        )
        toolStrip
      }
      .navigationTitle("Photoslop")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar { documentToolbar }
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
      contentType: .png,
      defaultFilename: "Photoslop Export.png"
    ) { result in
      if case .failure(let error) = result { errorMessage = error.localizedDescription }
    }
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
        Picker("Tool", selection: $isEraser) {
          Label("Pen", systemImage: "pencil.tip").tag(false)
          Label("Eraser", systemImage: "eraser").tag(true)
        }
        .pickerStyle(.segmented)
        .frame(width: 160)

        ColorPicker("Ink", selection: $inkColor, supportsOpacity: true)
          .labelsHidden()
          .disabled(isEraser)
          .accessibilityLabel("Ink color")

        Image(systemName: "circle.fill").font(.system(size: 6))
        Slider(value: $inkWidth, in: 1...80, step: 1)
          .frame(width: 180)
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
      Button {
        store.newDocument()
      } label: {
        Label("New", systemImage: "doc.badge.plus")
      }
      .keyboardShortcut("n", modifiers: .command)

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
          Label("Export PNG", systemImage: "square.and.arrow.up")
        }
        .keyboardShortcut("e", modifiers: [.command, .shift])
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

  private func export() {
    Task {
      guard let data = await store.exportPNG() else {
        errorMessage = "The document could not be rendered as PNG."
        return
      }
      exportDocument = PNGDocument(data: data)
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

struct PNGDocument: FileDocument {
  static var readableContentTypes: [UTType] { [.png] }
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

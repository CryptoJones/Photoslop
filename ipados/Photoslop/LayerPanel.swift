// SPDX-License-Identifier: Apache-2.0
import PencilKit
import SwiftUI
import UIKit

/// The layer stack: a thumbnail per layer, the active layer's opacities above
/// the list, and the layer actions below it.
///
/// A sidebar on an iPad, a sheet on a phone — the caller decides, and tells
/// the panel so a picker asked for from inside a sheet can be deferred until
/// the sheet is down (the flag flips and nothing appears otherwise, the way
/// #229's canvas sheet was lost).
struct LayerPanel: View {
  @ObservedObject var store: EditorStore
  let isAddingPhotos: Bool
  let onNewLayerFromPhoto: () -> Void
  let onEffects: () -> Void

  var body: some View {
    VStack(spacing: 0) {
      if let active = store.activeLayer {
        LayerProperties(
          layer: active,
          onOpacityChanged: { store.setOpacity($0, for: active.id, coalesce: $1) },
          onFillOpacityChanged: { store.setFillOpacity($0, for: active.id, coalesce: $1) })
        Divider().overlay(Studio.hairline)
      }

      List(
        selection: Binding(
          get: { store.activeLayerID },
          set: { if let id = $0 { store.select(id) } }
        )
      ) {
        ForEach(Array(store.layers.enumerated()).reversed(), id: \.element.id) { _, layer in
          LayerRow(
            layer: layer,
            canvasSize: store.canvasSize,
            isActive: layer.id == store.activeLayerID,
            onSelect: { store.select(layer.id) },
            onVisibleChanged: { store.setVisible($0, for: layer.id) },
            onRename: { store.rename($0, for: layer.id) }
          )
          .tag(layer.id)
          .listRowBackground(
            layer.id == store.activeLayerID ? Studio.accent.opacity(0.14) : Color.clear
          )
          .listRowSeparatorTint(Studio.hairline)
        }
        .onMove { source, destination in
          let count = store.layers.count
          let translated = IndexSet(source.map { count - 1 - $0 })
          let target = max(0, min(count, count - destination))
          store.moveLayers(fromOffsets: translated, toOffset: target)
        }
      }
      .listStyle(.plain)
      .scrollContentBackground(.hidden)

      Divider().overlay(Studio.hairline)
      actions
    }
    .background(Studio.chrome)
  }

  /// Add, add from a photo, effects, duplicate, merge down; then reorder and
  /// delete at the far end, away from the thumb that adds.
  private var actions: some View {
    HStack(spacing: 2) {
      Button(action: store.addLayer) { Label("Add layer", systemImage: "plus") }
        .accessibilityLabel("Add layer")
      Button(action: onNewLayerFromPhoto) {
        if isAddingPhotos {
          ProgressView()
            .frame(width: Studio.iconSide, height: Studio.iconSide)
        } else {
          Label("New layer from photo", systemImage: "photo.badge.plus")
        }
      }
      .disabled(isAddingPhotos)
      .accessibilityLabel("New layer from photo")
      Button(action: onEffects) { Label("Layer effects", systemImage: "sparkles") }
        .disabled(store.activeLayer == nil)
        .accessibilityLabel("Layer effects")
      Button(action: store.duplicateActiveLayer) {
        Label("Duplicate layer", systemImage: "square.on.square")
      }
      .accessibilityLabel("Duplicate layer")
      Button(action: store.mergeActiveDown) {
        Label("Merge layer down", systemImage: "square.3.layers.3d.down.right")
      }
      .disabled(!store.canMergeDown)
      .accessibilityLabel("Merge layer down")
      Spacer(minLength: 0)
      EditButton()
        .font(.subheadline)
        .padding(.horizontal, 6)
      Button(role: .destructive, action: store.deleteActiveLayer) {
        Label("Delete layer", systemImage: "trash")
      }
      .disabled(!store.canDeleteLayer)
      .accessibilityLabel("Delete layer")
    }
    .buttonStyle(.icon)
    .padding(.horizontal, 8)
    .padding(.vertical, 6)
  }
}

/// The active layer's two opacities, above the list where a layer palette
/// keeps them: the layer's, and the fill's.
///
/// Fill opacity is the control that makes a shadow-only layer possible — it
/// fades the pixels and leaves the effects — and a second slider is cheaper
/// to understand than a menu that explains it. They used to sit inside every
/// row, which made a row three lines tall and the list a wall of sliders.
private struct LayerProperties: View {
  let layer: RasterLayer
  /// The value, and whether more samples of the same drag are coming: true
  /// while the finger is down, false for the sample that ends it.
  let onOpacityChanged: (Double, Bool) -> Void
  let onFillOpacityChanged: (Double, Bool) -> Void

  var body: some View {
    VStack(spacing: 6) {
      row(
        "Opacity", value: layer.opacity, identifier: "Layer opacity", onChange: onOpacityChanged)
      row(
        "Fill", value: layer.fillOpacity, identifier: "Layer fill opacity",
        onChange: onFillOpacityChanged
      )
      .accessibilityLabel("Fill opacity")
    }
    .padding(.horizontal, 16)
    .padding(.vertical, 10)
  }

  private func row(
    _ title: String, value: Double, identifier: String,
    onChange: @escaping (Double, Bool) -> Void
  ) -> some View {
    HStack(spacing: 10) {
      Text(title)
        .font(.caption)
        .foregroundStyle(.secondary)
        .frame(width: 48, alignment: .leading)
      // Samples during the drag coalesce; the end of the drag re-sends the
      // value it settled on as the one sample that registers the undo step.
      Slider(
        value: Binding(get: { value }, set: { onChange($0, true) }), in: 0...1,
        onEditingChanged: { editing in
          if !editing { onChange(value, false) }
        }
      ) {
        Text(title)
      }
      .controlSize(.small)
      .accessibilityIdentifier(identifier)
      Text("\(Int((value * 100).rounded()))%")
        .font(.caption.monospacedDigit())
        .foregroundStyle(.secondary)
        .frame(width: 40, alignment: .trailing)
    }
  }
}

/// One layer: thumbnail, name, what it is, and its eye.
private struct LayerRow: View {
  let layer: RasterLayer
  let canvasSize: CGSize
  let isActive: Bool
  let onSelect: () -> Void
  let onVisibleChanged: (Bool) -> Void
  let onRename: (String) -> Void
  @State private var name = ""
  @FocusState private var isEditingName: Bool

  var body: some View {
    HStack(spacing: 12) {
      LayerThumbnail(layer: layer, canvasSize: canvasSize, isActive: isActive)

      VStack(alignment: .leading, spacing: 2) {
        TextField(
          "Layer name",
          text: Binding(
            get: { name.isEmpty ? layer.name : name },
            set: { name = $0 }
          )
        )
        .focused($isEditingName)
        .onSubmit(commitRename)
        // Return is not the only way out of a field: a tap on another row or
        // the sheet's Done leaves it too, and a name typed and then left that
        // way was shown and never kept.
        .onChange(of: isEditingName) { _, editing in
          if !editing { commitRename() }
        }
        .font(.subheadline.weight(isActive ? .semibold : .regular))
        Text(detail)
          .font(.caption2)
          .foregroundStyle(.secondary)
      }

      Spacer(minLength: 0)

      Button {
        onVisibleChanged(!layer.isVisible)
      } label: {
        Image(systemName: layer.isVisible ? "eye" : "eye.slash")
          .font(.system(size: 15, weight: .medium))
          .foregroundStyle(layer.isVisible ? Color.primary : Color.secondary)
          .frame(width: 36, height: 36)
          .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel(layer.isVisible ? "Hide layer" : "Show layer")
    }
    .padding(.vertical, 2)
    .contentShape(Rectangle())
    .onTapGesture(perform: onSelect)
    .accessibilityElement(children: .contain)
    .accessibilityLabel("\(layer.name) layer")
    .accessibilityValue(
      "\(layer.isVisible ? "visible" : "hidden"), "
        + "\(Int((layer.opacity * 100).rounded())) percent opacity, "
        + "\(Int((layer.fillOpacity * 100).rounded())) percent fill"
    )
    .accessibilityHint("Double tap to make active; use the eye button to toggle visibility")
  }

  private func commitRename() {
    guard !name.isEmpty else { return }
    if name != layer.name { onRename(name) }
    name = ""
  }

  private var detail: String {
    var parts = [layer.isText ? "Text" : "Paint"]
    if layer.opacity < 1 || layer.fillOpacity < 1 {
      parts.append("\(Int((layer.fillAlpha * 100).rounded()))%")
    }
    if !layer.effects.isEmpty { parts.append("Effects") }
    return parts.joined(separator: " · ")
  }
}

/// A small picture of the layer as it sits on the canvas, over a checkerboard
/// so a transparent layer looks transparent.
///
/// Rendered off the main actor and only when the layer's pixels, strokes or
/// the canvas change, which `task(id:)` decides from the key: the image
/// compares by identity because every mutation draws a new one, and the
/// strokes by revision (#355). The result is a 44pt square at 2x — a few tens
/// of kilobytes a layer, well inside DD-001 — and it is held by the row, so it
/// goes when the row does.
struct LayerThumbnail: View {
  let layer: RasterLayer
  let canvasSize: CGSize
  let isActive: Bool
  @State private var image: UIImage?

  static let side: CGFloat = 44

  private struct Key: Hashable {
    let image: ObjectIdentifier
    let revision: Int
    let origin: CGPoint
    let canvas: CGSize

    static func == (lhs: Key, rhs: Key) -> Bool {
      lhs.image == rhs.image && lhs.revision == rhs.revision && lhs.origin == rhs.origin
        && lhs.canvas == rhs.canvas
    }

    func hash(into hasher: inout Hasher) {
      hasher.combine(image)
      hasher.combine(revision)
      hasher.combine(origin.x)
      hasher.combine(origin.y)
      hasher.combine(canvas.width)
      hasher.combine(canvas.height)
    }
  }

  private var key: Key {
    Key(
      image: ObjectIdentifier(layer.image), revision: layer.drawingRevision,
      origin: layer.origin, canvas: canvasSize)
  }

  var body: some View {
    let shape = RoundedRectangle(cornerRadius: 6, style: .continuous)
    ZStack {
      Image(uiImage: Self.checkerboard)
        .resizable(resizingMode: .tile)
      if let image {
        Image(uiImage: image)
          .resizable()
          .interpolation(.medium)
          .aspectRatio(contentMode: .fit)
      }
    }
    .frame(width: Self.side, height: Self.side)
    .clipShape(shape)
    .overlay(
      shape.strokeBorder(
        isActive ? Studio.accent : Studio.hairline, lineWidth: isActive ? 2 : 1)
    )
    .opacity(layer.isVisible ? 1 : 0.4)
    .accessibilityHidden(true)
    .task(id: key) {
      let rendered = await Self.render(layer, canvasSize: canvasSize)
      // A key change cancels this task and starts the next; the render it
      // was awaiting still finishes, and must not land over the newer one.
      guard !Task.isCancelled else { return }
      image = rendered
    }
  }

  /// Eight-point squares, drawn once. Darker than the canvas's own
  /// checkerboard so it reads as chrome rather than as more artwork.
  private static let checkerboard: UIImage = {
    let tile: CGFloat = 16
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    return UIGraphicsImageRenderer(size: CGSize(width: tile, height: tile), format: format)
      .image { context in
        UIColor(white: 0.40, alpha: 1).setFill()
        context.fill(CGRect(x: 0, y: 0, width: tile, height: tile))
        UIColor(white: 0.30, alpha: 1).setFill()
        context.fill(CGRect(x: 0, y: 0, width: tile / 2, height: tile / 2))
        context.fill(CGRect(x: tile / 2, y: tile / 2, width: tile / 2, height: tile / 2))
      }
  }()

  /// The layer's pixels and strokes, scaled so the whole canvas fits the
  /// thumbnail square. Nothing here is canvas-sized: the pixels draw straight
  /// into the small context, and PencilKit rasterises the strokes at the
  /// thumbnail's scale.
  nonisolated static func render(_ layer: RasterLayer, canvasSize: CGSize) async -> UIImage? {
    guard canvasSize.width > 0, canvasSize.height > 0 else { return nil }
    let scale = min(side / canvasSize.width, side / canvasSize.height)
    let size = CGSize(
      width: max(1, (canvasSize.width * scale).rounded()),
      height: max(1, (canvasSize.height * scale).rounded()))
    let pixels = layer.image
    let origin = layer.origin
    let drawing = layer.drawing
    let hasStrokes = !drawing.bounds.isEmpty
    return await Task.detached(priority: .utility) {
      let format = UIGraphicsImageRendererFormat()
      format.scale = 2
      format.opaque = false
      return UIGraphicsImageRenderer(size: size, format: format).image { context in
        context.cgContext.interpolationQuality = .medium
        pixels.draw(
          in: CGRect(
            x: origin.x * scale, y: origin.y * scale,
            width: pixels.size.width * scale, height: pixels.size.height * scale))
        if hasStrokes {
          drawing.literalImage(from: CGRect(origin: .zero, size: canvasSize), scale: scale * 2)
            .draw(in: CGRect(origin: .zero, size: size))
        }
      }
    }.value
  }
}

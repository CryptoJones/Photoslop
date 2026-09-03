// SPDX-License-Identifier: Apache-2.0
import SwiftUI

/// The **Effects…** sheet: a text layer's live appearance stack, edited as a
/// draft that the canvas previews and Apply commits as one undo step (#316).
///
/// The list is the desktop appearance panel's shape — an ordered stack with
/// Add, reorder and remove, the built-in presets as a quick pick, and one
/// page of controls per effect. The controls edit the same parameters under
/// the same names the desktop uses, so what is set here is what
/// `photoslop-cli --effect` would set.
struct EffectsSheet: View {
  @ObservedObject var store: EditorStore
  let layerID: UUID
  @Binding var isPresented: Bool
  @State private var draft: [LayerEffect]

  init(store: EditorStore, layerID: UUID, isPresented: Binding<Bool>) {
    self.store = store
    self.layerID = layerID
    _isPresented = isPresented
    _draft = State(initialValue: store.layers.first { $0.id == layerID }?.effects ?? [])
  }

  var body: some View {
    NavigationStack {
      List {
        Section {
          ForEach($draft) { $effect in
            NavigationLink {
              EffectEditor(effect: $effect)
            } label: {
              HStack {
                Toggle(isOn: $effect.enabled) { EmptyView() }
                  .labelsHidden()
                  .accessibilityLabel("\(effect.label) enabled")
                Text(effect.label)
                  .foregroundStyle(effect.enabled ? .primary : .secondary)
              }
            }
            .accessibilityIdentifier("Effect \(effect.label)")
          }
          .onMove { source, destination in
            draft.move(fromOffsets: source, toOffset: destination)
          }
          .onDelete { offsets in draft.remove(atOffsets: offsets) }

          Menu {
            ForEach(LayerEffect.renderableKinds, id: \.self) { kind in
              Button(LayerEffect.labels[kind] ?? kind) {
                if let effect = LayerEffect(kind: kind) { draft.append(effect) }
              }
            }
          } label: {
            Label("Add Effect", systemImage: "plus")
          }
          .accessibilityIdentifier("Add Effect")
        } header: {
          Text("Effects")
        } footer: {
          Text(
            draft.isEmpty
              ? "Shadows, glows, outlines and bevels are drawn from the type each time "
                + "it is rendered, so they follow the words when they are edited or moved."
              : "Effects draw in this order, first at the bottom. Swipe to remove; "
                + "drag to reorder.")
        }

        Section("Presets") {
          ForEach(LayerEffect.presets, id: \.name) { preset in
            Button {
              // A preset replaces the stack, as on the desktop.
              draft = LayerEffect.preset(named: preset.name) ?? []
            } label: {
              HStack {
                Text(preset.name)
                Spacer()
                Text(preset.effects.map(\.label).joined(separator: " + "))
                  .font(.caption)
                  .foregroundStyle(.secondary)
              }
            }
            .foregroundStyle(.primary)
          }
        }
      }
      .navigationTitle("Effects")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { isPresented = false }
        }
        ToolbarItem(placement: .confirmationAction) {
          Button("Apply") {
            store.setEffects(draft, for: layerID)
            isPresented = false
          }
        }
        ToolbarItem(placement: .topBarTrailing) { EditButton() }
      }
    }
    .onChange(of: draft) { _, current in
      store.previewEffects = (layerID, current)
    }
    .onAppear { store.previewEffects = (layerID, draft) }
    // The preview is the sheet's alone: whichever way it closes, the layer's
    // own stack comes back, and Apply has already made that the draft.
    .onDisappear { store.previewEffects = nil }
  }
}

/// One effect's controls, keyed by the desktop parameter they edit.
struct EffectEditor: View {
  @Binding var effect: LayerEffect

  var body: some View {
    Form {
      Section {
        Toggle("Enabled", isOn: $effect.enabled)
        slider("Opacity", value: $effect.opacity, in: 0...1, step: 0.01, unit: "%", scale: 100)
        Picker("Blend", selection: $effect.blendMode) {
          ForEach(LayerEffect.blendModes, id: \.self) { mode in
            Text(mode.replacingOccurrences(of: "-", with: " ").capitalized).tag(mode)
          }
        }
      }
      Section(effect.label) {
        switch effect.kind {
        case "drop-shadow", "inner-shadow":
          color("Color", key: "color")
          number("Offset X", key: "offset_x", in: -200...200)
          number("Offset Y", key: "offset_y", in: -200...200)
          number("Blur", key: "blur", in: 0...100)
          number("Spread", key: "spread", in: 0...50)
        case "outer-glow":
          color("Color", key: "color")
          number("Size", key: "size", in: 0...100)
          number("Spread", key: "spread", in: 0...50)
        case "inner-glow":
          color("Color", key: "color")
          number("Size", key: "size", in: 0...100)
          number("Choke", key: "choke", in: 0...50)
          choice("Source", key: "source", options: ["edge", "center"])
        case "outline":
          color("Color", key: "color")
          number("Width", key: "width", in: 1...50)
          choice("Position", key: "position", options: ["outside", "inside", "center"])
        case "color-overlay":
          color("Color", key: "color")
        case "gradient-overlay":
          color("Start", key: "color1")
          color("End", key: "color2")
          number("Angle", key: "angle", in: 0...360, unit: "°")
          number("Scale", key: "scale", in: 1...400, unit: "%")
          number("Offset X", key: "offset_x", in: -200...200)
          number("Offset Y", key: "offset_y", in: -200...200)
          Toggle("Reverse", isOn: bool("reverse"))
        case "bevel-emboss":
          color("Highlight", key: "highlight_color")
          color("Shadow", key: "shadow_color")
          number("Depth", key: "depth", in: 1...500, unit: "%")
          number("Size", key: "size", in: 0...50)
          number("Soften", key: "soften", in: 0...20)
          number("Light Angle", key: "angle", in: 0...360, unit: "°")
          number("Altitude", key: "altitude", in: 0...90, unit: "°")
        default:
          Text("This effect is kept with the document but is not drawn on iOS.")
            .foregroundStyle(.secondary)
        }
      }
    }
    .navigationTitle(effect.label)
    .navigationBarTitleDisplayMode(.inline)
  }

  private func number(
    _ label: String, key: String, in range: ClosedRange<Double>, unit: String = " px"
  ) -> some View {
    slider(
      label,
      value: Binding(
        get: { effect.number(key) },
        set: { effect.parameters[key] = .number($0.rounded()) }
      ),
      in: range, step: 1, unit: unit, scale: 1)
  }

  private func slider(
    _ label: String, value: Binding<Double>, in range: ClosedRange<Double>, step: Double,
    unit: String, scale: Double
  ) -> some View {
    LabeledContent(label) {
      HStack {
        Slider(value: value, in: range, step: step)
          .accessibilityLabel(label)
        Text("\(Int((value.wrappedValue * scale).rounded()))\(unit)")
          .monospacedDigit()
          .frame(width: 64, alignment: .trailing)
      }
    }
  }

  private func color(_ label: String, key: String) -> some View {
    ColorPicker(
      label,
      selection: Binding(
        get: {
          let rgba = effect.rgba(key)
          return Color(
            red: Double(rgba[0]) / 255, green: Double(rgba[1]) / 255,
            blue: Double(rgba[2]) / 255, opacity: Double(rgba[3]) / 255)
        },
        set: { picked in
          var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 1
          UIColor(picked).getRed(&r, green: &g, blue: &b, alpha: &a)
          func channel(_ value: CGFloat) -> Int { Int((min(1, max(0, value)) * 255).rounded()) }
          effect.parameters[key] = .rgba(channel(r), channel(g), channel(b), channel(a))
        }
      ),
      supportsOpacity: true)
  }

  private func choice(_ label: String, key: String, options: [String]) -> some View {
    Picker(
      label,
      selection: Binding(
        get: { effect.string(key) },
        set: { effect.parameters[key] = .string($0) }
      )
    ) {
      ForEach(options, id: \.self) { Text($0.capitalized).tag($0) }
    }
  }

  private func bool(_ key: String) -> Binding<Bool> {
    Binding(get: { effect.bool(key) }, set: { effect.parameters[key] = .bool($0) })
  }
}

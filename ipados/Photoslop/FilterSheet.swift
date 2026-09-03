// SPDX-License-Identifier: Apache-2.0
import SwiftUI

/// The parameter sheet behind each row of the Filters menu (#327): the iOS
/// counterpart of the desktop `FilterParamsDialog`, built from the same
/// `ParamSpec`s. An integer becomes a slider (or a switch for a 0/1 flag),
/// a float a finer slider, a choice a picker. Apply runs the filter once over
/// the active layer; there is no live preview — the desktop dialog has none
/// either, and a preview would mean a second full-size buffer per drag.
struct FilterSheet: View {
  let kind: FilterKind
  let onApply: (FilterParams) -> Void
  let onCancel: () -> Void

  @State private var values: FilterParams

  init(kind: FilterKind, onApply: @escaping (FilterParams) -> Void, onCancel: @escaping () -> Void) {
    self.kind = kind
    self.onApply = onApply
    self.onCancel = onCancel
    _values = State(initialValue: kind.defaults)
  }

  var body: some View {
    NavigationStack {
      Form {
        Section {
          ForEach(kind.params) { spec in
            control(for: spec)
          }
        } footer: {
          Text(
            "The same maths as the desktop filter and photoslop-cli --filter "
              + "\(kind.rawValue), applied to the active layer as one undo step. "
              + "With a selection, only the selected pixels change."
          )
        }
      }
      .navigationTitle(kind.label)
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel", action: onCancel)
            .accessibilityIdentifier("Cancel filter")
        }
        ToolbarItem(placement: .confirmationAction) {
          Button("Apply") { onApply(values) }
            .accessibilityIdentifier("Apply filter")
        }
      }
    }
    .presentationDetents([.medium, .large])
  }

  @ViewBuilder
  private func control(for spec: FilterParamSpec) -> some View {
    switch spec.kind {
    case .int(let low, let high, let fallback):
      if spec.isToggle {
        Toggle(spec.label, isOn: intBinding(spec.name, fallback: fallback).asBool)
          .accessibilityIdentifier("Filter \(spec.name)")
      } else {
        LabeledContent(spec.label) {
          HStack {
            Slider(
              value: intBinding(spec.name, fallback: fallback).asDouble,
              in: Double(low)...Double(high), step: 1
            )
            .accessibilityLabel(spec.label)
            .accessibilityIdentifier("Filter \(spec.name)")
            Text("\(values.int(spec.name, default: fallback))")
              .monospacedDigit()
              .frame(width: 52, alignment: .trailing)
          }
        }
      }
    case .float(let low, let high, let fallback):
      LabeledContent(spec.label) {
        HStack {
          Slider(value: floatBinding(spec.name, fallback: fallback), in: low...high, step: 0.1)
            .accessibilityLabel(spec.label)
            .accessibilityIdentifier("Filter \(spec.name)")
          Text(values.float(spec.name, default: fallback), format: .number.precision(.fractionLength(1)))
            .monospacedDigit()
            .frame(width: 52, alignment: .trailing)
        }
      }
    case .choice(let options, let fallback):
      Picker(spec.label, selection: choiceBinding(spec.name, fallback: fallback)) {
        ForEach(options, id: \.self) { option in
          Text(option.capitalized).tag(option)
        }
      }
      .accessibilityIdentifier("Filter \(spec.name)")
    }
  }

  private func intBinding(_ name: String, fallback: Int) -> Binding<Int> {
    Binding(
      get: { values.int(name, default: fallback) },
      set: { values[name] = .int($0) })
  }

  private func floatBinding(_ name: String, fallback: Double) -> Binding<Double> {
    Binding(
      get: { values.float(name, default: fallback) },
      set: { values[name] = .float(($0 * 10).rounded() / 10) })
  }

  private func choiceBinding(_ name: String, fallback: String) -> Binding<String> {
    Binding(
      get: { values.choice(name, default: fallback) },
      set: { values[name] = .choice($0) })
  }
}

extension Binding where Value == Int {
  /// A slider's `Double` face over an `Int`.
  fileprivate var asDouble: Binding<Double> {
    Binding<Double>(get: { Double(wrappedValue) }, set: { wrappedValue = Int($0.rounded()) })
  }

  /// A switch's `Bool` face over a 0/1 flag.
  fileprivate var asBool: Binding<Bool> {
    Binding<Bool>(get: { wrappedValue != 0 }, set: { wrappedValue = $0 ? 1 : 0 })
  }
}

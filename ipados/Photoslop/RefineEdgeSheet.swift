// SPDX-License-Identifier: Apache-2.0
import SwiftUI

/// The Refine Edge / Select and Mask sheet on iPadOS/iOS (Issue #417).
/// Provides interactive Guided Filter edge matting, adaptive smart radius,
/// smooth, feather, contrast steepening, shift edge, and color decontamination.
struct RefineEdgeSheet: View {
  let onApply: (RefineSelectionOptions) -> Void
  let onCancel: () -> Void
  var onPreview: ((RefineSelectionOptions) -> Void)? = nil

  @State private var options = RefineSelectionOptions()

  var body: some View {
    NavigationStack {
      Form {
        // MARK: - Edge Detection
        Section("Edge Detection") {
          VStack(alignment: .leading, spacing: 6) {
            HStack {
              Text("Radius")
              Spacer()
              Text("\(options.radius) px")
                .font(.body.monospacedDigit())
                .foregroundStyle(.secondary)
            }
            HStack {
              Slider(
                value: Binding(
                  get: { Double(options.radius) },
                  set: { options.radius = Int($0) }
                ),
                in: 0...100,
                step: 1
              )
              .accessibilityLabel("Edge detection radius")
              .accessibilityIdentifier("Edge detection radius")
              Stepper(
                "",
                value: $options.radius,
                in: 0...100
              )
              .labelsHidden()
            }
          }

          Toggle("Smart Radius", isOn: $options.smartRadius)
            .accessibilityIdentifier("Smart Radius")
        }

        // MARK: - Global Refinements
        Section("Global Refinements") {
          // Smooth
          VStack(alignment: .leading, spacing: 6) {
            HStack {
              Text("Smooth")
              Spacer()
              Text("\(options.smooth) px")
                .font(.body.monospacedDigit())
                .foregroundStyle(.secondary)
            }
            HStack {
              Slider(
                value: Binding(
                  get: { Double(options.smooth) },
                  set: { options.smooth = Int($0) }
                ),
                in: 0...100,
                step: 1
              )
              .accessibilityLabel("Smooth")
              .accessibilityIdentifier("Smooth")
              Stepper("", value: $options.smooth, in: 0...100)
                .labelsHidden()
            }
          }

          // Feather
          VStack(alignment: .leading, spacing: 6) {
            HStack {
              Text("Feather")
              Spacer()
              Text("\(options.feather) px")
                .font(.body.monospacedDigit())
                .foregroundStyle(.secondary)
            }
            HStack {
              Slider(
                value: Binding(
                  get: { Double(options.feather) },
                  set: { options.feather = Int($0) }
                ),
                in: 0...100,
                step: 1
              )
              .accessibilityLabel("Feather")
              .accessibilityIdentifier("Feather")
              Stepper("", value: $options.feather, in: 0...100)
                .labelsHidden()
            }
          }

          // Contrast
          VStack(alignment: .leading, spacing: 6) {
            HStack {
              Text("Contrast")
              Spacer()
              Text("\(options.contrast)%")
                .font(.body.monospacedDigit())
                .foregroundStyle(.secondary)
            }
            HStack {
              Slider(
                value: Binding(
                  get: { Double(options.contrast) },
                  set: { options.contrast = Int($0) }
                ),
                in: 0...100,
                step: 1
              )
              .accessibilityLabel("Contrast")
              .accessibilityIdentifier("Contrast")
              Stepper("", value: $options.contrast, in: 0...100)
                .labelsHidden()
            }
          }

          // Shift Edge
          VStack(alignment: .leading, spacing: 6) {
            HStack {
              Text("Shift Edge")
              Spacer()
              Text("\(options.shiftEdge)%")
                .font(.body.monospacedDigit())
                .foregroundStyle(.secondary)
            }
            HStack {
              Slider(
                value: Binding(
                  get: { Double(options.shiftEdge) },
                  set: { options.shiftEdge = Int($0) }
                ),
                in: -100...100,
                step: 1
              )
              .accessibilityLabel("Shift Edge")
              .accessibilityIdentifier("Shift Edge")
              Stepper("", value: $options.shiftEdge, in: -100...100)
                .labelsHidden()
            }
          }
        }

        // MARK: - Output Settings / Decontamination
        Section("Output Settings") {
          Toggle("Decontaminate Colors", isOn: $options.decontaminate)
            .accessibilityIdentifier("Decontaminate Colors")

          if options.decontaminate {
            VStack(alignment: .leading, spacing: 6) {
              HStack {
                Text("Amount")
                Spacer()
                Text("\(Int(options.decontaminateAmount * 100))%")
                  .font(.body.monospacedDigit())
                  .foregroundStyle(.secondary)
              }
              HStack {
                Slider(
                  value: $options.decontaminateAmount,
                  in: 0.0...1.0,
                  step: 0.05
                )
                .accessibilityLabel("Decontaminate Amount")
                .accessibilityIdentifier("Decontaminate Amount")
              }
            }
          }
        }
      }
      .navigationTitle("Refine Edge")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel", action: onCancel)
            .accessibilityIdentifier("Cancel refine edge")
        }
        ToolbarItem(placement: .confirmationAction) {
          Button("Apply") { onApply(options) }
            .accessibilityIdentifier("Apply refine edge")
        }
      }
    }
    .presentationDetents([.medium, .large])
    .onChange(of: options) { _, current in
      onPreview?(current)
    }
  }
}

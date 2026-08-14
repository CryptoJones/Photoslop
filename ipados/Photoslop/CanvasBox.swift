// SPDX-License-Identifier: Apache-2.0
import SwiftUI

/// A rectangle on the canvas whose edges and corners drag.
///
/// One control, three jobs: choosing a region to crop, placing and sizing an
/// imported layer, and fitting a text layer to what is underneath. They are the
/// same gesture on the same surface, and the differences between them —
/// whether the rectangle may leave the canvas, whether the outside is dimmed —
/// are parameters rather than separate views.
///
/// **The rectangle is in document pixels.** This view is hosted inside the
/// canvas's scroll view, whose content coordinate space *is* the document, so
/// there is no conversion between what is drawn and what is applied: the
/// readout is the truth rather than a rendering of it. The earlier version
/// floated above the canvas in screen points and converted, which is how the
/// crop came to take a region nobody chose (#260, #268).
///
/// `scale` is the one thing that still depends on the view: handles and labels
/// are for the finger, not for the document, so they are divided by the zoom to
/// stay the same size on screen however far in the canvas is zoomed.
struct CanvasBox: View {
  @Binding var rect: CGRect
  /// Where the rectangle may go. The canvas, for a crop; larger, for a layer
  /// being placed, which is allowed to hang over the edge.
  let bounds: CGRect
  /// Width over height, when the shape is locked. Nil is free.
  let ratio: CGFloat?
  /// Points per document pixel.
  let scale: CGFloat
  var dimsOutside = true
  var showsThirds = true
  var showsReadout = true
  var identifier = "Crop"
  var readoutLabel = "Crop size"

  /// Drawn handles are small; touch targets are not. 44pt is Apple's minimum
  /// and a handle sits under a fingertip, so the hit area is padded well past
  /// what is painted — then divided by the zoom, so it is 44 *points* rather
  /// than 44 document pixels.
  private var handleTouch: CGFloat { 44 / max(scale, 0.0001) }
  private var handleDraw: CGFloat { 22 / max(scale, 0.0001) }
  private var hairline: CGFloat { 2 / max(scale, 0.0001) }

  @State private var dragStart: CGRect?

  var body: some View {
    ZStack(alignment: .topLeading) {
      if dimsOutside {
        // Everything outside the rectangle is dimmed, so the crop is legible
        // before it is committed rather than after.
        Color.black.opacity(0.55)
          .reverseMask {
            Rectangle()
              .frame(width: rect.width, height: rect.height)
              .offset(x: rect.minX, y: rect.minY)
          }
          .allowsHitTesting(false)
      }

      Rectangle()
        .strokeBorder(.white, lineWidth: hairline)
        .frame(width: rect.width, height: rect.height)
        .offset(x: rect.minX, y: rect.minY)
        .allowsHitTesting(false)

      if showsThirds { thirdsGuides }

      // The interior drags the whole rectangle.
      Color.clear
        .contentShape(Rectangle())
        .frame(width: rect.width, height: rect.height)
        .offset(x: rect.minX, y: rect.minY)
        .gesture(drag(for: .interior))

      ForEach(Array(handles.enumerated()), id: \.offset) { _, handle in
        handleView(handle)
      }

      if showsReadout { readout }
    }
  }

  private var handles: [CropHandle] {
    [.topLeft, .top, .topRight, .left, .right, .bottomLeft, .bottom, .bottomRight]
  }

  @ViewBuilder
  private var thirdsGuides: some View {
    Path { path in
      for step in 1...2 {
        let x = rect.minX + rect.width * CGFloat(step) / 3
        let y = rect.minY + rect.height * CGFloat(step) / 3
        path.move(to: CGPoint(x: x, y: rect.minY))
        path.addLine(to: CGPoint(x: x, y: rect.maxY))
        path.move(to: CGPoint(x: rect.minX, y: y))
        path.addLine(to: CGPoint(x: rect.maxX, y: y))
      }
    }
    .stroke(.white.opacity(0.35), lineWidth: hairline / 2)
    .allowsHitTesting(false)
  }

  private func handleView(_ handle: CropHandle) -> some View {
    let point = position(of: handle)
    return RoundedRectangle(cornerRadius: 3 / max(scale, 0.0001))
      .fill(.white)
      .frame(width: handleDraw, height: handleDraw)
      .shadow(radius: 2 / max(scale, 0.0001))
      .frame(width: handleTouch, height: handleTouch)
      .contentShape(Rectangle())
      .position(x: point.x, y: point.y)
      .gesture(drag(for: handle))
      .accessibilityLabel(name(handle))
      .accessibilityIdentifier("\(identifier) \(name(handle))")
  }

  private func name(_ handle: CropHandle) -> String {
    switch handle {
    case .topLeft: "top left"
    case .top: "top"
    case .topRight: "top right"
    case .left: "left"
    case .right: "right"
    case .bottomLeft: "bottom left"
    case .bottom: "bottom"
    case .bottomRight: "bottom right"
    case .interior: "region"
    }
  }

  /// A handle sits on the edge, which is where a handle belongs.
  ///
  /// An earlier version inset these so the 44pt touch target stayed inside the
  /// canvas, on the theory that a bottom handle was covering the crop bar. It
  /// was not: the accessibility hierarchy showed the bar perfectly placed and
  /// nothing on top of it. Insetting moved the handles off the line they exist
  /// to mark, for a fault that was never there. See LESSONSLEARNED.md L-001.
  private func position(of handle: CropHandle) -> CGPoint {
    let x: CGFloat =
      handle.movesLeftEdge ? rect.minX : handle.movesRightEdge ? rect.maxX : rect.midX
    let y: CGFloat =
      handle.movesTopEdge ? rect.minY : handle.movesBottomEdge ? rect.maxY : rect.midY
    return CGPoint(x: x, y: y)
  }

  private func drag(for handle: CropHandle) -> some Gesture {
    DragGesture(minimumDistance: 0)
      .onChanged { value in
        let start = dragStart ?? rect
        if dragStart == nil { dragStart = rect }
        // No conversion: this view's coordinate space is the document's, so a
        // translation here is already a translation in canvas pixels.
        rect = CropGeometry.resized(
          start,
          handle: handle,
          translation: value.translation,
          bounds: bounds,
          ratio: ratio)
      }
      .onEnded { _ in dragStart = nil }
  }

  /// The size the rectangle describes, in pixels, while it is being chosen.
  /// This is what makes "a custom canvas size" a deliberate choice rather than
  /// a guess.
  private var readout: some View {
    Text("\(Int(rect.width)) × \(Int(rect.height))")
      .font(.caption.monospacedDigit().weight(.semibold))
      .padding(.horizontal, 10)
      .padding(.vertical, 6)
      .background(.black.opacity(0.7), in: Capsule())
      .foregroundStyle(.white)
      .fixedSize()
      // Chrome, not document: drawn at its natural point size and then scaled
      // down by the zoom so it reads the same however far in the canvas is.
      .scaleEffect(1 / max(scale, 0.0001))
      .position(x: rect.midX, y: max(rect.minY - 22 / max(scale, 0.0001), 22 / max(scale, 0.0001)))
      .allowsHitTesting(false)
      .accessibilityIdentifier(readoutLabel)
      .accessibilityLabel("\(readoutLabel) \(Int(rect.width)) by \(Int(rect.height))")
  }
}

extension View {
  /// Punch a hole in this view. `mask` keeps what is inside the shape; the crop
  /// dimming needs the opposite.
  fileprivate func reverseMask<Mask: View>(@ViewBuilder _ mask: () -> Mask) -> some View {
    self.mask {
      Rectangle().overlay(alignment: .topLeading) {
        mask().blendMode(.destinationOut)
      }
    }
  }
}

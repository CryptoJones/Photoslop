// SPDX-License-Identifier: Apache-2.0
import SwiftUI

/// The crop mode: a rectangle over the canvas whose edges and corners drag.
///
/// Canvas Size already existed and takes a size, but not a *region* — you could
/// not say which part of the picture to keep, or see what you were about to
/// lose. This is the other half: choose the region by eye, read the resulting
/// pixel size as you drag, and apply it as one undoable step.
///
/// The rectangle is held in canvas pixels rather than screen points, so the
/// readout is the truth rather than a conversion of it, and the applied crop is
/// exactly what the readout said.
struct CropOverlay: View {
  let canvas: CGSize
  @Binding var rect: CGRect
  @Binding var aspect: CropAspect
  let onCancel: () -> Void
  let onApply: (CGRect) -> Void

  /// Drawn handles are small; touch targets are not. 44pt is Apple's minimum
  /// and a crop handle sits under a fingertip, so the hit area is padded well
  /// past what is painted.
  private let handleTouchSize: CGFloat = 44
  private let handleDrawSize: CGFloat = 22

  @State private var dragStart: CGRect?

  var body: some View {
    GeometryReader { proxy in
      let scale = fittedScale(in: proxy.size)
      let origin = fittedOrigin(in: proxy.size, scale: scale)
      let frame = CGRect(
        x: origin.x + rect.minX * scale,
        y: origin.y + rect.minY * scale,
        width: rect.width * scale,
        height: rect.height * scale)

      ZStack(alignment: .topLeading) {
        // Everything outside the rectangle is dimmed, so the crop is legible
        // before it is committed rather than after.
        Color.black.opacity(0.55)
          .reverseMask {
            Rectangle().frame(width: frame.width, height: frame.height).offset(
              x: frame.minX, y: frame.minY)
          }
          // Deliberately NOT .ignoresSafeArea(). Extending the dimming past the
          // overlay's bounds grows the layout it is attached to, which pushed
          // the crop bar below the bottom of the window on an iPad mini — the
          // same "control exists but cannot be reached" fault as #227, #242 and
          // #246. The dimming only ever needs to cover the canvas.
          .allowsHitTesting(false)

        Rectangle()
          .strokeBorder(.white, lineWidth: 2)
          .frame(width: frame.width, height: frame.height)
          .offset(x: frame.minX, y: frame.minY)
          .allowsHitTesting(false)

        thirdsGuides(in: frame)

        // The interior drags the whole rectangle.
        Color.clear
          .contentShape(Rectangle())
          .frame(width: frame.width, height: frame.height)
          .offset(x: frame.minX, y: frame.minY)
          .gesture(drag(for: .interior, scale: scale))

        ForEach(Array(handles.enumerated()), id: \.offset) { _, handle in
          handleView(handle, in: frame, scale: scale)
        }

        readout(in: frame)
      }
    }
  }

  private var handles: [CropHandle] {
    [.topLeft, .top, .topRight, .left, .right, .bottomLeft, .bottom, .bottomRight]
  }

  @ViewBuilder
  private func thirdsGuides(in frame: CGRect) -> some View {
    Path { path in
      for step in 1...2 {
        let x = frame.minX + frame.width * CGFloat(step) / 3
        let y = frame.minY + frame.height * CGFloat(step) / 3
        path.move(to: CGPoint(x: x, y: frame.minY))
        path.addLine(to: CGPoint(x: x, y: frame.maxY))
        path.move(to: CGPoint(x: frame.minX, y: y))
        path.addLine(to: CGPoint(x: frame.maxX, y: y))
      }
    }
    .stroke(.white.opacity(0.35), lineWidth: 1)
    .allowsHitTesting(false)
  }

  private func handleView(_ handle: CropHandle, in frame: CGRect, scale: CGFloat) -> some View {
    let point = position(of: handle, in: frame)
    return RoundedRectangle(cornerRadius: 3)
      .fill(.white)
      .frame(width: handleDrawSize, height: handleDrawSize)
      .shadow(radius: 2)
      .frame(width: handleTouchSize, height: handleTouchSize)
      .contentShape(Rectangle())
      .position(x: point.x, y: point.y)
      .gesture(drag(for: handle, scale: scale))
      .accessibilityLabel(accessibilityName(handle))
      .accessibilityIdentifier("Crop \(accessibilityName(handle))")
  }

  private func accessibilityName(_ handle: CropHandle) -> String {
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

  private func position(of handle: CropHandle, in frame: CGRect) -> CGPoint {
    let x: CGFloat =
      handle.movesLeftEdge ? frame.minX : handle.movesRightEdge ? frame.maxX : frame.midX
    let y: CGFloat =
      handle.movesTopEdge ? frame.minY : handle.movesBottomEdge ? frame.maxY : frame.midY
    return CGPoint(x: x, y: y)
  }

  private func drag(for handle: CropHandle, scale: CGFloat) -> some Gesture {
    DragGesture(minimumDistance: 0)
      .onChanged { value in
        let start = dragStart ?? rect
        if dragStart == nil { dragStart = rect }
        // Screen points back to canvas pixels: the rectangle is stored in the
        // document's own units so the readout and the applied crop agree.
        let translation = CGSize(
          width: value.translation.width / scale,
          height: value.translation.height / scale)
        rect = CropGeometry.resized(
          start, handle: handle, translation: translation, canvas: canvas, aspect: aspect)
      }
      .onEnded { _ in dragStart = nil }
  }

  /// The size the crop will produce, in pixels, while it is being chosen. This
  /// is what makes "a custom canvas size" a deliberate choice rather than a
  /// guess.
  private func readout(in frame: CGRect) -> some View {
    Text("\(Int(rect.width)) × \(Int(rect.height))")
      .font(.caption.monospacedDigit().weight(.semibold))
      .padding(.horizontal, 10)
      .padding(.vertical, 6)
      .background(.black.opacity(0.7), in: Capsule())
      .foregroundStyle(.white)
      .position(x: frame.midX, y: max(frame.minY - 22, 22))
      .allowsHitTesting(false)
      .accessibilityIdentifier("Crop size")
      .accessibilityLabel("Crop size \(Int(rect.width)) by \(Int(rect.height))")
  }

  /// Fit the canvas into the available space the same way the editor does, so
  /// the rectangle sits over the pixels it is actually cropping.
  private func fittedScale(in size: CGSize) -> CGFloat {
    guard canvas.width > 0, canvas.height > 0 else { return 1 }
    return min(size.width / canvas.width, size.height / canvas.height)
  }

  private func fittedOrigin(in size: CGSize, scale: CGFloat) -> CGPoint {
    CGPoint(
      x: (size.width - canvas.width * scale) / 2,
      y: (size.height - canvas.height * scale) / 2)
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

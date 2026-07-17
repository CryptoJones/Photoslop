// SPDX-License-Identifier: Apache-2.0
import PencilKit
import SwiftUI
import UIKit

struct PencilCanvas: UIViewRepresentable {
  let backgroundImage: UIImage
  let canvasSize: CGSize
  let drawing: PKDrawing
  let inkColor: UIColor
  let inkWidth: CGFloat
  let isEraser: Bool
  let drawsWithFinger: Bool
  let drawingOpacity: Double
  let onDrawingChanged: (PKDrawing) -> Void

  func makeCoordinator() -> Coordinator { Coordinator(self) }

  func makeUIView(context: Context) -> CanvasHostView {
    let view = CanvasHostView()
    configure(view)
    view.canvasView.delegate = context.coordinator
    return view
  }

  func updateUIView(_ view: CanvasHostView, context: Context) {
    context.coordinator.parent = self
    configure(view)
  }

  private func configure(_ host: CanvasHostView) {
    host.updateCanvasSize(canvasSize)
    host.imageView.image = backgroundImage
    host.canvasView.tool =
      isEraser
      ? PKEraserTool(.bitmap)
      : PKInkingTool(.pen, color: inkColor, width: inkWidth)
    host.canvasView.drawingPolicy = drawsWithFinger ? .anyInput : .pencilOnly
    host.canvasView.alpha = drawingOpacity
    host.scrollView.panGestureRecognizer.minimumNumberOfTouches = drawsWithFinger ? 2 : 1
    if host.canvasView.drawing.dataRepresentation() != drawing.dataRepresentation() {
      let delegate = host.canvasView.delegate
      host.canvasView.delegate = nil
      host.canvasView.drawing = drawing
      host.canvasView.delegate = delegate
    }
    host.makeDrawingSurfaceTransparent()
  }

  final class Coordinator: NSObject, PKCanvasViewDelegate {
    var parent: PencilCanvas

    init(_ parent: PencilCanvas) { self.parent = parent }

    func canvasViewDrawingDidChange(_ canvasView: PKCanvasView) {
      parent.onDrawingChanged(canvasView.drawing)
    }
  }
}

final class CanvasHostView: UIView, UIScrollViewDelegate {
  let scrollView = UIScrollView()
  let contentView = UIView()
  let imageView = UIImageView()
  let canvasView = PKCanvasView()
  private var canvasSize = CGSize.zero
  private var fitted = false

  override init(frame: CGRect) {
    super.init(frame: frame)
    backgroundColor = UIColor.secondarySystemBackground
    scrollView.delegate = self
    scrollView.minimumZoomScale = 0.05
    scrollView.maximumZoomScale = 16
    scrollView.bouncesZoom = true
    scrollView.alwaysBounceVertical = true
    scrollView.alwaysBounceHorizontal = true
    scrollView.keyboardDismissMode = .onDrag

    imageView.contentMode = .scaleToFill
    imageView.backgroundColor = .white
    imageView.isUserInteractionEnabled = false
    canvasView.backgroundColor = .clear
    canvasView.isOpaque = false
    canvasView.layer.backgroundColor = UIColor.clear.cgColor
    canvasView.isScrollEnabled = false

    addSubview(scrollView)
    scrollView.addSubview(contentView)
    contentView.addSubview(imageView)
    contentView.addSubview(canvasView)
  }

  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func layoutSubviews() {
    super.layoutSubviews()
    scrollView.frame = bounds
    guard canvasSize.width > 0, canvasSize.height > 0 else { return }
    if !fitted {
      let fit = min(bounds.width / canvasSize.width, bounds.height / canvasSize.height)
      scrollView.minimumZoomScale = min(1, max(0.05, fit * 0.25))
      scrollView.zoomScale = min(1, max(0.05, fit))
      fitted = true
    }
    centerCanvas()
  }

  func updateCanvasSize(_ size: CGSize) {
    guard size != canvasSize else { return }
    canvasSize = size
    let frame = CGRect(origin: .zero, size: size)
    contentView.frame = frame
    imageView.frame = frame
    canvasView.frame = frame
    canvasView.contentSize = size
    scrollView.contentSize = size
    fitted = false
    setNeedsLayout()
  }

  func viewForZooming(in scrollView: UIScrollView) -> UIView? { contentView }

  func makeDrawingSurfaceTransparent() {
    makeTransparent(canvasView)
  }

  func scrollViewDidZoom(_ scrollView: UIScrollView) { centerCanvas() }

  private func centerCanvas() {
    let scaledWidth = canvasSize.width * scrollView.zoomScale
    let scaledHeight = canvasSize.height * scrollView.zoomScale
    let horizontal = max(0, (scrollView.bounds.width - scaledWidth) / 2)
    let vertical = max(0, (scrollView.bounds.height - scaledHeight) / 2)
    scrollView.contentInset = UIEdgeInsets(
      top: vertical, left: horizontal, bottom: vertical, right: horizontal
    )
  }

  private func makeTransparent(_ view: UIView) {
    view.backgroundColor = .clear
    view.isOpaque = false
    view.layer.backgroundColor = UIColor.clear.cgColor
    for subview in view.subviews { makeTransparent(subview) }
  }
}

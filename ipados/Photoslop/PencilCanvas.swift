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
  let tool: BrushTool
  let drawsWithFinger: Bool
  let drawingOpacity: Double
  /// When set, a tap reports where in canvas pixels it landed instead of
  /// drawing, so text can be placed at the spot the user pointed at.
  var onCanvasTapped: ((CGPoint) -> Void)?
  /// When set, dragging reports the position in canvas pixels so a text layer
  /// can be moved. `isFinal` marks the end of the gesture, which is where the
  /// undo entry belongs — one per drag rather than one per touch sample.
  var onCanvasDragged: ((CGPoint, Bool) -> Void)?
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
    host.canvasView.tool = tool.pkTool(color: inkColor, width: inkWidth)
    host.canvasView.drawingPolicy = drawsWithFinger ? .anyInput : .pencilOnly
    host.canvasView.alpha = drawingOpacity
    host.canvasView.isAccessibilityElement = true
    host.canvasView.accessibilityLabel = "Editable image canvas"
    host.canvasView.accessibilityValue = (
      "\(Int(canvasSize.width)) by \(Int(canvasSize.height)) pixels, "
        + "\(tool.displayName.lowercased()), "
        + "\(Int((drawingOpacity * 100).rounded())) percent layer opacity"
    )
    host.canvasView.accessibilityHint = (
      "Draw with \(drawsWithFinger ? "Apple Pencil or one finger" : "Apple Pencil"). "
        + "Use two fingers to pan or pinch to zoom. Layer controls and Undo are outside the canvas."
    )
    host.canvasView.accessibilityTraits.insert(.allowsDirectInteraction)
    // Placement has to win over PencilKit's own touch handling, so drawing is
    // suspended for as long as a tap is what the user means.
    host.onCanvasTapped = onCanvasTapped
    host.onCanvasDragged = onCanvasDragged
    // Placement and moving both need the touch before PencilKit gets it.
    host.canvasView.isUserInteractionEnabled = onCanvasTapped == nil && onCanvasDragged == nil
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
  var onCanvasTapped: ((CGPoint) -> Void)?
  var onCanvasDragged: ((CGPoint, Bool) -> Void)?

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
    imageView.isAccessibilityElement = false
    canvasView.backgroundColor = .clear
    canvasView.isOpaque = false
    canvasView.layer.backgroundColor = UIColor.clear.cgColor
    // PencilKit treats ink as a light-mode value and swaps it for display when
    // the canvas is in dark mode, so black ink paints white and white ink
    // paints black while mid-tones like purple pass through unchanged. The
    // canvas here sits over the user's own artwork rather than a themed
    // background, so pin it to light and let the chosen color be literal.
    canvasView.overrideUserInterfaceStyle = .light
    canvasView.isScrollEnabled = false
    scrollView.accessibilityLabel = "Zoomable document canvas"
    scrollView.accessibilityHint = "Pinch to zoom and swipe to pan"

    addSubview(scrollView)
    scrollView.addSubview(contentView)
    contentView.addSubview(imageView)
    contentView.addSubview(canvasView)

    let tap = UITapGestureRecognizer(target: self, action: #selector(handlePlacementTap))
    contentView.addGestureRecognizer(tap)

    let drag = UIPanGestureRecognizer(target: self, action: #selector(handleMoveDrag))
    drag.maximumNumberOfTouches = 1
    contentView.addGestureRecognizer(drag)
  }

  @objc private func handleMoveDrag(_ recognizer: UIPanGestureRecognizer) {
    guard let onCanvasDragged else { return }
    switch recognizer.state {
    case .changed:
      onCanvasDragged(clamped(recognizer.location(in: contentView)), false)
    case .ended:
      onCanvasDragged(clamped(recognizer.location(in: contentView)), true)
    default:
      break
    }
  }

  /// Keep a drag that leaves the canvas from parking text off the edge.
  private func clamped(_ point: CGPoint) -> CGPoint {
    CGPoint(
      x: min(max(0, point.x), canvasSize.width),
      y: min(max(0, point.y), canvasSize.height)
    )
  }

  /// Reports the tap in canvas pixels. contentView is sized to the canvas and
  /// scaled by the scroll view's zoom, so a location in its coordinate space is
  /// already the pixel the user pointed at, whatever the zoom.
  @objc private func handlePlacementTap(_ recognizer: UITapGestureRecognizer) {
    guard let onCanvasTapped else { return }
    let point = recognizer.location(in: contentView)
    guard point.x >= 0, point.y >= 0,
      point.x <= canvasSize.width, point.y <= canvasSize.height
    else { return }
    onCanvasTapped(point)
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

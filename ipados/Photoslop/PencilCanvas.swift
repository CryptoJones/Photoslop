// SPDX-License-Identifier: Apache-2.0
import PencilKit
import SwiftUI
import UIKit

/// The canvas, and anything drawn on top of it.
///
/// `Overlay` is hosted **inside** the scroll view's content rather than floated
/// above it, which is the whole point: `contentView`'s coordinate space is the
/// document's own pixels, so an overlay placed there needs no conversion, zooms
/// and pans with the picture for free, and — because the touches land inside
/// the scroll view — leaves pinch and pan working while a mode is up.
///
/// The overlay used to sit above the canvas in screen points, told where the
/// canvas was by `onCanvasRectChanged`. That split coordinate space produced
/// three bugs in a fortnight: the crop took a region nobody chose (#260), a
/// second crop divided the new canvas by the old rectangle (#268), and
/// suspending drawing meant switching off hit-testing for the whole scroll
/// view, which took pinch and zoom with it (#270). All three were the same
/// mistake, so the fix is to stop making it rather than to patch the arithmetic.
struct PencilCanvas<Overlay: View>: UIViewRepresentable {
  let backgroundImage: UIImage
  let canvasSize: CGSize
  let drawing: PKDrawing
  let inkColor: UIColor
  let inkWidth: CGFloat
  let tool: BrushTool
  let drawsWithFinger: Bool
  let drawingOpacity: Double
  /// When set, dragging reports the position in canvas pixels so a text layer
  /// can be moved. `isFinal` marks the end of the gesture, which is where the
  /// undo entry belongs — one per drag rather than one per touch sample.
  var onCanvasDragged: ((CGPoint, Bool) -> Void)?
  /// The zoom scale, so an overlay can keep its chrome a constant size on
  /// screen. Everything an overlay *draws about the document* — the rectangle,
  /// its position — is in document pixels and scales correctly on its own; the
  /// things it draws *for the finger*, like handles and labels, must not.
  var onZoomScaleChanged: ((CGFloat) -> Void)?
  /// True while an overlay owns the canvas. Drawing is suspended — a drag
  /// positions the overlay rather than painting under it — but scrolling,
  /// pinching and zooming are emphatically not.
  var overlayIsActive = false
  let onDrawingChanged: (PKDrawing) -> Void
  /// Drawn inside the scrolling content, in document pixels.
  @ViewBuilder var overlay: () -> Overlay

  func makeCoordinator() -> Coordinator { Coordinator(self) }

  func makeUIView(context: Context) -> CanvasHostView {
    let view = CanvasHostView()
    view.mount(context.coordinator.overlayHost)
    configure(view)
    view.canvasView.delegate = context.coordinator
    return view
  }

  func updateUIView(_ view: CanvasHostView, context: Context) {
    view.onZoomScaleChanged = onZoomScaleChanged
    context.coordinator.parent = self
    context.coordinator.overlayHost.rootView = AnyView(overlay())
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
    host.onCanvasDragged = onCanvasDragged
    let isMoving = onCanvasDragged != nil
    // Moving needs the touch before PencilKit gets it, or the drag paints.
    // An overlay needs the same, for the same reason.
    host.canvasView.isUserInteractionEnabled = !isMoving && !overlayIsActive
    host.setOverlayActive(overlayIsActive)
    // With one-finger panning left on, the scroll view and the move gesture
    // both claim the same drag: the canvas scrolls while the text moves, so the
    // text lurches away from the finger in steps instead of following it. Give
    // the drag to the text while moving and hand panning back afterwards.
    host.scrollView.panGestureRecognizer.isEnabled = !isMoving
    // While an overlay is up, one finger belongs to it — dragging a handle —
    // and two fingers pan, the way two fingers already pan while drawing. The
    // pinch recogniser is untouched throughout, which is what makes zooming
    // work during a crop (#270).
    host.scrollView.panGestureRecognizer.minimumNumberOfTouches =
      (drawsWithFinger || overlayIsActive) ? 2 : 1
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
    /// Retains the overlay's hosting controller. Its view lives in the scroll
    /// view's content, so the overlay is laid out in document pixels.
    let overlayHost = UIHostingController<AnyView>(rootView: AnyView(EmptyView()))

    init(_ parent: PencilCanvas) {
      self.parent = parent
      super.init()
      overlayHost.view.backgroundColor = .clear
      overlayHost.view.isOpaque = false
    }

    func canvasViewDrawingDidChange(_ canvasView: PKCanvasView) {
      parent.onDrawingChanged(canvasView.drawing)
    }
  }
}

final class CanvasHostView: UIView, UIScrollViewDelegate {
  let scrollView = UIScrollView()
  var onZoomScaleChanged: ((CGFloat) -> Void)?
  private var lastReportedZoomScale: CGFloat = 0
  let contentView = UIView()
  /// Holds the SwiftUI overlay, in document pixels, above the artwork.
  private let overlayContainer = UIView()
  /// The overlay's hosting controller, until an owning controller can adopt it.
  private var pendingOverlayController: UIViewController?
  let imageView = UIImageView()
  let canvasView = PKCanvasView()
  private var canvasSize = CGSize.zero
  private var fitted = false
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
    overlayContainer.backgroundColor = .clear
    // Off until a mode is up, so an inert overlay cannot swallow a stroke.
    overlayContainer.isUserInteractionEnabled = false
    contentView.addSubview(overlayContainer)

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

  /// Put the overlay's hosting controller into the scrolling content.
  ///
  /// The **controller** is parented, not merely its view. Adding a hosting
  /// controller's view to a hierarchy while leaving the controller out of the
  /// view-controller hierarchy is unsupported, and what it costs is gesture
  /// delivery: an orphaned hosting controller never joins the responder chain,
  /// so on iOS 18 a drag inside the overlay was recognised as a press and then
  /// went nowhere — the crop handles could be touched and would not move. It
  /// happened to work on iOS 26, which is why five local runs passed while CI,
  /// on 18.5, failed every time.
  func mount(_ controller: UIViewController) {
    controller.view.backgroundColor = .clear
    controller.view.frame = overlayContainer.bounds
    controller.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    overlayContainer.addSubview(controller.view)
    pendingOverlayController = controller
    adoptOverlayController()
  }

  /// Adopt the overlay controller once this view is in a window and an owning
  /// controller exists to adopt it. `mount` runs from `makeUIView`, before the
  /// view has a window, so the parent is not reachable yet.
  private func adoptOverlayController() {
    guard let controller = pendingOverlayController,
      controller.parent == nil,
      let owner = owningViewController
    else { return }
    owner.addChild(controller)
    controller.didMove(toParent: owner)
    pendingOverlayController = nil
  }

  private var owningViewController: UIViewController? {
    var responder: UIResponder? = next
    while let current = responder {
      if let controller = current as? UIViewController { return controller }
      responder = current.next
    }
    return nil
  }

  override func didMoveToWindow() {
    super.didMoveToWindow()
    adoptOverlayController()
  }

  func setOverlayActive(_ active: Bool) {
    overlayContainer.isUserInteractionEnabled = active
    // A scroll view holds a touch back to decide whether it is a scroll, and
    // will cancel it outright once it decides yes. That is right for a list and
    // wrong for a handle: a slow, careful drag — which is how anyone sizes a
    // crop by eye — was being taken away from the box mid-gesture and given to
    // the scroll view, so the rectangle simply did not move.
    //
    // The overlay only became vulnerable to this when it moved inside the
    // scroll view (DD-012). The delay is lifted while a box is up and restored
    // afterwards, so ordinary scrolling still feels ordinary.
    //
    // `canCancelContentTouches` is deliberately left alone. Switching it off as
    // well does stop the scroll view stealing the drag — and also stops it
    // starting a pinch, because the first finger's touch is then owned outright
    // by the box and the second finger never gets to begin a zoom. That trade
    // is exactly backwards: zooming while cropping is the feature this release
    // exists for (#270). Cancellation is not the problem here anyway, since
    // panning needs two fingers while a box is up.
    scrollView.delaysContentTouches = !active
  }

  func updateCanvasSize(_ size: CGSize) {
    guard size != canvasSize else { return }
    canvasSize = size
    let frame = CGRect(origin: .zero, size: size)
    contentView.frame = frame
    imageView.frame = frame
    canvasView.frame = frame
    // The overlay is exactly the document, so its bounds *are* canvas pixels.
    overlayContainer.frame = frame
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
    reportZoomScale()
  }

  /// Publish the zoom scale so an overlay can counter-scale its handles.
  ///
  /// This is all an overlay now needs from the canvas. It used to be told the
  /// canvas's rectangle on screen, because it lived in screen coordinates and
  /// had to convert; hosted inside the content it is already in the document's
  /// coordinates, and the only thing left that depends on zoom is how big a
  /// handle should be under a fingertip.
  func reportZoomScale() {
    guard canvasSize.width > 0, canvasSize.height > 0 else { return }
    let scale = scrollView.zoomScale
    guard abs(scale - lastReportedZoomScale) > 0.0001 else { return }
    lastReportedZoomScale = scale
    onZoomScaleChanged?(scale)
  }

  func scrollViewDidScroll(_ scrollView: UIScrollView) { reportZoomScale() }

  private func makeTransparent(_ view: UIView) {
    view.backgroundColor = .clear
    view.isOpaque = false
    view.layer.backgroundColor = UIColor.clear.cgColor
    for subview in view.subviews { makeTransparent(subview) }
  }
}

// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import Foundation

/// The shape a crop rectangle is held to.
///
/// `free` is the default because it is what cropping to "a custom canvas size"
/// means. The presets exist because the next thing anyone does after cropping
/// freely is crop for a destination that has a shape.
enum CropAspect: String, CaseIterable, Identifiable {
  case free
  case original
  case square
  case threeTwo
  case fourThree
  case sixteenNine

  var id: String { rawValue }

  var displayName: String {
    switch self {
    case .free: "Free"
    case .original: "Original"
    case .square: "1:1"
    case .threeTwo: "3:2"
    case .fourThree: "4:3"
    case .sixteenNine: "16:9"
    }
  }

  var isLocked: Bool { self != .free }

  /// Width divided by height, or nil when unconstrained.
  ///
  /// `original` depends on the document, so it is the one preset that cannot
  /// answer without being told the canvas.
  func ratio(canvas: CGSize) -> CGFloat? {
    switch self {
    case .free: nil
    case .original: canvas.height > 0 ? canvas.width / canvas.height : nil
    case .square: 1
    case .threeTwo: 3.0 / 2.0
    case .fourThree: 4.0 / 3.0
    case .sixteenNine: 16.0 / 9.0
    }
  }
}

/// Which part of the crop rectangle a drag is moving.
enum CropHandle: CaseIterable {
  case topLeft, top, topRight
  case left, right
  case bottomLeft, bottom, bottomRight
  case interior

  var movesLeftEdge: Bool { [.topLeft, .left, .bottomLeft].contains(self) }
  var movesRightEdge: Bool { [.topRight, .right, .bottomRight].contains(self) }
  var movesTopEdge: Bool { [.topLeft, .top, .topRight].contains(self) }
  var movesBottomEdge: Bool { [.bottomLeft, .bottom, .bottomRight].contains(self) }
}

/// Crop rectangle arithmetic, kept out of the view so it can be tested without
/// a running app — the parts that go wrong are clamping and aspect correction,
/// neither of which needs a screen to exercise.
enum CropGeometry {
  /// No crop may produce a canvas smaller than this on either side. A rectangle
  /// dragged to nothing would otherwise be applied as an unopenable document.
  static let minimumSide: CGFloat = 16

  /// Apply `translation` to `rect` through `handle`, clamped to `canvas` and
  /// held to `aspect`.
  static func resized(
    _ rect: CGRect,
    handle: CropHandle,
    translation: CGSize,
    canvas: CGSize,
    aspect: CropAspect
  ) -> CGRect {
    resized(
      rect,
      handle: handle,
      translation: translation,
      bounds: CGRect(origin: .zero, size: canvas),
      ratio: aspect.ratio(canvas: canvas))
  }

  /// The general form, in whatever coordinate space the caller is working in.
  ///
  /// Crop is bounded by the canvas — you cannot keep a region of a picture that
  /// is not in the picture. Placing a layer is not: an imported image may hang
  /// off the edge, which is how you crop *into* a canvas by moving the picture
  /// rather than the frame. Same arithmetic, different bounds, so it is one
  /// implementation with the bounds passed in.
  static func resized(
    _ rect: CGRect,
    handle: CropHandle,
    translation: CGSize,
    bounds: CGRect,
    ratio: CGFloat?
  ) -> CGRect {
    if handle == .interior {
      return moved(rect, by: translation, in: bounds)
    }

    var minX = rect.minX
    var maxX = rect.maxX
    var minY = rect.minY
    var maxY = rect.maxY

    if handle.movesLeftEdge { minX = min(rect.maxX - minimumSide, rect.minX + translation.width) }
    if handle.movesRightEdge { maxX = max(rect.minX + minimumSide, rect.maxX + translation.width) }
    if handle.movesTopEdge { minY = min(rect.maxY - minimumSide, rect.minY + translation.height) }
    if handle.movesBottomEdge {
      maxY = max(rect.minY + minimumSide, rect.maxY + translation.height)
    }

    minX = max(bounds.minX, minX)
    minY = max(bounds.minY, minY)
    maxX = min(bounds.maxX, maxX)
    maxY = min(bounds.maxY, maxY)

    let dragged = CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)
    guard let ratio else { return dragged.integral }
    return corrected(dragged, to: ratio, handle: handle, bounds: bounds).integral
  }

  /// Move the whole rectangle without resizing it, stopping at the canvas edge
  /// rather than sliding part of it outside.
  static func moved(_ rect: CGRect, by translation: CGSize, in bounds: CGRect) -> CGRect {
    let x = min(max(bounds.minX, rect.minX + translation.width), bounds.maxX - rect.width)
    let y = min(max(bounds.minY, rect.minY + translation.height), bounds.maxY - rect.height)
    return CGRect(x: x, y: y, width: rect.width, height: rect.height).integral
  }

  /// Force `rect` to `ratio`, keeping the edges the drag was not moving.
  ///
  /// The anchor matters: correcting a bottom-right drag by moving the top-left
  /// corner would drag the rectangle out from under the finger. So the corner
  /// opposite the handle stays put, and for an edge drag the rectangle grows
  /// about its own centre on the other axis.
  static func corrected(
    _ rect: CGRect, to ratio: CGFloat, handle: CropHandle, canvas: CGSize
  ) -> CGRect {
    corrected(rect, to: ratio, handle: handle, bounds: CGRect(origin: .zero, size: canvas))
  }

  static func corrected(
    _ rect: CGRect, to ratio: CGFloat, handle: CropHandle, bounds: CGRect
  ) -> CGRect {
    var width = rect.width
    var height = rect.height

    // Whichever axis the drag actually moved is the one to trust.
    if handle.movesLeftEdge || handle.movesRightEdge {
      height = width / ratio
    } else if handle.movesTopEdge || handle.movesBottomEdge {
      width = height * ratio
    } else {
      height = width / ratio
    }

    // Shrink to fit rather than overflow the bounds.
    if width > bounds.width {
      width = bounds.width
      height = width / ratio
    }
    if height > bounds.height {
      height = bounds.height
      width = height * ratio
    }
    if width < minimumSide {
      width = minimumSide
      height = width / ratio
    }
    if height < minimumSide {
      height = minimumSide
      width = height * ratio
    }

    let anchorX = handle.movesLeftEdge ? rect.maxX - width : rect.minX
    let anchorY = handle.movesTopEdge ? rect.maxY - height : rect.minY
    let centredX = rect.midX - width / 2
    let centredY = rect.midY - height / 2

    let x = (handle.movesLeftEdge || handle.movesRightEdge) ? anchorX : centredX
    let y = (handle.movesTopEdge || handle.movesBottomEdge) ? anchorY : centredY

    return moved(CGRect(x: x, y: y, width: width, height: height), by: .zero, in: bounds)
  }

  /// Which part of `rect` a touch at `point` has taken hold of.
  ///
  /// The box is dragged from UIKit rather than by a SwiftUI gesture per handle
  /// (see `PencilCanvas.onBoxDrag`), so picking the handle is arithmetic now,
  /// and arithmetic can be tested without a screen. Corners win over edges when
  /// both are in range, because a corner is the more specific intent; the
  /// interior is the fallback, and outside the rectangle nothing is grabbed.
  ///
  /// `tolerance` is the touch radius in the same units as `rect` — document
  /// pixels — so the caller divides its 44pt target by the zoom scale.
  static func handle(at point: CGPoint, in rect: CGRect, tolerance: CGFloat) -> CropHandle? {
    let corners: [(CropHandle, CGPoint)] = [
      (.topLeft, CGPoint(x: rect.minX, y: rect.minY)),
      (.topRight, CGPoint(x: rect.maxX, y: rect.minY)),
      (.bottomLeft, CGPoint(x: rect.minX, y: rect.maxY)),
      (.bottomRight, CGPoint(x: rect.maxX, y: rect.maxY)),
    ]
    let edges: [(CropHandle, CGPoint)] = [
      (.top, CGPoint(x: rect.midX, y: rect.minY)),
      (.bottom, CGPoint(x: rect.midX, y: rect.maxY)),
      (.left, CGPoint(x: rect.minX, y: rect.midY)),
      (.right, CGPoint(x: rect.maxX, y: rect.midY)),
    ]

    func nearest(_ candidates: [(CropHandle, CGPoint)]) -> CropHandle? {
      var best: (handle: CropHandle, distance: CGFloat)?
      for (handle, centre) in candidates {
        let distance = hypot(point.x - centre.x, point.y - centre.y)
        guard distance <= tolerance else { continue }
        if best == nil || distance < best!.distance { best = (handle, distance) }
      }
      return best?.handle
    }

    if let corner = nearest(corners) { return corner }
    if let edge = nearest(edges) { return edge }
    return rect.insetBy(dx: -tolerance / 4, dy: -tolerance / 4).contains(point) ? .interior : nil
  }

  /// The starting rectangle when the crop mode opens: the whole canvas, or the
  /// largest centred rectangle of the locked shape that fits inside it.
  static func initialRect(canvas: CGSize, aspect: CropAspect) -> CGRect {
    let whole = CGRect(origin: .zero, size: canvas)
    guard let ratio = aspect.ratio(canvas: canvas) else { return whole }
    return corrected(whole, to: ratio, handle: .interior, canvas: canvas)
  }
}

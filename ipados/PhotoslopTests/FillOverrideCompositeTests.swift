// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Gaussian Blur and Feather as the composite draws them (#372).
///
/// `FillOverrideParityTests` proves the arithmetic matches the desktop. This
/// covers what the arithmetic is *for*: that the replacement fill actually
/// reaches the canvas, and that where a fill-replacing effect sits in the
/// stack changes the result — which is the reason the stack is walked in
/// order rather than every plane being resolved against one silhouette.
@MainActor
final class FillOverrideCompositeTests: XCTestCase {
  private let canvas = CGSize(width: 60, height: 60)

  private func square(_ rect: CGRect, color: UIColor = .white) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: canvas, format: format).image { context in
      color.setFill()
      context.fill(rect)
    }
  }

  private func layer(_ effects: [LayerEffect]) -> RasterLayer {
    var layer = RasterLayer(
      name: "Square", image: square(CGRect(x: 20, y: 20, width: 20, height: 20)))
    layer.effects = effects
    return layer
  }

  private func blur(_ radius: Double) -> LayerEffect {
    LayerEffect(kind: "gaussian-blur", parameters: ["radius": .number(radius)])!
  }

  private func feather(_ radius: Double) -> LayerEffect {
    LayerEffect(kind: "feather", parameters: ["radius": .number(radius)])!
  }

  private var hardShadow: LayerEffect {
    LayerEffect(
      kind: "drop-shadow",
      parameters: [
        "offset_x": 12, "offset_y": 12, "blur": 0, "spread": 0,
        "color": .rgba(255, 0, 0, 255),
      ])!
  }

  private func alpha(_ image: UIImage, x: Int, y: Int) throws -> Int {
    let word = try XCTUnwrap(PixelBuffer.probe(image: image, x: x, y: y))
    return Int((word >> 24) & 0xFF)
  }

  /// The fill is genuinely replaced: a blurred square must put ink outside the
  /// crisp square's bounds, which an unblurred fill never would.
  func testBlurReplacesTheFillOnTheCanvas() throws {
    let sharp = EditorStore.render(layers: [layer([])], size: canvas)
    let blurred = EditorStore.render(layers: [layer([blur(6)])], size: canvas)
    XCTAssertEqual(try alpha(sharp, x: 17, y: 30), 0, "the sharp square ends at x=20")
    XCTAssertGreaterThan(
      try alpha(blurred, x: 17, y: 30), 0, "the blur should have spread past the edge")
    XCTAssertLessThan(
      try alpha(blurred, x: 30, y: 30), 255, "and softened the middle's own edge region")
  }

  /// Feather may only take opacity away, so unlike a blur it must never put
  /// ink outside the original silhouette.
  func testFeatherDoesNotSpreadOutsideTheLayer() throws {
    let feathered = EditorStore.render(layers: [layer([feather(6)])], size: canvas)
    XCTAssertEqual(try alpha(feathered, x: 17, y: 30), 0, "feather grew the silhouette")
    XCTAssertLessThan(
      try alpha(feathered, x: 21, y: 30), 255, "feather should soften the edge inward")
  }

  /// The ordering claim. A blur *below* a shadow is applied first, so the
  /// shadow is cast by the softened silhouette and its edge is soft too. The
  /// same blur *above* the shadow leaves the shadow crisp and softens only the
  /// artwork. If the walk ignored order these two would be identical.
  func testStackOrderDecidesWhetherTheShadowIsBlurred() throws {
    let blurThenShadow = EditorStore.render(
      layers: [layer([blur(6), hardShadow])], size: canvas)
    let shadowThenBlur = EditorStore.render(
      layers: [layer([hardShadow, blur(6)])], size: canvas)

    // Just outside where the hard shadow's own edge falls (20+12 = 32 .. 52).
    // With the blur first, the shadow's edge is soft and reaches further out.
    let softEdge = try alpha(blurThenShadow, x: 30, y: 55)
    let hardEdge = try alpha(shadowThenBlur, x: 30, y: 55)
    XCTAssertNotEqual(
      softEdge, hardEdge,
      "stack order made no difference — the walk is resolving every plane "
        + "against one silhouette instead of following the stack")
    XCTAssertGreaterThan(softEdge, hardEdge, "the blurred silhouette casts the softer shadow")
  }

  /// A radius of zero is a no-op rather than an error or an empty fill.
  func testZeroRadiusChangesNothing() throws {
    let plain = EditorStore.render(layers: [layer([])], size: canvas)
    let zero = EditorStore.render(layers: [layer([blur(0)])], size: canvas)
    XCTAssertEqual(try alpha(zero, x: 30, y: 30), try alpha(plain, x: 30, y: 30))
    XCTAssertEqual(try alpha(zero, x: 17, y: 30), 0)
  }

  /// The QuickLook preview shares the model but not the loop — it scales, and
  /// rasterises strokes at preview size — so it gets its own assertion. The
  /// canvas is deliberately over `previewMaximumDimension`, because below that
  /// the preview delegates straight to the ordinary compositor and this would
  /// prove nothing about the second loop.
  func testThePreviewAlsoDrawsTheReplacementFill() throws {
    let big = CGSize(width: 1400, height: 700)
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let art = UIGraphicsImageRenderer(size: big, format: format).image { context in
      UIColor.white.setFill()
      context.fill(CGRect(x: 600, y: 300, width: 200, height: 200))
    }

    let store = EditorStore()
    store.newDocument(size: big)
    _ = try store.addImageLayers([(name: "Square", image: art)])
    let id = try XCTUnwrap(store.activeLayerID)
    store.setEffects([blur(8)], for: id)

    let wrapper = try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject))
    let data = try XCTUnwrap(wrapper.fileWrappers?["preview.png"]?.regularFileContents)
    let preview = try XCTUnwrap(UIImage(data: data))
    let scale = preview.size.width / big.width

    // Just outside the crisp square's left edge, in preview coordinates. A
    // preview drawing the unblurred fill would leave this transparent.
    let x = Int((595.0 * scale).rounded())
    let y = Int((400.0 * scale).rounded())
    XCTAssertGreaterThan(
      try alpha(preview, x: x, y: y), 0,
      "the preview drew the unblurred fill — its loop still bypasses the override")
  }
}

// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Effects on raster and photo layers (#372 part 1).
///
/// The model, the archive and the renderer were always layer-agnostic — only
/// the entry point was text-only. What actually had to be decided was memory:
/// a text layer's effect planes are a tight box around its glyphs, while a
/// photo layer's are the whole canvas, which is the jetsam risk #309 and #311
/// were about. These tests pin the measurement and the refusal rather than the
/// button, because the measurement is the part that can quietly go wrong.
@MainActor
final class RasterEffectsTests: XCTestCase {
  private func shadow() -> LayerEffect {
    LayerEffect(kind: "drop-shadow", parameters: ["blur": 4])!
  }

  private func blur() -> LayerEffect {
    LayerEffect(kind: "gaussian-blur", parameters: ["radius": 5])!
  }

  func testAnEmptyStackCostsNothing() {
    XCTAssertEqual(AppearanceRenderer.transientLayers(for: []), 0)
    // A kind the renderer does not draw is carried in the document but costs
    // no buffers, so it must not inflate the budget either.
    let unknown = LayerEffect(kind: "satin", parameters: [:])
    XCTAssertEqual(AppearanceRenderer.transientLayers(for: unknown.map { [$0] } ?? []), 0)
  }

  func testDisabledEffectsAreNotCharged() {
    var off = shadow()
    off.enabled = false
    XCTAssertEqual(AppearanceRenderer.transientLayers(for: [off]), 0)
  }

  /// Each plane's colour buffer is held until the whole stack has been drawn,
  /// so a longer stack genuinely costs more and the estimate must say so.
  func testCostGrowsWithTheNumberOfPlanes() {
    let one = AppearanceRenderer.transientLayers(for: [shadow()])
    let three = AppearanceRenderer.transientLayers(for: [shadow(), shadow(), shadow()])
    XCTAssertGreaterThan(one, 0)
    XCTAssertEqual(three, one + 2)
  }

  /// A fill-replacing effect pads the layer and blurs it, which is more than a
  /// plane costs — the estimate has to charge for that separately.
  func testAFillOverrideCostsMoreThanAPlane() {
    XCTAssertGreaterThan(
      AppearanceRenderer.transientLayers(for: [blur()]),
      AppearanceRenderer.transientLayers(for: [shadow()]))
  }

  /// A stack on an ordinary document fits, and the store agrees.
  func testAnOrdinaryStackIsAffordable() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 1024, height: 768))
    var layer = try! XCTUnwrap(store.activeLayer)
    layer.effects = [shadow()]
    XCTAssertTrue(store.canAffordEffects(for: layer))
  }

  /// Effects belong to the layer, not to its type: a raster layer carries and
  /// renders them exactly as a text layer does. This is the whole of part 1
  /// once the memory question is answered.
  func testARasterLayerRendersItsEffects() throws {
    let canvas = CGSize(width: 60, height: 60)
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let art = UIGraphicsImageRenderer(size: canvas, format: format).image { context in
      UIColor.white.setFill()
      context.fill(CGRect(x: 20, y: 20, width: 20, height: 20))
    }
    var layer = RasterLayer(name: "Photo", image: art)
    XCTAssertFalse(layer.isText, "this test is about a layer that is not text")
    layer.effects = [
      LayerEffect(
        kind: "drop-shadow",
        parameters: [
          "offset_x": 8, "offset_y": 8, "blur": 0, "spread": 0,
          "color": .rgba(255, 0, 0, 255),
        ])!
    ]
    XCTAssertTrue(layer.hasRenderableEffects)

    let rendered = EditorStore.render(layers: [layer], size: canvas)
    let word = try XCTUnwrap(PixelBuffer.probe(image: rendered, x: 45, y: 45))
    XCTAssertGreaterThan((word >> 24) & 0xFF, 0, "the shadow did not draw on a raster layer")
  }

  /// The store's own setter is the same one the sheet commits through, so a
  /// raster layer must accept a stack and keep it.
  func testSetEffectsWorksOnARasterLayer() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 40, height: 40))
    let id = try XCTUnwrap(store.activeLayerID)
    XCTAssertFalse(store.activeLayer?.isText ?? true)
    store.setEffects([shadow()], for: id)
    XCTAssertEqual(store.layers.first(where: { $0.id == id })?.effects.count, 1)
  }
}

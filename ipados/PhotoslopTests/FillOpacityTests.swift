// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Fill opacity (#372): the desktop's `Layer.fill_opacity`, which fades a
/// layer's own pixels and leaves its effects at full strength.
///
/// The distinction from plain layer opacity is the whole feature. `opacity`
/// fades artwork and shadow together; `fillOpacity` fades only the artwork,
/// which is what makes a shadow-only or knockout layer possible. Every test
/// here is written so that it would fail if the two were wired to the same
/// alpha.
@MainActor
final class FillOpacityTests: XCTestCase {
  private let canvas = CGSize(width: 80, height: 60)
  private let square = CGRect(x: 20, y: 20, width: 10, height: 10)

  private func squareImage(color: UIColor = .blue) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: canvas, format: format).image { context in
      color.setFill()
      context.fill(square)
    }
  }

  /// A hard red shadow ten pixels down and right: no blur, no spread, so the
  /// shadow's pixels are the square's alpha moved, in one colour.
  private var hardRedShadow: LayerEffect {
    LayerEffect(
      kind: "drop-shadow",
      parameters: [
        "offset_x": 10, "offset_y": 10, "blur": 0, "spread": 0,
        "color": .rgba(255, 0, 0, 255),
      ])!
  }

  private func alpha(_ image: UIImage, x: Int, y: Int) throws -> Int {
    let word = try XCTUnwrap(PixelBuffer.probe(image: image, x: x, y: y))
    return Int((word >> 24) & 0xFF)
  }

  private func layer(fillOpacity: Double, opacity: Double = 1, effects: [LayerEffect] = [])
    -> RasterLayer
  {
    var layer = RasterLayer(name: "Square", image: squareImage())
    layer.opacity = opacity
    layer.fillOpacity = fillOpacity
    layer.effects = effects
    return layer
  }

  /// The defining property: the artwork fades, the shadow does not.
  func testFillOpacityFadesTheFillAndNotTheEffect() throws {
    let full = EditorStore.render(
      layers: [layer(fillOpacity: 1, effects: [hardRedShadow])], size: canvas)
    let faded = EditorStore.render(
      layers: [layer(fillOpacity: 0.25, effects: [hardRedShadow])], size: canvas)

    // Inside the square: the fill is a quarter as opaque as it was.
    let fullFill = try alpha(full, x: 22, y: 22)
    let fadedFill = try alpha(faded, x: 22, y: 22)
    XCTAssertEqual(fullFill, 255, "the square should start opaque")
    XCTAssertLessThan(fadedFill, fullFill, "fill opacity did not fade the fill")
    XCTAssertEqual(Double(fadedFill), 255 * 0.25, accuracy: 8)

    // In the shadow, clear of the square: untouched.
    XCTAssertEqual(
      try alpha(faded, x: 35, y: 35), try alpha(full, x: 35, y: 35),
      "fill opacity must not fade the effect — that is what layer opacity is for")
  }

  /// Layer opacity remains the one that fades both, so the two controls stay
  /// distinguishable rather than becoming two names for one thing.
  func testLayerOpacityStillFadesTheEffectToo() throws {
    let full = EditorStore.render(
      layers: [layer(fillOpacity: 1, effects: [hardRedShadow])], size: canvas)
    let faded = EditorStore.render(
      layers: [layer(fillOpacity: 1, opacity: 0.25, effects: [hardRedShadow])], size: canvas)
    XCTAssertLessThan(
      try alpha(faded, x: 35, y: 35), try alpha(full, x: 35, y: 35),
      "layer opacity should fade the shadow as well as the fill")
  }

  /// Zero fill with an effect is the point of the feature: the shadow survives
  /// its own subject.
  func testZeroFillLeavesAnEffectOnlyLayer() throws {
    let rendered = EditorStore.render(
      layers: [layer(fillOpacity: 0, effects: [hardRedShadow])], size: canvas)
    XCTAssertEqual(try alpha(rendered, x: 22, y: 22), 0, "the artwork should be gone")
    XCTAssertGreaterThan(try alpha(rendered, x: 35, y: 35), 0, "the shadow should remain")
  }

  /// The two multiply rather than one replacing the other.
  func testFillAlphaCombinesBothOpacities() {
    XCTAssertEqual(layer(fillOpacity: 0.5, opacity: 0.5).fillAlpha, 0.25, accuracy: 0.0001)
    XCTAssertEqual(layer(fillOpacity: 1, opacity: 1).fillAlpha, 1, accuracy: 0.0001)
  }

  func testSetFillOpacityClampsAndIsUndoable() {
    let store = EditorStore()
    store.newDocument(size: canvas)
    let id = try! XCTUnwrap(store.activeLayerID)

    store.setFillOpacity(0.4, for: id)
    XCTAssertEqual(store.layers.first(where: { $0.id == id })?.fillOpacity, 0.4)

    store.setFillOpacity(9, for: id)
    XCTAssertEqual(store.layers.first(where: { $0.id == id })?.fillOpacity, 1, "clamps high")
    store.setFillOpacity(-3, for: id)
    XCTAssertEqual(store.layers.first(where: { $0.id == id })?.fillOpacity, 0, "clamps low")
  }

  func testFillOpacitySurvivesEncodeAndDecode() throws {
    let store = EditorStore()
    store.newDocument(size: canvas)
    let id = try XCTUnwrap(store.activeLayerID)
    store.setFillOpacity(0.35, for: id)

    let snapshot = try ProjectArchive.snapshot(
      state: EditorState(
        layers: store.layers, activeLayerID: store.activeLayerID,
        canvasSize: store.canvasSize))
    let decoded = try ProjectArchive.decode(try ProjectArchive.encode(snapshot))
    XCTAssertEqual(decoded.layers.first?.fillOpacity ?? -1, 0.35, accuracy: 0.0001)
  }

  /// A layer at the default writes no key, so a project with no fill opacity
  /// in it stays byte-comparable to what earlier versions wrote.
  func testTheDefaultWritesNoKey() throws {
    let store = EditorStore()
    store.newDocument(size: canvas)
    let snapshot = try ProjectArchive.snapshot(
      state: EditorState(
        layers: store.layers, activeLayerID: store.activeLayerID,
        canvasSize: store.canvasSize))
    XCTAssertTrue(snapshot.manifest.layers.allSatisfy { $0.fillOpacity == nil })
  }

  /// The dangerous case. A document written before fill opacity existed has no
  /// key, and a missing Double must read as 1 (fully painted) — decoding it as
  /// zero would silently erase the artwork of every layer in every older
  /// project the moment it was opened.
  func testADocumentWithoutTheKeyOpensFullyPainted() throws {
    let store = EditorStore()
    store.newDocument(size: canvas)
    let id = try XCTUnwrap(store.activeLayerID)
    store.setFillOpacity(0.5, for: id)
    let wrapper = try ProjectArchive.encode(
      try ProjectArchive.snapshot(
        state: EditorState(
          layers: store.layers, activeLayerID: store.activeLayerID,
          canvasSize: store.canvasSize)))

    let root = try XCTUnwrap(wrapper.fileWrappers)
    let manifestData = try XCTUnwrap(root["manifest.json"]?.regularFileContents)
    var json = try XCTUnwrap(
      JSONSerialization.jsonObject(with: manifestData) as? [String: Any])
    if var layers = json["layers"] as? [[String: Any]] {
      for index in layers.indices { layers[index].removeValue(forKey: "fillOpacity") }
      json["layers"] = layers
    }
    var children = root
    children["manifest.json"] = FileWrapper(
      regularFileWithContents: try JSONSerialization.data(withJSONObject: json))

    let decoded = try ProjectArchive.decode(
      FileWrapper(directoryWithFileWrappers: children))
    XCTAssertTrue(
      decoded.layers.allSatisfy { $0.fillOpacity == 1 },
      "a document predating fill opacity must open fully painted, not blank")
  }
}

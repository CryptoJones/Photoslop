// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Effects as the editor carries them (#316): data on the layer, drawn live
/// by the one composite the canvas, Flatten and Export share, never baked
/// into the layer's pixels, saved in the project as the desktop's JSON, and
/// applied as a single undo step.
@MainActor
final class LayerEffectsTests: XCTestCase {
  /// A canvas-sized image with one opaque square, so where a shadow lands is
  /// arithmetic rather than font metrics.
  private func square(
    canvas: CGSize, at rect: CGRect, color: UIColor = .blue
  ) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: canvas, format: format).image { context in
      color.setFill()
      context.fill(rect)
    }
  }

  /// A hard red shadow ten pixels down and right: no blur, no spread, so its
  /// pixels are exactly the square's alpha moved, in one colour.
  private var hardRedShadow: LayerEffect {
    LayerEffect(
      kind: "drop-shadow",
      parameters: [
        "offset_x": 10, "offset_y": 10, "blur": 0, "spread": 0,
        "color": .rgba(255, 0, 0, 255),
      ])!
  }

  private func word(_ image: UIImage, x: Int, y: Int) throws -> UInt32 {
    try XCTUnwrap(PixelBuffer(image: image)).word(x: x, y: y)
  }

  private func storeWithSquare() throws -> (EditorStore, UUID) {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 80, height: 60))
    _ = try store.addImageLayers([
      (
        name: "Square",
        image: square(
          canvas: CGSize(width: 80, height: 60), at: CGRect(x: 20, y: 20, width: 10, height: 10))
      )
    ])
    return (store, try XCTUnwrap(store.activeLayerID))
  }

  // MARK: Compositing

  func testCompositeDrawsShadowUnderTheLayerWithoutTouchingItsPixels() throws {
    let (store, id) = try storeWithSquare()
    let before = try XCTUnwrap(store.layers.last).image

    XCTAssertTrue(store.setEffects([hardRedShadow], for: id))

    let layer = try XCTUnwrap(store.layers.last)
    XCTAssertTrue(layer.image === before, "an effect never bakes into the layer")
    XCTAssertTrue(layer.hasRenderableEffects)
    let composite = EditorStore.render(layers: store.layers, size: store.canvasSize)
    // The square itself, still on top; the shadow, where only it lands; and
    // the white background where neither reaches.
    XCTAssertEqual(try word(composite, x: 25, y: 25), 0xFF00_00FF)
    XCTAssertEqual(try word(composite, x: 35, y: 35), 0xFFFF_0000)
    XCTAssertEqual(try word(composite, x: 5, y: 5), 0xFFFF_FFFF)
    XCTAssertEqual(try word(composite, x: 45, y: 45), 0xFFFF_FFFF)
  }

  func testDisabledEffectDrawsNothing() throws {
    let (store, id) = try storeWithSquare()
    var shadow = hardRedShadow
    shadow.enabled = false
    store.setEffects([shadow], for: id)
    XCTAssertFalse(try XCTUnwrap(store.layers.last).hasRenderableEffects)
    let composite = EditorStore.render(layers: store.layers, size: store.canvasSize)
    XCTAssertEqual(try word(composite, x: 35, y: 35), 0xFFFF_FFFF)
  }

  func testLayerOpacityScalesTheEffectToo() throws {
    let (store, id) = try storeWithSquare()
    store.setEffects([hardRedShadow], for: id)
    store.setOpacity(0.5, for: id)
    let composite = EditorStore.render(layers: store.layers, size: store.canvasSize)
    let shadow = try word(composite, x: 35, y: 35)
    // Half red over white: red stays full, green and blue drop by about half.
    XCTAssertEqual((shadow >> 16) & 0xFF, 0xFF)
    XCTAssertEqual(Int((shadow >> 8) & 0xFF), 128, accuracy: 2)
    XCTAssertEqual(Int(shadow & 0xFF), 128, accuracy: 2)
  }

  func testFlattenAndExportIncludeTheEffects() async throws {
    let (store, id) = try storeWithSquare()
    store.setEffects([hardRedShadow], for: id)

    let exportedData = await store.exportPNG()
    let png = try XCTUnwrap(exportedData)
    let exported = try XCTUnwrap(UIImage(data: png))
    XCTAssertEqual(try word(exported, x: 35, y: 35), 0xFFFF_0000)

    store.flattenImage()
    XCTAssertEqual(store.layers.count, 1)
    let flat = try XCTUnwrap(store.layers.first)
    XCTAssertTrue(flat.effects.isEmpty, "a flattened layer's shadow is pixels now")
    XCTAssertEqual(try word(flat.image, x: 35, y: 35), 0xFFFF_0000)
    XCTAssertEqual(try word(flat.image, x: 25, y: 25), 0xFF00_00FF)
  }

  func testTextLayerKeepsItsEffectsThroughEditsAndMoves() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 300, height: 200))
    XCTAssertTrue(
      store.addTextLayer("Shadow", fontSize: 40, color: .black, at: CGPoint(x: 150, y: 100)))
    let id = try XCTUnwrap(store.activeLayerID)
    let stack = try XCTUnwrap(LayerEffect.preset(named: "Sticker"))
    XCTAssertTrue(store.setEffects(stack, for: id))

    XCTAssertTrue(store.updateTextLayer(id, string: "Shadows", fontSize: 44, color: .black))
    XCTAssertEqual(store.layers.last?.effects, stack)
    XCTAssertTrue(store.moveTextLayer(id, to: CGPoint(x: 120, y: 90)))
    XCTAssertEqual(store.layers.last?.effects, stack)

    // Effects follow the re-rendered type: the composite still differs from
    // the plain one, without the layer's own pixels having been touched.
    let with = EditorStore.render(layers: store.layers, size: store.canvasSize)
    store.setEffects([], for: id)
    let without = EditorStore.render(layers: store.layers, size: store.canvasSize)
    XCTAssertNotEqual(
      try XCTUnwrap(PixelBuffer(image: with)).words,
      try XCTUnwrap(PixelBuffer(image: without)).words)
  }

  // MARK: Undo

  func testSetEffectsIsOneUndoStepAndNormalises() throws {
    let (store, id) = try storeWithSquare()
    let undoManager = UndoManager()
    undoManager.groupsByEvent = false
    store.undoManager = undoManager

    var loose = hardRedShadow
    loose.parameters["blur"] = -5
    loose.blendMode = "not-a-mode"
    undoManager.beginUndoGrouping()
    XCTAssertTrue(store.setEffects([loose], for: id))
    undoManager.endUndoGrouping()

    XCTAssertTrue(undoManager.canUndo)
    XCTAssertEqual(undoManager.undoActionName, "Change Effects")
    let stored = try XCTUnwrap(store.layers.last?.effects.first)
    XCTAssertEqual(stored.number("blur"), 0)
    XCTAssertEqual(stored.blendMode, "normal")

    // The same stack again is not an edit.
    XCTAssertFalse(store.setEffects([stored], for: id))
    XCTAssertFalse(store.setEffects([loose], for: id), "unnormalised but equivalent")

    undoManager.undo()
    XCTAssertEqual(store.layers.last?.effects, [])
    XCTAssertFalse(undoManager.canUndo)
    XCTAssertTrue(undoManager.canRedo)
    undoManager.redo()
    XCTAssertEqual(store.layers.last?.effects, [stored])

    XCTAssertFalse(store.setEffects([], for: UUID()), "an unknown layer registers nothing")
  }

  // MARK: Preview

  func testPreviewEffectsShowInTheCompositeWithoutBecomingAnEdit() throws {
    let (store, id) = try storeWithSquare()
    let undoManager = UndoManager()
    undoManager.groupsByEvent = false
    store.undoManager = undoManager

    store.previewEffects = (id, [hardRedShadow])
    XCTAssertEqual(store.layers.last?.effects, [])
    XCTAssertFalse(undoManager.canUndo)

    // What the canvas paints is the composite with the draft substituted; the
    // store's own layers are untouched, and clearing the preview drops it.
    var previewed = store.layers
    previewed[previewed.count - 1].effects = [hardRedShadow]
    let composite = EditorStore.render(layers: previewed, size: store.canvasSize)
    XCTAssertEqual(try word(composite, x: 35, y: 35), 0xFFFF_0000)
    store.previewEffects = nil
    let plain = EditorStore.render(layers: store.layers, size: store.canvasSize)
    XCTAssertEqual(try word(plain, x: 35, y: 35), 0xFFFF_FFFF)
  }

  // MARK: The project archive

  /// Effects survive the archive, and the manifest version is pinned on
  /// purpose: a bump has to be a decision about what older documents do, not
  /// something that happens quietly. Version 4 introduced effects; version 5
  /// added fill opacity (#372), which is why this now reads 5.
  func testProjectRoundTripKeepsEffectsAtTheCurrentVersion() throws {
    let (store, id) = try storeWithSquare()
    var glow = try XCTUnwrap(LayerEffect(kind: "outer-glow", parameters: ["size": 9]))
    glow.opacity = 0.5
    glow.blendMode = "screen"
    glow.extensions = ["future_key": .string("kept")]
    var shadow = hardRedShadow
    shadow.enabled = false
    store.setEffects([glow, shadow], for: id)

    let wrapper = try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject))
    let manifestData = try XCTUnwrap(wrapper.fileWrappers?["manifest.json"]?.regularFileContents)
    let manifest = try JSONDecoder().decode(ProjectManifest.self, from: manifestData)
    XCTAssertEqual(manifest.version, ProjectManifest.currentVersion)
    XCTAssertEqual(
      ProjectManifest.currentVersion, 5,
      """
      the archive format moved — decide what a document written by the previous \
      version does when this one opens it, then update this number
      """)
    XCTAssertNil(manifest.layers[0].effects, "a layer with no effects writes no key")
    XCTAssertEqual(manifest.layers[1].effects?.effects, [glow, shadow])

    // The manifest carries the desktop's shape: `type`, `blend_mode`,
    // `parameters`, `extensions` — what an `.ora`'s `photoslop-effects`
    // attribute holds.
    let raw = try XCTUnwrap(
      JSONSerialization.jsonObject(with: manifestData) as? [String: Any])
    let layers = try XCTUnwrap(raw["layers"] as? [[String: Any]])
    let effects = try XCTUnwrap(layers[1]["effects"] as? [[String: Any]])
    XCTAssertEqual(effects.map { $0["type"] as? String }, ["outer-glow", "drop-shadow"])
    XCTAssertEqual(effects[0]["blend_mode"] as? String, "screen")
    XCTAssertEqual((effects[0]["extensions"] as? [String: Any])?["future_key"] as? String, "kept")
    XCTAssertEqual(effects[0]["schema_version"] as? Int, 1)
    XCTAssertEqual((effects[0]["parameters"] as? [String: Any])?["size"] as? Double, 9)
    XCTAssertEqual(effects[1]["enabled"] as? Bool, false)

    let decoded = try ProjectArchive.decode(wrapper)
    XCTAssertEqual(decoded.layers[0].effects, [])
    XCTAssertEqual(decoded.layers[1].effects, [glow, shadow])
  }

  func testVersionThreeProjectOpensWithNoEffects() throws {
    let (store, id) = try storeWithSquare()
    store.setEffects([hardRedShadow], for: id)
    let wrapper = try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject))
    let manifestData = try XCTUnwrap(wrapper.fileWrappers?["manifest.json"]?.regularFileContents)

    // The same package stamped version 3 — including an `effects` key a
    // version 3 writer could never have produced — decodes as a version 3
    // document: no effects, everything else intact.
    var raw = try XCTUnwrap(JSONSerialization.jsonObject(with: manifestData) as? [String: Any])
    raw["version"] = 3
    let older = FileWrapper(directoryWithFileWrappers: [
      "manifest.json": FileWrapper(
        regularFileWithContents: try JSONSerialization.data(withJSONObject: raw)),
      "layers": try XCTUnwrap(wrapper.fileWrappers?["layers"]),
    ])
    let decoded = try ProjectArchive.decode(older)
    XCTAssertEqual(decoded.layers.count, 2)
    XCTAssertEqual(decoded.layers.map(\.effects), [[], []])
    XCTAssertEqual(decoded.layers[1].name, "Square")

    // And a version 3 manifest without the key at all, as they were written.
    raw["layers"] = (raw["layers"] as? [[String: Any]])?.map { layer in
      var layer = layer
      layer.removeValue(forKey: "effects")
      return layer
    }
    let plain = FileWrapper(directoryWithFileWrappers: [
      "manifest.json": FileWrapper(
        regularFileWithContents: try JSONSerialization.data(withJSONObject: raw)),
      "layers": try XCTUnwrap(wrapper.fileWrappers?["layers"]),
    ])
    XCTAssertEqual(try ProjectArchive.decode(plain).layers.map(\.effects), [[], []])
  }

  func testUnreadableEffectEntriesAreDroppedNotFatal() throws {
    let (store, id) = try storeWithSquare()
    store.setEffects([hardRedShadow], for: id)
    let wrapper = try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject))
    let manifestData = try XCTUnwrap(wrapper.fileWrappers?["manifest.json"]?.regularFileContents)
    var raw = try XCTUnwrap(JSONSerialization.jsonObject(with: manifestData) as? [String: Any])
    var layers = try XCTUnwrap(raw["layers"] as? [[String: Any]])
    var effects = try XCTUnwrap(layers[1]["effects"] as? [Any])
    effects.append(["type": "lens-flare", "parameters": [:]])
    effects.append("garbage")
    effects.append(["type": "outline", "parameters": ["width": 4]])
    layers[1]["effects"] = effects
    raw["layers"] = layers
    let patched = FileWrapper(directoryWithFileWrappers: [
      "manifest.json": FileWrapper(
        regularFileWithContents: try JSONSerialization.data(withJSONObject: raw)),
      "layers": try XCTUnwrap(wrapper.fileWrappers?["layers"]),
    ])
    let decoded = try ProjectArchive.decode(patched)
    XCTAssertEqual(decoded.layers[1].effects.map(\.kind), ["drop-shadow", "outline"])
    XCTAssertEqual(decoded.layers[1].effects[1].number("width"), 4)
    XCTAssertEqual(decoded.layers[1].effects[1].string("position"), "outside")
  }

  func testPreviewImageIncludesEffects() throws {
    let (store, id) = try storeWithSquare()
    store.setEffects([hardRedShadow], for: id)
    let wrapper = try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject))
    let data = try XCTUnwrap(wrapper.fileWrappers?["preview.png"]?.regularFileContents)
    let preview = try XCTUnwrap(UIImage(data: data))
    // The 80×60 canvas is smaller than the preview cap, so it is not scaled.
    XCTAssertEqual(preview.size, CGSize(width: 80, height: 60))
    XCTAssertEqual(try word(preview, x: 35, y: 35), 0xFFFF_0000)
    XCTAssertEqual(try word(preview, x: 25, y: 25), 0xFF00_00FF)
  }

  func testScaledPreviewImageIncludesEffects() throws {
    // Past the preview cap the archive composites straight into a scaled
    // context, a separate path from `EditorStore.render`, so it is checked
    // on its own.
    let canvas = CGSize(width: 2_048, height: 1_536)
    let store = EditorStore()
    store.newDocument(size: canvas)
    _ = try store.addImageLayers([
      (
        name: "Square",
        image: square(canvas: canvas, at: CGRect(x: 512, y: 512, width: 256, height: 256))
      )
    ])
    let id = try XCTUnwrap(store.activeLayerID)
    var shadow = hardRedShadow
    shadow.parameters["offset_x"] = 40
    shadow.parameters["offset_y"] = 40
    store.setEffects([shadow], for: id)

    let wrapper = try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject))
    let data = try XCTUnwrap(wrapper.fileWrappers?["preview.png"]?.regularFileContents)
    let preview = try XCTUnwrap(UIImage(data: data))
    XCTAssertEqual(preview.size, CGSize(width: 1_024, height: 768))
    // Canvas (790, 790) is shadow only — past the square's 768 edge, inside
    // the shadow's 808 — and lands at (395, 395) in the half-size preview.
    let inShadow = try word(preview, x: 395, y: 395)
    XCTAssertEqual((inShadow >> 16) & 0xFF, 0xFF)
    XCTAssertLessThan((inShadow >> 8) & 0xFF, 8)
    XCTAssertLessThan(inShadow & 0xFF, 8)
    let inSquare = try word(preview, x: 320, y: 320)
    XCTAssertEqual(inSquare & 0xFF, 0xFF)
    XCTAssertLessThan((inSquare >> 16) & 0xFF, 8)
  }
}

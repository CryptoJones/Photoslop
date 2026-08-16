// SPDX-License-Identifier: Apache-2.0
import XCTest

@testable import PhotoslopIPad

/// The import-size question (#293) and typeface selection.
///
/// Importing used to scale every image to the canvas without asking, which
/// read as "importing an image is still auto cropping to canvas size"; and a
/// text layer could be any size and colour but only ever one face.
final class ImportSizingAndFontTests: XCTestCase {
  private func pngData(size: CGSize, color: UIColor = .red) -> Data {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    let image = UIGraphicsImageRenderer(size: size, format: format).image { context in
      color.setFill()
      context.fill(CGRect(origin: .zero, size: size))
    }
    return image.pngData()!
  }

  // MARK: - Import sizing

  func testExpandCanvasImportMakesTheCanvasTheImage() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    try store.importImage(
      data: pngData(size: CGSize(width: 1000, height: 800)), sizing: .expandCanvas)
    XCTAssertEqual(
      store.canvasSize, CGSize(width: 1000, height: 800),
      "expanding must make the canvas the image's own size")
  }

  func testCropToCanvasImportKeepsTheCanvasAndCentresThePixels() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    try store.importImage(
      data: pngData(size: CGSize(width: 1000, height: 800)), sizing: .cropToCanvas)
    XCTAssertEqual(
      store.canvasSize, CGSize(width: 400, height: 300),
      "cropping must leave the canvas alone")
    guard let image = store.layers.first?.image else { return XCTFail("no imported layer") }
    XCTAssertEqual(image.size, CGSize(width: 400, height: 300))
  }

  func testFitImportIsTheOldBehaviour() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    try store.importImage(data: pngData(size: CGSize(width: 1000, height: 800)))
    XCTAssertEqual(store.canvasSize, CGSize(width: 400, height: 300))
  }

  func testExpandCanvasImportRefusesAnImpossibleCanvas() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    // One dimension past what a project may save.
    let oversized = pngData(size: CGSize(width: 40000, height: 10))
    XCTAssertThrowsError(
      try store.importImage(data: oversized, sizing: .expandCanvas),
      "a canvas the archive would refuse must be refused at import")
  }

  // MARK: - Placement that grows the canvas

  func testPlacingAnOverhangingLayerCanExpandTheCanvas() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    let placed = try store.addPlaceableLayer(
      name: "Photo",
      image: UIGraphicsImageRenderer(size: CGSize(width: 200, height: 200)).image { context in
        UIColor.blue.setFill()
        context.fill(CGRect(x: 0, y: 0, width: 200, height: 200))
      })

    // Half on, half off the right-bottom corner.
    let rect = CGRect(x: 300, y: 200, width: 200, height: 200)
    XCTAssertTrue(store.placeLayerExpandingCanvas(placed.id, in: rect))
    XCTAssertEqual(
      store.canvasSize, CGSize(width: 500, height: 400),
      "the canvas must grow to the union of itself and the placed rectangle")
    let layer = store.layers.first(where: { $0.id == placed.id })
    XCTAssertEqual(
      layer?.placement, rect,
      "a placement on the positive side needs no shift — the rectangle is kept as dragged")
  }

  func testExpandingForANegativeOverhangShiftsEverythingTogether() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    XCTAssertTrue(
      store.addTextLayer("Anchor", fontSize: 20, color: .black, at: CGPoint(x: 50, y: 50)))
    let anchorBefore = store.layers.last?.text?.anchor

    let placed = try store.addPlaceableLayer(
      name: "Photo",
      image: UIGraphicsImageRenderer(size: CGSize(width: 100, height: 100)).image { context in
        UIColor.green.setFill()
        context.fill(CGRect(x: 0, y: 0, width: 100, height: 100))
      })
    // Hanging off the top-left: the union's origin is negative, so every
    // layer — and the text anchor — must shift right and down together.
    XCTAssertTrue(
      store.placeLayerExpandingCanvas(placed.id, in: CGRect(x: -60, y: -40, width: 100, height: 100))
    )
    XCTAssertEqual(store.canvasSize, CGSize(width: 460, height: 340))
    let anchorAfter = store.layers.first(where: { $0.text != nil })?.text?.anchor
    XCTAssertEqual(anchorAfter?.x, (anchorBefore?.x ?? 0) + 60)
    XCTAssertEqual(anchorAfter?.y, (anchorBefore?.y ?? 0) + 40)
    let photo = store.layers.first(where: { $0.id == placed.id })
    XCTAssertEqual(
      photo?.placement, CGRect(x: 0, y: 0, width: 100, height: 100),
      "the placed rectangle shifts by the same amount, so it starts at the new origin")
  }

  // MARK: - Typeface

  func testGlyphsRenderTightAroundTheWords() {
    let measured = TextLayerRenderer.measure(text: "Hello", fontSize: 40)
    guard let glyphs = TextLayerRenderer.glyphs(text: "Hello", fontSize: 40, color: .red) else {
      return XCTFail("nothing rendered for plain words")
    }
    XCTAssertEqual(glyphs.size.width, measured.width + 4, accuracy: 1)
    XCTAssertEqual(glyphs.size.height, measured.height + 4, accuracy: 1)
    XCTAssertNil(
      TextLayerRenderer.glyphs(text: "   ", fontSize: 40, color: .red),
      "blank input renders nothing, matching the layer renderer")
  }

  func testAMissingFontFamilyFallsBackToTheSystemFont() {
    let font = TextLayerRenderer.font(family: "No Such Family 9000", size: 30)
    XCTAssertEqual(
      font.familyName, UIFont.systemFont(ofSize: 30).familyName,
      "a family the OS no longer has must degrade to readable, not fail")
  }

  func testFontFamilySurvivesASaveAndReload() throws {
    let family = UIFont.familyNames.sorted().first ?? "Helvetica"
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    XCTAssertTrue(
      store.addTextLayer(
        "Faced", fontSize: 32, color: .black, at: CGPoint(x: 40, y: 40), fontFamily: family))

    let wrapper = try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject))
    let restored = try ProjectArchive.decode(wrapper)
    XCTAssertEqual(
      restored.layers.compactMap(\.text?.fontFamily), [family],
      "the chosen face is part of the document")
  }

  /// The store honours an explicit edited size exactly — even past the
  /// canvas edge. Whether to accept the cut-off or shrink to fit is the
  /// sheet's question (#298), asked before the store is called; a store that
  /// silently second-guessed the size was its own foot-gun.
  func testAnExplicitEditedSizeIsHonouredExactly() {
    let text = "Why are people so afraid of being a minority in America somehow"
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 1000, height: 1000))
    XCTAssertTrue(store.addTextLayer(text, fontSize: 20, color: .black, at: .zero))
    guard let id = store.activeLayerID else { return XCTFail("no text layer") }
    XCTAssertTrue(store.fitTextLayer(id, to: CGRect(x: 100, y: 400, width: 800, height: 500)))

    XCTAssertTrue(store.updateTextLayer(id, string: text, fontSize: 600, color: .black))
    XCTAssertEqual(
      store.layers.last?.text?.fontSize ?? 0, 600, accuracy: 0.001,
      "a confirmed oversize is kept as chosen")
    XCTAssertEqual(
      store.layers.last?.text?.wrapWidth ?? 0, 800, accuracy: 0.001,
      "the wrap survives the edit")

    XCTAssertTrue(store.updateTextLayer(id, string: text, fontSize: 24, color: .black))
    XCTAssertEqual(store.layers.last?.text?.fontSize ?? 0, 24, accuracy: 0.001)
  }

  func testDocumentsWithoutAFontFamilyStillDecodeAsSystem() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    XCTAssertTrue(
      store.addTextLayer("Plain", fontSize: 32, color: .black, at: CGPoint(x: 40, y: 40)))
    let wrapper = try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject))
    let restored = try ProjectArchive.decode(wrapper)
    XCTAssertEqual(restored.layers.compactMap(\.text).count, 1)
    XCTAssertNil(restored.layers.compactMap(\.text).first?.fontFamily)
  }
}

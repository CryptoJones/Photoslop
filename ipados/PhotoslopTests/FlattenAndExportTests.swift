// SPDX-License-Identifier: Apache-2.0
import XCTest

@testable import PhotoslopIPad

/// Flatten Image (#300) and the export background choice.
///
/// The report: a picture that looked finished in Photoslop exported with its
/// transparent areas intact, which most viewers show as black — and there was
/// no way to collapse a text layer with opacity onto its background by hand.
final class FlattenAndExportTests: XCTestCase {
  private func pixel(
    _ image: UIImage, x: Int, y: Int
  ) -> (r: CGFloat, g: CGFloat, b: CGFloat, a: CGFloat) {
    var data = [UInt8](repeating: 0, count: 4)
    let space = CGColorSpaceCreateDeviceRGB()
    let context = CGContext(
      data: &data, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
      space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    context.translateBy(x: CGFloat(-x), y: CGFloat(y - Int(image.size.height) + 1))
    context.draw(image.cgImage!, in: CGRect(origin: .zero, size: image.size))
    let a = CGFloat(data[3]) / 255
    guard a > 0 else { return (0, 0, 0, 0) }
    return (
      CGFloat(data[0]) / 255 / a, CGFloat(data[1]) / 255 / a, CGFloat(data[2]) / 255 / a, a
    )
  }

  private func solid(_ color: UIColor, size: CGSize) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: size, format: format).image { context in
      color.setFill()
      context.fill(CGRect(origin: .zero, size: size))
    }
  }

  /// A store whose bottom-right corner is genuinely transparent: a small
  /// opaque square in the top-left, the white background deleted.
  private func storeWithTransparentCorner() throws -> EditorStore {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 200, height: 200))
    let backgroundID = store.layers.first!.id
    let placed = try store.addPlaceableLayer(
      name: "Square", image: solid(.green, size: CGSize(width: 50, height: 50)))
    store.placeLayer(placed.id, in: CGRect(x: 0, y: 0, width: 50, height: 50))
    store.deleteLayer(backgroundID)
    try store.addImageLayers([
      (name: "Mark", image: solid(.clear, size: CGSize(width: 200, height: 200)))
    ])
    return store
  }

  func testFlattenCollapsesVisibleLayersWithTheirOpacity() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 100, height: 100))
    let size = CGSize(width: 100, height: 100)
    try store.addImageLayers([
      (name: "Red", image: solid(.red, size: size)),
      (name: "Blue", image: solid(.blue, size: size)),
    ])
    guard let blue = store.layers.last else { return XCTFail("no top layer") }
    store.setOpacity(0.5, for: blue.id)

    store.flattenImage()
    XCTAssertEqual(store.layers.count, 1, "flattening leaves exactly one layer")
    guard let image = store.layers.first?.image else { return XCTFail("no flattened image") }
    let sample = pixel(image, x: 50, y: 50)
    XCTAssertEqual(sample.a, 1, accuracy: 0.02, "opaque under opaque stays opaque")
    XCTAssertEqual(sample.r, 0.5, accuracy: 0.1, "half-opacity blue over red blends the red down")
    XCTAssertEqual(sample.b, 0.5, accuracy: 0.1, "and brings the blue in")
  }

  func testFlattenKeepsTransparencyRatherThanFillingIt() throws {
    let store = try storeWithTransparentCorner()
    XCTAssertGreaterThan(store.layers.count, 1)
    store.flattenImage()
    XCTAssertEqual(store.layers.count, 1)
    guard let image = store.layers.first?.image else { return XCTFail("no flattened image") }
    XCTAssertEqual(
      pixel(image, x: 150, y: 150).a, 0, accuracy: 0.02,
      "flattening keeps transparency — it does not invent a background")
    XCTAssertEqual(
      pixel(image, x: 25, y: 25).a, 1, accuracy: 0.02, "the artwork itself stays put")
  }

  func testExportOnWhiteFlattensTransparencyAndTheDefaultKeepsIt() async throws {
    let store = try storeWithTransparentCorner()

    guard let kept = await store.exportImage(format: .png),
      let keptImage = UIImage(data: kept)
    else { return XCTFail("no PNG data") }
    XCTAssertEqual(
      pixel(keptImage, x: 150, y: 150).a, 0, accuracy: 0.02,
      "the default export keeps the transparency the document really has")

    guard let flattened = await store.exportImage(format: .png, onWhite: true),
      let flatImage = UIImage(data: flattened)
    else { return XCTFail("no flattened PNG data") }
    let corner = pixel(flatImage, x: 150, y: 150)
    XCTAssertEqual(corner.a, 1, accuracy: 0.02, "flatten-to-white leaves no transparency")
    XCTAssertEqual(corner.r, 1, accuracy: 0.02, "and the fill is white")
    XCTAssertEqual(corner.g, 1, accuracy: 0.02)
  }
}

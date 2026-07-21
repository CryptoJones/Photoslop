// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

@MainActor
final class EditorStoreTests: XCTestCase {
  func testNewDocumentStartsWithEditableBackground() {
    let store = EditorStore()
    XCTAssertEqual(store.layers.count, 1)
    XCTAssertEqual(store.activeLayer?.name, "Background")
    XCTAssertEqual(store.canvasSize, CGSize(width: 2048, height: 1536))
  }

  func testLayerLifecycleKeepsAnActiveLayer() {
    let store = EditorStore()
    store.addLayer()
    XCTAssertEqual(store.layers.count, 2)
    store.duplicateActiveLayer()
    XCTAssertEqual(store.layers.count, 3)
    store.deleteActiveLayer()
    XCTAssertEqual(store.layers.count, 2)
    XCTAssertNotNil(store.activeLayerID)
  }

  func testLayerMutationSupportsUndoAndRedo() {
    let store = EditorStore()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    store.addLayer()
    XCTAssertEqual(store.layers.count, 2)
    XCTAssertTrue(undoManager.canUndo)
    undoManager.undo()
    XCTAssertEqual(store.layers.count, 1)
    XCTAssertTrue(undoManager.canRedo)
    undoManager.redo()
    XCTAssertEqual(store.layers.count, 2)
  }

  func testPhotoslopPackageRoundTripPreservesLayerMetadata() throws {
    let store = EditorStore()
    store.addLayer()
    guard let id = store.activeLayerID else { return XCTFail("missing active layer") }
    store.rename("Ink", for: id)
    store.setOpacity(0.42, for: id)
    store.setVisible(false, for: id)

    let snapshot = try store.snapshot(contentType: .photoslopProject)
    let wrapper = try ProjectArchive.encode(snapshot)
    let restored = try ProjectArchive.decode(wrapper)
    XCTAssertEqual(restored.canvasSize, store.canvasSize)
    XCTAssertEqual(restored.layers.count, 2)
    XCTAssertEqual(restored.activeLayerID, id)
    XCTAssertEqual(restored.layers.last?.name, "Ink")
    XCTAssertEqual(restored.layers.last?.opacity ?? 0, 0.42, accuracy: 0.001)
    XCTAssertEqual(restored.layers.last?.isVisible, false)
  }

  func testProjectResourceCapsAreHard() {
    XCTAssertTrue(ProjectArchive.isValidCanvas(CGSize(width: 4_000, height: 4_000)))
    XCTAssertFalse(ProjectArchive.isValidCanvas(CGSize(width: 16_385, height: 1)))
    XCTAssertFalse(ProjectArchive.isValidCanvas(CGSize(width: 10_001, height: 10_001)))
  }

  func testPNGExportRendersAsynchronously() async {
    let store = EditorStore()
    let data = await store.exportPNG()
    XCTAssertNotNil(data)
    XCTAssertNotNil(data.flatMap(UIImage.init(data:)))
  }

  func testVisibilityAndOpacityAffectComposite() {
    let red = EditorStore.solidImage(size: CGSize(width: 2, height: 2), color: .red)
    let blue = EditorStore.solidImage(size: CGSize(width: 2, height: 2), color: .blue)
    let bottom = RasterLayer(name: "Red", image: red)
    var top = RasterLayer(name: "Blue", image: blue)
    top.opacity = 0.5

    let blended = EditorStore.render(layers: [bottom, top], size: CGSize(width: 2, height: 2))
    let color = blended.pixelColor(x: 0, y: 0)
    XCTAssertEqual(color.red, 0.5, accuracy: 0.04)
    XCTAssertEqual(color.blue, 0.5, accuracy: 0.04)

    top.isVisible = false
    let hidden = EditorStore.render(layers: [bottom, top], size: CGSize(width: 2, height: 2))
    XCTAssertEqual(hidden.pixelColor(x: 0, y: 0).red, 1, accuracy: 0.01)
  }

  func testImportRejectsInvalidData() {
    let store = EditorStore()
    XCTAssertThrowsError(try store.importImage(data: Data("not an image".utf8)))
  }
}

extension UIImage {
  fileprivate func pixelColor(x: Int, y: Int) -> (
    red: CGFloat, green: CGFloat, blue: CGFloat, alpha: CGFloat
  ) {
    guard let cgImage,
      let data = cgImage.dataProvider?.data,
      let bytes = CFDataGetBytePtr(data)
    else { return (0, 0, 0, 0) }
    let offset = y * cgImage.bytesPerRow + x * 4
    if cgImage.bitmapInfo.contains(.byteOrder32Little) {
      return (
        CGFloat(bytes[offset + 2]) / 255,
        CGFloat(bytes[offset + 1]) / 255,
        CGFloat(bytes[offset]) / 255,
        CGFloat(bytes[offset + 3]) / 255
      )
    }
    return (
      CGFloat(bytes[offset]) / 255,
      CGFloat(bytes[offset + 1]) / 255,
      CGFloat(bytes[offset + 2]) / 255,
      CGFloat(bytes[offset + 3]) / 255
    )
  }
}

// SPDX-License-Identifier: Apache-2.0
import PencilKit
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Version 3 of the document format: a layer carries an origin and only has to
/// FIT the canvas rather than BE it (#309).
final class BoundedLayerExtentTests: XCTestCase {

  private func store(withTextAt anchor: CGPoint) -> EditorStore {
    let store = EditorStore()
    XCTAssertTrue(
      store.addTextLayer("Bounded", fontSize: 96, color: .white, at: anchor))
    return store
  }

  // MARK: - The payoff

  /// The whole reason for the format change: a caption costs its own box.
  func testATextLayerCostsItsWordsNotTheWholeCanvas() throws {
    let store = store(withTextAt: CGPoint(x: 120, y: 200))
    let layer = try XCTUnwrap(store.layers.last)

    let bounded = Int(layer.image.size.width) * Int(layer.image.size.height) * 4
    let canvasSized = Int(store.canvasSize.width) * Int(store.canvasSize.height) * 4
    print(
      "### text layer: \(Int(layer.image.size.width))x\(Int(layer.image.size.height))"
        + String(format: " = %.0f KB (canvas-sized would be %.1f MB, %.0fx more)",
          Double(bounded) / 1_000, Double(canvasSized) / 1_000_000,
          Double(canvasSized) / Double(max(bounded, 1))))

    XCTAssertEqual(layer.origin, CGPoint(x: 120, y: 200))
    XCTAssertLessThan(bounded, canvasSized / 10, "a caption should not cost a canvas")
  }

  // MARK: - Round trip

  func testOriginSurvivesEncodeAndDecode() throws {
    let store = store(withTextAt: CGPoint(x: 64, y: 96))
    let original = try XCTUnwrap(store.layers.last)

    let snapshot = try ProjectArchive.snapshot(
      state: EditorState(
        layers: store.layers, activeLayerID: store.activeLayerID,
        canvasSize: store.canvasSize))
    // Version 3 introduced the origin; later versions carry it unchanged.
    XCTAssertGreaterThanOrEqual(snapshot.manifest.version, 3)

    let decoded = try ProjectArchive.decode(try ProjectArchive.encode(snapshot))
    let restored = try XCTUnwrap(decoded.layers.last)
    XCTAssertEqual(restored.origin, original.origin)
    XCTAssertEqual(restored.image.size, original.image.size)
    XCTAssertEqual(restored.frame, original.frame)
  }

  /// A layer that fills the canvas writes no origin at all, so a document with
  /// nothing bounded in it stays byte-comparable to what version 2 wrote.
  func testAFullCanvasLayerRecordsNoOrigin() throws {
    let store = EditorStore()
    let snapshot = try ProjectArchive.snapshot(
      state: EditorState(
        layers: store.layers, activeLayerID: store.activeLayerID,
        canvasSize: store.canvasSize))
    XCTAssertTrue(snapshot.manifest.layers.allSatisfy { $0.origin == nil })
  }

  // MARK: - Backwards compatibility

  /// Documents written before version 3 must still open. Their layers have no
  /// origin and are canvas-sized, which is exactly what the old rule enforced.
  func testAVersionTwoDocumentStillOpens() throws {
    let store = EditorStore()
    let snapshot = try ProjectArchive.snapshot(
      state: EditorState(
        layers: store.layers, activeLayerID: store.activeLayerID,
        canvasSize: store.canvasSize))
    let wrapper = try ProjectArchive.encode(snapshot)

    // Rewrite the manifest as a version 2 file: older version, no origin key.
    let root = try XCTUnwrap(wrapper.fileWrappers)
    let manifestData = try XCTUnwrap(root["manifest.json"]?.regularFileContents)
    var json = try XCTUnwrap(
      JSONSerialization.jsonObject(with: manifestData) as? [String: Any])
    json["version"] = 2
    if var layers = json["layers"] as? [[String: Any]] {
      for index in layers.indices { layers[index].removeValue(forKey: "origin") }
      json["layers"] = layers
    }
    let downgraded = try JSONSerialization.data(withJSONObject: json)

    var children = root
    children["manifest.json"] = FileWrapper(regularFileWithContents: downgraded)
    let legacy = FileWrapper(directoryWithFileWrappers: children)

    let decoded = try ProjectArchive.decode(legacy)
    XCTAssertEqual(decoded.canvasSize, store.canvasSize)
    XCTAssertTrue(
      decoded.layers.allSatisfy { $0.origin == .zero && $0.image.size == store.canvasSize },
      "a pre-v3 layer fills the canvas at the top-left")
  }

  // MARK: - Validation

  func testAFrameFarOutsideTheCanvasIsRejected() {
    let canvas = CGSize(width: 2048, height: 1536)
    XCTAssertTrue(
      ProjectArchive.isLayerFrameValid(
        CGRect(x: 0, y: 0, width: 2048, height: 1536), canvas: canvas))
    XCTAssertTrue(
      ProjectArchive.isLayerFrameValid(
        CGRect(x: -40, y: -40, width: 200, height: 200), canvas: canvas),
      "overhanging an edge has always been allowed")
    XCTAssertFalse(
      ProjectArchive.isLayerFrameValid(
        CGRect(x: 90_000, y: 90_000, width: 10, height: 10), canvas: canvas),
      "a layer with no pixels on the canvas is not a layer")
    XCTAssertFalse(
      ProjectArchive.isLayerFrameValid(
        CGRect(x: 0.5, y: 0, width: 10, height: 10), canvas: canvas),
      "origins are whole pixels")
  }

  // MARK: - Geometry still works on a bounded layer

  /// Resize, canvas resize and clear all predate bounded extents. Each expands
  /// the layer first, so a text layer must survive them intact.
  func testGeometryOperationsSurviveABoundedLayer() throws {
    let store = store(withTextAt: CGPoint(x: 100, y: 100))
    XCTAssertEqual(store.layers.count, 2)

    store.scaleDocument(to: CGSize(width: 1024, height: 768))
    XCTAssertEqual(store.canvasSize, CGSize(width: 1024, height: 768))
    XCTAssertTrue(
      store.layers.allSatisfy {
        ProjectArchive.isLayerFrameValid($0.frame, canvas: store.canvasSize)
      }, "every layer still fits the canvas after a resize")

    // The document must still be saveable, which is the real regression risk.
    XCTAssertNoThrow(
      try ProjectArchive.snapshot(
        state: EditorState(
          layers: store.layers, activeLayerID: store.activeLayerID,
          canvasSize: store.canvasSize)))
  }
}

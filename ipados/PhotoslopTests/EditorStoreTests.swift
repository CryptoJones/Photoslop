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

extension EditorStoreTests {
  /// Canvas resize pads and crops around centred content, matching
  /// `photoslop-cli --canvas-size`, which offsets by half the difference.
  func testCanvasResizeKeepsArtworkCentredLikeTheCli() {
    let store = EditorStore()
    let original = store.canvasSize
    let grown = CGSize(width: original.width + 400, height: original.height + 200)

    store.resizeCanvas(to: grown)

    XCTAssertEqual(store.canvasSize, grown)
    for layer in store.layers {
      XCTAssertEqual(layer.image.size, grown, "\(layer.name) was not recanvased")
    }
  }

  func testCanvasResizeIsUndoable() {
    let store = EditorStore()
    let undoManager = UndoManager()
    store.undoManager = undoManager
    let original = store.canvasSize

    store.resizeCanvas(to: CGSize(width: 640, height: 480))
    XCTAssertEqual(store.canvasSize, CGSize(width: 640, height: 480))
    XCTAssertTrue(undoManager.canUndo)

    undoManager.undo()
    XCTAssertEqual(store.canvasSize, original)
  }

  func testCanvasResizeRefusesSizesTheProjectCannotSave() {
    let store = EditorStore()
    let original = store.canvasSize

    store.resizeCanvas(to: CGSize(width: 0, height: 100))
    XCTAssertEqual(store.canvasSize, original, "a zero dimension must be refused")

    store.resizeCanvas(to: CGSize(width: 40_000, height: 40_000))
    XCTAssertEqual(store.canvasSize, original, "past the caps must be refused")

    store.resizeCanvas(to: original)
    XCTAssertEqual(store.canvasSize, original)
  }

  func testAboutInformationIsPresentInTheBundle() {
    let info = Bundle(for: EditorStore.self).infoDictionary ?? [:]
    XCTAssertNotNil(
      info["CFBundleShortVersionString"], "About shows the marketing version")
    XCTAssertNotNil(info["CFBundleVersion"], "About shows the build number")
  }
}

extension EditorStoreTests {
  /// DocumentGroup builds new documents itself with no chance to ask for a size
  /// first, so the editor offers the choice when the document appears. That
  /// only works if a new document can be told apart from an opened one.
  func testANewDocumentAsksForItsCanvasSize() {
    let store = EditorStore()
    XCTAssertTrue(store.awaitingCanvasSizeChoice)
  }

  func testAskingIsClearedOnceOfferedSoItDoesNotRepeat() {
    let store = EditorStore()
    store.canvasSizeChoiceOffered()
    XCTAssertFalse(
      store.awaitingCanvasSizeChoice,
      "the sheet would return on every reappearance, rotation, and resume")
  }

  /// This used to assert that "only `init()` raises the flag, so nothing on the
  /// opening path can turn it on" — which was the bug, stated as a guarantee.
  /// Creating a document writes it to disk and reopens it through
  /// `init(configuration:)`, so `init()`'s flag is spent on a store that never
  /// reaches the screen and the question was never asked. What it pins now is
  /// that answering, then editing, does not bring the question back.
  func testAnsweringThenEditingDoesNotBringTheQuestionBack() throws {
    let store = EditorStore()
    store.canvasSizeChoiceOffered()
    store.resizeCanvas(to: CGSize(width: 900, height: 700))

    let wrapper = try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject))
    let restored = try ProjectArchive.decode(wrapper)
    XCTAssertEqual(restored.canvasSize, CGSize(width: 900, height: 700))
    XCTAssertFalse(store.awaitingCanvasSizeChoice)
    XCTAssertFalse(
      EditorStore.isUntouchedNewDocument(restored),
      "a document resized on purpose has had its size chosen")
  }

  /// `ReadConfiguration` has no public initialiser, so `init(configuration:)`
  /// cannot be called directly. These cover the recogniser it consults, over
  /// states that have been through a real encode/decode round trip — the trip
  /// that loses `init()`'s flag.
  func testAFreshDocumentSurvivesTheDiskRoundTripAsStillNeedingASize() throws {
    let store = EditorStore()
    let restored = try roundTrip(store)

    XCTAssertTrue(
      EditorStore.isUntouchedNewDocument(restored),
      "the launch scene writes a new document to disk and reopens it; if this "
        + "shape is not recognised, the size question is never asked")
  }

  func testAnEditedDocumentIsNotMistakenForANewOne() throws {
    for (name, edit) in editsThatCountAsTouching {
      let store = EditorStore()
      edit(store)
      let restored = try roundTrip(store)
      XCTAssertFalse(
        EditorStore.isUntouchedNewDocument(restored),
        "\(name) is an edit, so the document has been accepted at its size")
    }
  }

  /// Each of these alone should be enough to stop the question being asked.
  private var editsThatCountAsTouching: [(String, (EditorStore) -> Void)] {
    [
      ("resizing the canvas", { $0.resizeCanvas(to: CGSize(width: 640, height: 480)) }),
      ("adding a layer", { $0.addLayer() }),
      (
        "renaming the only layer",
        { store in
          guard let id = store.activeLayerID else { return }
          store.rename("Sketch", for: id)
        }
      ),
      (
        "hiding the only layer",
        { store in
          guard let id = store.activeLayerID else { return }
          store.setVisible(false, for: id)
        }
      ),
      (
        "changing opacity",
        { store in
          guard let id = store.activeLayerID else { return }
          store.setOpacity(0.5, for: id)
        }
      ),
      (
        "adding text",
        { store in
          _ = store.addTextLayer(
            "hello", fontSize: 48, color: .black, at: CGPoint(x: 100, y: 100))
        }
      ),
    ]
  }

  private func roundTrip(_ store: EditorStore) throws -> EditorState {
    try ProjectArchive.decode(
      try ProjectArchive.encode(try store.snapshot(contentType: .photoslopProject)))
  }
}

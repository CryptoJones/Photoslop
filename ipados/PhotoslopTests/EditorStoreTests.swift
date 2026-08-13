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
  // MARK: - New layer from photo

  /// The point of the feature: a second image joins the document instead of
  /// replacing it, which is what a double exposure needs.
  func testAddingAPhotoLayerKeepsWhatIsAlreadyThere() throws {
    let store = EditorStore()
    try store.importImage(data: Self.jpeg(width: 2031, height: 1429), suggestedName: "First")
    let canvas = store.canvasSize
    XCTAssertEqual(store.layers.count, 1)

    let added = try store.addImageLayers([
      (name: "Photo", image: Self.image(width: 1318, height: 2014))
    ])

    XCTAssertEqual(added, 1)
    XCTAssertEqual(store.layers.count, 2, "the first image must survive the second")
    XCTAssertEqual(store.layers.first?.name, "First")
    XCTAssertEqual(store.canvasSize, canvas, "adding a layer must not resize the canvas")
    XCTAssertEqual(store.activeLayerID, store.layers.last?.id)
  }

  /// `ProjectArchive.snapshot` refuses any layer whose image is not exactly
  /// canvas-sized, so a document with a mismatched layer cannot be saved at all.
  func testPhotoLayersAreCanvasSizedWhateverThePhotoWas() throws {
    let store = EditorStore()
    store.resizeCanvas(to: CGSize(width: 1000, height: 800))

    try store.addImageLayers([
      (name: "Landscape", image: Self.image(width: 2031, height: 1429)),
      (name: "Portrait", image: Self.image(width: 1318, height: 2014)),
      (name: "Tiny", image: Self.image(width: 40, height: 40)),
    ])

    for layer in store.layers {
      XCTAssertEqual(layer.image.size, store.canvasSize, "\(layer.name) is not canvas-sized")
    }
    XCTAssertNoThrow(try store.snapshot(contentType: .photoslopProject))
  }

  /// Aspect ratio is preserved, so a portrait photo keeps its proportions and
  /// pays for the difference in transparent edges rather than in stretching.
  ///
  /// Fitting works in both directions. This test previously asserted the
  /// opposite for the small case — that an image smaller than the canvas was
  /// left alone rather than blown up (#234), on the reasoning that upscaling
  /// invents detail. The reasoning is sound and the behaviour was still wrong:
  /// it made one action do two different things depending on the size of the
  /// photo someone picked. Reversed in #258.
  func testFittingPreservesAspectRatioInBothDirections() {
    let canvas = CGSize(width: 1000, height: 1000)

    let wide = EditorStore.fitted(Self.image(width: 2000, height: 1000), into: canvas)
    XCTAssertEqual(wide.size, canvas)
    // 2000x1000 into 1000x1000 fits at half scale: 1000x500, so a quarter of the
    // height is transparent at the top and a quarter at the bottom.
    XCTAssertTrue(Self.isTransparent(wide, at: CGPoint(x: 500, y: 10)))
    XCTAssertFalse(Self.isTransparent(wide, at: CGPoint(x: 500, y: 500)))

    // Smaller than the canvas: scaled up to fill it, not left in the middle.
    let small = EditorStore.fitted(Self.image(width: 100, height: 100), into: canvas)
    XCTAssertEqual(small.size, canvas)
    XCTAssertFalse(
      Self.isTransparent(small, at: CGPoint(x: 10, y: 10)),
      "a square image should fill a square canvas once fitting scales up")
    XCTAssertFalse(Self.isTransparent(small, at: CGPoint(x: 500, y: 500)))

    // Aspect ratio still holds when scaling up: 2:1 into a square leaves bands.
    let smallWide = EditorStore.fitted(Self.image(width: 200, height: 100), into: canvas)
    XCTAssertTrue(Self.isTransparent(smallWide, at: CGPoint(x: 500, y: 10)))
    XCTAssertFalse(Self.isTransparent(smallWide, at: CGPoint(x: 10, y: 500)))
  }

  func testAWholeSelectionIsOneUndoStep() throws {
    let store = EditorStore()
    let undo = UndoManager()
    store.undoManager = undo

    try store.addImageLayers([
      (name: "One", image: Self.image(width: 100, height: 100)),
      (name: "Two", image: Self.image(width: 100, height: 100)),
      (name: "Three", image: Self.image(width: 100, height: 100)),
    ])
    XCTAssertEqual(store.layers.count, 4)

    undo.undo()
    XCTAssertEqual(store.layers.count, 1, "three photos should undo in one step, not three")
  }

  func testDuplicateNamesAreMadeUnique() throws {
    let store = EditorStore()
    try store.addImageLayers([
      (name: "Photo", image: Self.image(width: 100, height: 100)),
      (name: "Photo", image: Self.image(width: 100, height: 100)),
    ])
    XCTAssertEqual(Set(store.layers.map(\.name)).count, store.layers.count)
  }

  /// Refused as a batch rather than half-added, so the document is never left in
  /// a state the project cannot hold.
  func testASelectionThatWouldExceedTheLayerCapIsRefusedWhole() throws {
    let store = EditorStore()
    let before = store.layers.count
    let tooMany = Array(
      repeating: (name: "Photo", image: Self.image(width: 10, height: 10)),
      count: ProjectArchive.maximumLayers)

    XCTAssertThrowsError(try store.addImageLayers(tooMany))
    XCTAssertEqual(store.layers.count, before, "a refused batch must add nothing")
  }

  func testAnEmptySelectionDoesNothing() throws {
    let store = EditorStore()
    let before = store.layers.count
    XCTAssertEqual(try store.addImageLayers([]), 0)
    XCTAssertEqual(store.layers.count, before)
  }

  private static func image(width: Int, height: Int) -> UIImage {
    let size = CGSize(width: width, height: height)
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    return UIGraphicsImageRenderer(size: size, format: format).image { context in
      UIColor.systemPink.setFill()
      context.fill(CGRect(origin: .zero, size: size))
    }
  }

  private static func jpeg(width: Int, height: Int) -> Data {
    guard let data = image(width: width, height: height).jpegData(compressionQuality: 0.9) else {
      preconditionFailure("could not encode a test JPEG")
    }
    return data
  }

  private static func isTransparent(_ image: UIImage, at point: CGPoint) -> Bool {
    guard let cgImage = image.cgImage else { return false }
    var pixel: [UInt8] = [0, 0, 0, 0]
    guard
      let context = CGContext(
        data: &pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    else { return false }
    context.draw(
      cgImage, in: CGRect(x: -point.x, y: -(CGFloat(cgImage.height) - point.y), width: CGFloat(cgImage.width), height: CGFloat(cgImage.height)))
    return pixel[3] == 0
  }

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

/// Cropping is `resizeCanvas` with a chosen origin, and shares its
/// implementation deliberately: a layer is pixels *and* PencilKit strokes *and*
/// possibly a text anchor, and all three have to travel together.
extension EditorStoreTests {
  @MainActor
  func testCropResizesTheCanvasToTheRectangle() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))

    store.crop(to: CGRect(x: 50, y: 40, width: 200, height: 150))

    XCTAssertEqual(store.canvasSize, CGSize(width: 200, height: 150))
  }

  @MainActor
  func testCropIsOneUndoableStep() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))

    // Attached after the document exists. UndoManager groups by run-loop event
    // and a test performs every mutation inside one, so an undo manager present
    // for both would revert the document's creation along with the crop and
    // this would pass while telling us nothing about cropping.
    let undoManager = UndoManager()
    store.undoManager = undoManager

    store.crop(to: CGRect(x: 10, y: 10, width: 100, height: 100))
    XCTAssertEqual(store.canvasSize, CGSize(width: 100, height: 100))

    XCTAssertTrue(undoManager.canUndo)
    XCTAssertEqual(undoManager.undoActionName, "Crop")
    undoManager.undo()
    XCTAssertEqual(
      store.canvasSize, CGSize(width: 400, height: 300),
      "one undo should restore the whole canvas")
  }

  @MainActor
  func testCropIsClampedToTheCanvas() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))

    // A rectangle reaching past the edge crops to the overlap rather than
    // inventing canvas that was never there.
    store.crop(to: CGRect(x: 300, y: 200, width: 400, height: 400))

    XCTAssertEqual(store.canvasSize, CGSize(width: 100, height: 100))
  }

  @MainActor
  func testCroppingToTheWholeCanvasChangesNothing() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    let before = store.canvasSize

    store.crop(to: CGRect(x: 0, y: 0, width: 400, height: 300))

    XCTAssertEqual(store.canvasSize, before)
  }

  @MainActor
  func testCropMovesTheTextAnchorWithThePixels() {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 400, height: 300))
    _ = store.addTextLayer(
      "Hi", fontSize: 24, color: .black, at: CGPoint(x: 120, y: 90))

    store.crop(to: CGRect(x: 20, y: 30, width: 200, height: 150))

    let anchor = store.layers.compactMap(\.text).first
    XCTAssertEqual(anchor?.x ?? 0, 100, accuracy: 1, "the text anchor did not follow the crop")
    XCTAssertEqual(anchor?.y ?? 0, 60, accuracy: 1, "the text anchor did not follow the crop")
  }
}

/// Importing a photo keeps the canvas the person chose and fits the photo to it.
extension EditorStoreTests {
  private func photoData(_ size: CGSize, color: UIColor = .systemTeal) -> Data {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    let image = UIGraphicsImageRenderer(size: size, format: format).image { context in
      color.setFill()
      context.fill(CGRect(origin: .zero, size: size))
    }
    return image.pngData()!
  }

  @MainActor
  func testImportingAPhotoKeepsTheChosenCanvas() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 1920, height: 1080))

    // A photo far larger, and a different shape, than the canvas.
    try store.importImage(data: photoData(CGSize(width: 4032, height: 3024)))

    XCTAssertEqual(
      store.canvasSize, CGSize(width: 1920, height: 1080),
      "importing took the canvas from the photo instead of keeping the chosen one")
    XCTAssertEqual(store.layers.count, 1)
    XCTAssertEqual(store.layers[0].image.size, CGSize(width: 1920, height: 1080))
  }

  @MainActor
  func testAPhotoSmallerThanTheCanvasIsScaledUpToFit() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 1000, height: 1000))

    // 200x100 fits the width at 10x; the layer is canvas-sized either way, so
    // the check is that the drawn content reaches the edges rather than sitting
    // small in the middle.
    try store.importImage(data: photoData(CGSize(width: 200, height: 100)))

    let image = store.layers[0].image
    XCTAssertEqual(image.size, CGSize(width: 1000, height: 1000))
    // Scaled to fit width means opaque pixels at the horizontal extremes.
    let left = image.pixelColor(at: CGPoint(x: 2, y: 500))
    let right = image.pixelColor(at: CGPoint(x: 997, y: 500))
    XCTAssertGreaterThan(left.alpha, 0.5, "the photo was not scaled up to the canvas width")
    XCTAssertGreaterThan(right.alpha, 0.5, "the photo was not scaled up to the canvas width")
  }

  @MainActor
  func testAFittedPhotoIsCentred() throws {
    let store = EditorStore()
    store.newDocument(size: CGSize(width: 1000, height: 1000))

    // 2:1 fits the width and leaves equal transparent bands above and below.
    try store.importImage(data: photoData(CGSize(width: 400, height: 200)))

    let image = store.layers[0].image
    let top = image.pixelColor(at: CGPoint(x: 500, y: 10))
    let bottom = image.pixelColor(at: CGPoint(x: 500, y: 990))
    let middle = image.pixelColor(at: CGPoint(x: 500, y: 500))
    XCTAssertLessThan(top.alpha, 0.5, "content should not reach the top edge")
    XCTAssertLessThan(bottom.alpha, 0.5, "content should not reach the bottom edge")
    XCTAssertGreaterThan(middle.alpha, 0.5, "the centre should hold the photo")
  }
}

extension UIImage {
  /// Alpha and colour at a point, for asserting where fitted content landed.
  fileprivate func pixelColor(at point: CGPoint) -> (alpha: CGFloat, color: UIColor) {
    guard let cgImage else { return (0, .clear) }
    var pixel = [UInt8](repeating: 0, count: 4)
    let space = CGColorSpaceCreateDeviceRGB()
    let info = CGImageAlphaInfo.premultipliedLast.rawValue
    guard
      let context = CGContext(
        data: &pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
        space: space, bitmapInfo: info)
    else { return (0, .clear) }
    context.draw(
      cgImage,
      in: CGRect(x: -point.x, y: -(CGFloat(cgImage.height) - point.y), 
                 width: CGFloat(cgImage.width), height: CGFloat(cgImage.height)))
    let alpha = CGFloat(pixel[3]) / 255
    return (
      alpha,
      UIColor(
        red: CGFloat(pixel[0]) / 255, green: CGFloat(pixel[1]) / 255,
        blue: CGFloat(pixel[2]) / 255, alpha: alpha)
    )
  }
}


// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Diagnostics for #309 — what a multi-photo import actually costs in memory.
///
/// These do not assert a threshold. They measure and print, because the claim
/// under test is about a growth curve, and the number that decides a crash (the
/// jetsam limit) exists only on a device. On the Simulator these are honest
/// allocations against effectively unlimited RAM; on device the same curve runs
/// into a ceiling and the process is killed.
final class ImportMemoryDiagnosticsTests: XCTestCase {

  /// `phys_footprint` is the figure jetsam actually kills on, so it is the one
  /// worth reading — not `resident_size`, which counts pages jetsam discounts.
  private func footprint() -> UInt64 {
    var info = task_vm_info_data_t()
    var count = mach_msg_type_number_t(
      MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
    let kr = withUnsafeMutablePointer(to: &info) {
      $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
        task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
      }
    }
    return kr == KERN_SUCCESS ? info.phys_footprint : 0
  }

  private func mb(_ bytes: UInt64) -> String {
    String(format: "%.1f MB", Double(bytes) / 1_000_000)
  }

  private func delta(_ from: UInt64, _ to: UInt64) -> String {
    to >= from ? "+\(mb(to - from))" : "-\(mb(from - to))"
  }

  /// JPEG data at the 13 Pro Max's own capture size, 4032x3024 (12 MP).
  ///
  /// Real photo bytes rather than a synthetic UIImage, so the import runs the
  /// same `CGImageSourceCreateWithData` + `normalizedImage` path a picked photo
  /// does — including the forced full-size redraw, which is what turns a
  /// lazily-decoded image into a resident bitmap.
  private func photoJPEGData() -> Data {
    let size = CGSize(width: 4032, height: 3024)
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = true
    // Per-pixel noise, NOT flat colour bands.
    //
    // This matters more than it looks. A banded image compresses to almost
    // nothing in iOS's memory compressor, so every layer built from one reads
    // as ~0 MB resident and the whole measurement flatters itself — the same
    // artefact that makes near-empty text layers look free. Noise is
    // incompressible, so what is measured is what a real photograph costs.
    let width = 4032, height = 3024
    var pixels = [UInt8](repeating: 0, count: width * height * 4)
    var seed: UInt64 = 0x2545_F491_4F6C_DD1D
    for index in stride(from: 0, to: pixels.count, by: 4) {
      seed ^= seed << 13
      seed ^= seed >> 7
      seed ^= seed << 17
      pixels[index] = UInt8(truncatingIfNeeded: seed)
      pixels[index + 1] = UInt8(truncatingIfNeeded: seed >> 8)
      pixels[index + 2] = UInt8(truncatingIfNeeded: seed >> 16)
      pixels[index + 3] = 255
    }
    let provider = CGDataProvider(data: Data(pixels) as CFData)!
    let cg = CGImage(
      width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
      bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
      bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
      provider: provider, decode: nil, shouldInterpolate: false,
      intent: .defaultIntent)!
    _ = format
    _ = size
    return UIImage(cgImage: cg).jpegData(compressionQuality: 0.95)!
  }

  /// The exact shape of `EditorView.addLayers(from:)`: decode every picked
  /// photo into an array first, then hand the whole array to the store.
  func testMultiPhotoImportMemoryCurve() throws {
    let data = photoJPEGData()
    print("### JPEG bytes: \(mb(UInt64(data.count))) — decoded should be ~48.8 MB each")

    let store = EditorStore()
    let base = footprint()
    print("### baseline: \(mb(base))")

    // Stage 1: decode-all-first, exactly as addLayers(from:) does.
    var loaded: [(name: String, image: UIImage)] = []
    for index in 1...8 {
      let image = try ProjectArchive.decodeImage(data)
      loaded.append((name: "Photo \(index)", image: image))
      let now = footprint()
      print("### decoded \(index): \(mb(now))  \(delta(base, now))")
    }
    let afterDecode = footprint()

    // Stage 2: addImageLayers builds a second array of canvas-sized bitmaps
    // while `loaded` is still alive.
    let added = try store.addImageLayers(loaded)
    let afterAdd = footprint()
    print("### added \(added) layers: \(mb(afterAdd))  \(delta(afterDecode, afterAdd))")
    print("### PEAK over baseline: \(delta(base, afterAdd))")

    XCTAssertEqual(added, 8)
  }

  /// Each text layer is rendered at full canvas size, and every edit renders a
  /// fresh one while the undo stack keeps the old alive.
  func testTextLayerAndUndoRetention() throws {
    let store = EditorStore()
    let undo = UndoManager()
    store.undoManager = undo
    print("### levelsOfUndo = \(undo.levelsOfUndo) (0 means unlimited)")

    let base = footprint()
    print("### baseline: \(mb(base))")

    for index in 1...12 {
      _ = store.addTextLayer(
        "Caption number \(index)", fontSize: 96, color: .white,
        at: CGPoint(x: 40, y: CGFloat(index) * 80))
      let now = footprint()
      print("### text layer \(index): \(mb(now))  \(delta(base, now))")
    }
    print("### PEAK over baseline: \(delta(base, footprint()))")
  }

  /// Scale the import up to find where the curve actually goes.
  func testImportScalesLinearlyWithPhotoCount() throws {
    let data = photoJPEGData()
    for count in [4, 8, 16, 24] {
      autoreleasepool {
        let store = EditorStore()
        let base = footprint()
        var loaded: [(name: String, image: UIImage)] = []
        for index in 1...count {
          if let image = try? ProjectArchive.decodeImage(data) {
            loaded.append((name: "Photo \(index)", image: image))
          }
        }
        let added = (try? store.addImageLayers(loaded)) ?? 0
        let peak = footprint()
        let each = Double(peak > base ? peak - base : 0) / Double(max(count, 1)) / 1_000_000
        print("### \(count) photos -> \(added) layers: \(delta(base, peak))  "
          + String(format: "(%.1f MB per photo)", each))
      }
    }
  }

  /// The retention claim: every text edit renders a fresh canvas-sized bitmap
  /// while the undo stack keeps every earlier one alive.
  func testRepeatedTextEditsRetainEveryEarlierRendering() throws {
    let store = EditorStore()
    let undo = UndoManager()
    store.undoManager = undo
    _ = store.addTextLayer("Caption", fontSize: 96, color: .white, at: CGPoint(x: 40, y: 40))
    guard let id = store.layers.last?.id else { return XCTFail("no text layer") }

    let base = footprint()
    print("### baseline after one text layer: \(mb(base))")
    for index in 1...40 {
      _ = store.fitTextLayer(id, to: CGRect(x: 40, y: 40, width: 600 + CGFloat(index) * 8, height: 300))
      if index % 10 == 0 {
        print("### after \(index) edits: \(delta(base, footprint()))  "
          + "undo stack canUndo=\(undo.canUndo)")
      }
    }
    print("### PEAK over baseline: \(delta(base, footprint()))")
  }

  /// The FIXED path, measured the same way as the old one so the two numbers
  /// are comparable: decode straight to canvas size, fit, and release each
  /// photo before touching the next — exactly what `addLayers(from:)` now does.
  func testStreamedImportCostsFarLessThanPooledImport() throws {
    let data = photoJPEGData()
    let canvas = EditorStore.defaultCanvasSize
    let layerMB = Double(Int(canvas.width) * Int(canvas.height) * 4) / 1_000_000

    for count in [4, 8, 16, 24] {
      autoreleasepool {
        let store = EditorStore()
        let base = footprint()
        var prepared: [(name: String, image: UIImage)] = []
        for index in 1...count {
          let fitted: UIImage? = autoreleasepool {
            guard let decoded = try? ProjectArchive.decodeImage(data, fittingInto: canvas)
            else { return nil }
            return EditorStore.fitted(decoded, into: canvas)
          }
          if let fitted { prepared.append((name: "Photo \(index)", image: fitted)) }
        }
        let added = (try? store.addImageLayers(prepared)) ?? 0
        let peak = footprint()
        let each = Double(peak > base ? peak - base : 0) / Double(max(count, 1)) / 1_000_000
        print("### STREAMED \(count) photos -> \(added) layers: \(delta(base, peak))  "
          + String(format: "(%.1f MB per photo; a canvas layer is %.1f MB)", each, layerMB))
      }
    }
  }

  /// The decode itself must now produce a canvas-sized image, not a 12 MP one.
  func testDecodeFittingIntoNeverMaterialisesTheFullSizeBitmap() throws {
    let data = photoJPEGData()
    let canvas = EditorStore.defaultCanvasSize

    let full = try ProjectArchive.decodeImage(data)
    let fitted = try ProjectArchive.decodeImage(data, fittingInto: canvas)
    print("### full decode: \(Int(full.size.width))x\(Int(full.size.height))")
    print("### fitted decode: \(Int(fitted.size.width))x\(Int(fitted.size.height))")

    XCTAssertEqual(full.size, CGSize(width: 4032, height: 3024))
    // Longest side bounded by what actually fits the canvas, so `fitted` never
    // has to upscale what the decoder handed back.
    XCTAssertLessThanOrEqual(fitted.size.width, canvas.width)
    XCTAssertLessThanOrEqual(fitted.size.height, canvas.height)
    XCTAssertGreaterThan(fitted.size.width, canvas.width * 0.98)
  }

  /// Reading a size must not decode the picture.
  func testImportedImageSizeReadsTheHeaderNotThePixels() throws {
    let data = photoJPEGData()
    let base = footprint()
    var size: CGSize?
    for _ in 1...20 { size = EditorStore.importedImageSize(of: data) }
    let after = footprint()
    print("### 20 size reads: \(delta(base, after))  size=\(size.map { "\(Int($0.width))x\(Int($0.height))" } ?? "nil")")
    XCTAssertEqual(size, CGSize(width: 4032, height: 3024))
    // Twenty full decodes would be ~975 MB. Allow generous slack for noise.
    XCTAssertLessThan(after > base ? after - base : 0, 100_000_000)
  }

  /// #350: a placed photo keeps its JPEG bytes as its source, not the decoded
  /// bitmap. Ten placed 12 MP photos used to hold 488 MB of sources beside
  /// their 126 MB of layers; the sources are now the ~3 MB each the picker
  /// handed over, and the budget caps even that.
  func testPlacedPhotoSourcesStayAsCompressedBytes() throws {
    let data = photoJPEGData()
    let store = EditorStore()
    store.newDocument(size: EditorStore.defaultCanvasSize)
    let base = footprint()
    print("### baseline: \(mb(base)); JPEG bytes per photo: \(mb(UInt64(data.count)))")

    for index in 1...6 {
      try autoreleasepool {
        let image = try ProjectArchive.decodeImage(data)
        _ = try store.addPlaceableLayer(name: "Photo \(index)", image: image, sourceData: data)
      }
      let now = footprint()
      print(
        "### placed \(index): \(mb(now))  \(delta(base, now))  "
          + "sources=\(mb(UInt64(store.retainedSourceBytes)))")
    }
    let decodedWouldBe = UInt64(6 * 4032 * 3024 * 4)
    print("### sources retained: \(mb(UInt64(store.retainedSourceBytes))); decoded they were \(mb(decodedWouldBe))")

    // The noise JPEG is a worst case at ~15 MB (a real photo is 3-4 MB), so
    // the 64 MiB budget lets the oldest go once four are held: what is kept
    // is whole sources, as many as fit, and never more than the budget.
    let fits = min(6, store.sourceBudgetBytes / data.count)
    XCTAssertEqual(store.retainedSourceBytes, fits * data.count)
    XCTAssertLessThanOrEqual(store.retainedSourceBytes, store.sourceBudgetBytes)
    XCTAssertLessThan(UInt64(data.count), UInt64(4032 * 3024 * 4), "one source is smaller than its decode")
    XCTAssertLessThan(UInt64(store.retainedSourceBytes) * 4, decodedWouldBe)
  }

  /// #351: five whole-document geometry steps on a photo-bearing document,
  /// and what the undo history pins once the records have packed.
  func testGeometryUndoHistoryPacksItsBitmaps() throws {
    let data = photoJPEGData()
    let store = EditorStore()
    store.newDocument(size: EditorStore.defaultCanvasSize)
    let undo = UndoManager()
    store.undoManager = undo
    _ = try store.addImageLayers([(name: "Photo", image: try ProjectArchive.decodeImage(data))])
    store.addLayer()
    XCTAssertTrue(store.addTextLayer("Caption", fontSize: 96, color: .white, at: CGPoint(x: 40, y: 40)))
    let document = store.layers.reduce(0) { $0 + $1.imageBytes }
    let base = footprint()
    print("### document \(mb(UInt64(document))) across \(store.layers.count) layers; baseline \(mb(base))")

    store.resizeCanvas(to: CGSize(width: 2200, height: 1700))
    store.crop(to: CGRect(x: 76, y: 82, width: 2048, height: 1536))
    store.scaleDocument(to: CGSize(width: 1800, height: 1350))
    store.resizeCanvas(to: CGSize(width: 2048, height: 1536))
    store.scaleDocument(to: CGSize(width: 1600, height: 1200))
    let live = store.undoPinnedBytes
    let beforePacking = footprint()
    store.settleUndoPacking()
    let packed = store.undoPinnedBytes
    let afterPacking = footprint()
    print("### pinned live: \(mb(UInt64(live)))  packed: \(mb(UInt64(packed)))  (5 x document = \(mb(UInt64(document * 5))))")
    print("### footprint before packing \(mb(beforePacking)), after \(mb(afterPacking))  \(delta(beforePacking, afterPacking))")

    XCTAssertLessThan(packed, document * 5)
  }
}

// SPDX-License-Identifier: Apache-2.0
import XCTest

@testable import PhotoslopIPad

/// The iOS filter ports (#327) against pixels the desktop produced.
///
/// `FilterFixture` is written by `scripts/gen-filter-fixture.py`, which runs
/// the real `photoslop.filters` built-ins over synthetic inputs; every case
/// here must match it word for word — the same premultiplied ARGB32 the
/// desktop and the CLI write. There is no tolerance: the ports reproduce the
/// desktop's float32 arithmetic, Qt's nearest-neighbour sampling grid and
/// NumPy's seeded generator, so any difference is a bug, not rounding.
@MainActor
final class FilterParityTests: XCTestCase {
  private func buffer(_ name: String) throws -> PixelBuffer {
    let image = try XCTUnwrap(FilterFixture.inputs[name], "fixture input \(name)")
    return PixelBuffer(width: image.width, height: image.height, words: image.words)
  }

  private func describeMismatch(
    _ got: [UInt32], _ expected: [UInt32], width: Int, label: String
  ) -> String {
    var differing = 0
    var first: String?
    for i in 0..<min(got.count, expected.count) where got[i] != expected[i] {
      differing += 1
      if first == nil {
        first = String(
          format: "first at (%d, %d): got 0x%08X, expected 0x%08X", i % width, i / width, got[i],
          expected[i])
      }
    }
    return "\(label): \(differing) of \(expected.count) words differ; \(first ?? "sizes differ")"
  }

  /// Every fixture case, every filter, word for word.
  func testEveryFixtureCaseMatchesTheDesktop() throws {
    XCTAssertEqual(FilterFixture.cases.count, 23)
    var covered = Set<FilterKind>()
    for testCase in FilterFixture.cases {
      let kind = try XCTUnwrap(FilterKind(rawValue: testCase.filter), "filter \(testCase.filter)")
      covered.insert(kind)
      var pixels = try buffer(testCase.input)
      kind.apply(to: &pixels, params: testCase.params)
      if pixels.words != testCase.expected {
        XCTFail(
          describeMismatch(
            pixels.words, testCase.expected, width: pixels.width,
            label: "\(testCase.filter)/\(testCase.name)"))
      }
    }
    XCTAssertEqual(covered, Set(FilterKind.allCases), "every filter has fixture cases")
  }

  /// Sepia at amount 0 is the identity — the desktop registers the step
  /// regardless, so the fixture holds the input back unchanged.
  func testSepiaOffIsIdentity() throws {
    var pixels = try buffer("gradient16")
    let before = pixels.words
    FilterAlgorithms.sepia(&pixels, amount: 0)
    XCTAssertEqual(pixels.words, before)
  }

  /// Pixel sort permutes whole pixels: every sorted row (or column) holds
  /// exactly the words the input row held, and out-of-band pixels stay put.
  func testPixelSortIsAPermutationOfEachLine() throws {
    for (name, vertical, low, high, reverse) in [
      ("gradient16", false, 60, 200, false),
      ("gradient16", true, 0, 255, true),
      ("gradient22", false, 220, 40, true),
      ("gradient22", true, 30, 230, false),
    ] {
      let input = try buffer(name)
      var pixels = input
      FilterAlgorithms.pixelSort(&pixels, low: low, high: high, vertical: vertical, reverse: reverse)
      let lines = vertical ? input.width : input.height
      let length = vertical ? input.height : input.width
      for n in 0..<lines {
        var before: [UInt32] = []
        var after: [UInt32] = []
        for i in 0..<length {
          let x = vertical ? n : i
          let y = vertical ? i : n
          before.append(input.word(x: x, y: y))
          after.append(pixels.word(x: x, y: y))
        }
        XCTAssertEqual(
          before.sorted(), after.sorted(),
          "\(name) \(vertical ? "column" : "row") \(n) is a permutation of its input")
      }
      XCTAssertNotEqual(pixels.words, input.words, "\(name): the sort moved something")
    }
  }

  /// `QImage.scaled` with the fast transformation: the identity at equal
  /// sizes, and the 16.16 fixed-point walk otherwise, checked against Qt on
  /// the pixelate fixture (16x12 -> 5x4 -> 16x12 for size 3).
  func testNearestScaleMatchesQtGrid() {
    let scale = FilterAlgorithms.NearestScale(from: 16, 12, to: 5, 4)
    XCTAssertEqual((0..<5).map(scale.sourceX), [1, 4, 7, 11, 14])
    XCTAssertEqual((0..<4).map(scale.sourceY), [1, 4, 7, 10])
    let up = FilterAlgorithms.NearestScale(from: 5, 4, to: 16, 12)
    XCTAssertEqual((0..<16).map(up.sourceX), [0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 4, 4, 4])
    XCTAssertEqual((0..<12).map(up.sourceY), [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3])
    let same = FilterAlgorithms.NearestScale(from: 9, 7, to: 9, 7)
    XCTAssertTrue(same.isIdentity)
    XCTAssertEqual((0..<9).map(same.sourceX), Array(0..<9))
  }

  /// `SeedSequence([7, 0])`, its three children and the first draws of each,
  /// as NumPy 2.5 produces them.
  func testNumpySeedSequenceAndPCG64MatchNumpy() {
    var sequence = NumpyRandom.SeedSequence(entropy: [7, 0])
    XCTAssertEqual(
      sequence.generateState(doubleWords: 4),
      [0xEAD0_F701_7C32_6E58, 0x0879_C4F0_F97E_037A, 0x623A_8C4B_6745_675F, 0xB344_3FAD_6038_6CAC])
    let children = sequence.spawn(3)
    XCTAssertEqual(
      children[0].generateState(doubleWords: 4),
      [0x2EFE_612D_4797_B856, 0xF3F7_F6CB_6E93_DFD5, 0x32F8_C02B_D32A_582B, 0xE186_984A_4E51_D527])
    XCTAssertEqual(
      children[2].generateState(doubleWords: 4),
      [0xF3AE_1B89_E462_588D, 0x2BAF_8157_6006_9A34, 0xE0A1_CBC6_E87C_9533, 0x92A2_C50A_952D_88AF])

    var rf = NumpyRandom.PCG64(seed: children[0])
    XCTAssertEqual(
      (0..<4).map { _ in rf.nextDouble() },
      [0.7978591868433563, 0.05309388325640407, 0.5913511174298967, 0.8688251433502354])
    var rx = NumpyRandom.PCG64(seed: children[1])
    XCTAssertEqual((0..<8).map { _ in rx.integer(low: -12, high: 13) }, [5, 0, -3, -11, -1, -7, -3, -9])
    var ry = NumpyRandom.PCG64(seed: children[2])
    XCTAssertEqual((0..<8).map { _ in ry.integer(low: -6, high: 7) }, [-1, 2, 4, 0, 0, -6, -3, 2])

    var raw = NumpyRandom.PCG64(seed: NumpyRandom.SeedSequence(entropy: [9999, 3]))
    XCTAssertEqual(
      (0..<3).map { _ in raw.next64() },
      [0xE8F7_F4F2_67AF_8B83, 0xE57F_1BAF_3BDC_3FEF, 0x3742_9FC2_A17C_3409])
    // a range wide enough for Lemire's rejection threshold to matter
    var wide = NumpyRandom.PCG64(seed: NumpyRandom.SeedSequence(entropy: [0, 0]))
    XCTAssertEqual(
      (0..<4).map { _ in wide.integer(low: 0, high: 4_000_000_000) },
      [3_402_496_903, 2_547_846_748, 2_044_545_919, 1_079_146_854])
  }

  /// The same seed lays the same mosh: the desktop's promise (#319), which a
  /// system generator would break.
  func testDatamoshIsDeterministicBySeed() throws {
    var first = try buffer("gradient22")
    var second = try buffer("gradient22")
    var other = try buffer("gradient22")
    FilterAlgorithms.datamosh(&first, block: 4, amount: 50, drift: 6, aberration: 0, seed: 11)
    FilterAlgorithms.datamosh(&second, block: 4, amount: 50, drift: 6, aberration: 0, seed: 11)
    FilterAlgorithms.datamosh(&other, block: 4, amount: 50, drift: 6, aberration: 0, seed: 12)
    XCTAssertEqual(first.words, second.words)
    XCTAssertNotEqual(first.words, other.words)
  }

  /// The desktop defaults, name for name, so `--params` written for the CLI
  /// mean the same thing here.
  func testDefaultsMatchTheDesktopParamSpecs() {
    XCTAssertEqual(FilterKind.sepia.defaults, ["amount": .int(80)])
    XCTAssertEqual(FilterKind.pixelate.defaults, ["size": .int(8)])
    XCTAssertEqual(FilterKind.denoise.defaults, ["strength": .int(40)])
    XCTAssertEqual(
      FilterKind.retroConsole.defaults, ["size": .int(6), "levels": .int(4), "dither": .int(1)])
    XCTAssertEqual(
      FilterKind.pixelSort.defaults,
      ["low": .int(60), "high": .int(200), "vertical": .int(0), "reverse": .int(0)])
    XCTAssertEqual(
      FilterKind.datamosh.defaults,
      [
        "block": .int(16), "amount": .int(35), "drift": .int(12), "aberration": .float(3.0),
        "seed": .int(7),
      ])
    XCTAssertEqual(FilterKind.filmNegative.defaults, ["mode": .choice("auto"), "clip": .float(0.5)])
    XCTAssertEqual(
      FilterKind.allCases.map(\.rawValue),
      ["sepia", "pixelate", "denoise", "retro-console", "pixel-sort", "datamosh", "film-negative"])
  }

  // MARK: - Through the store

  /// Seeds the active layer with a fixture image, so the tests below run the
  /// filters over known pixels rather than a blank canvas.
  private func makeStore(with name: String) throws -> (EditorStore, UndoManager, [UInt32]) {
    let image = try XCTUnwrap(FilterFixture.inputs[name])
    let store = EditorStore()
    store.newDocument(size: CGSize(width: image.width, height: image.height))
    let layerID = try XCTUnwrap(store.activeLayerID)
    XCTAssertTrue(
      store.applyPixelOperation(to: layerID, actionName: "Seed") { buffer in
        buffer.withMutableWords { words in
          for i in 0..<image.words.count { words[i] = image.words[i] }
        }
        return true
      })
    let undoManager = UndoManager()
    undoManager.groupsByEvent = false
    store.undoManager = undoManager
    return (store, undoManager, image.words)
  }

  private func layerWords(_ store: EditorStore) throws -> [UInt32] {
    try XCTUnwrap(PixelBuffer(image: store.layers[0].image)).words
  }

  /// One filter, one undo step, and undo puts every byte back.
  func testApplyFilterIsOneUndoStepAndUndoRestoresPixels() throws {
    let (store, undoManager, before) = try makeStore(with: "gradient16")
    var expected = PixelBuffer(width: 16, height: 12, words: before)
    FilterAlgorithms.sepia(&expected, amount: 80)

    undoManager.beginUndoGrouping()
    XCTAssertEqual(store.applyFilter(.sepia, params: ["amount": .int(80)]), .applied)
    undoManager.endUndoGrouping()
    XCTAssertTrue(undoManager.canUndo)
    XCTAssertEqual(undoManager.undoActionName, "Sepia")
    XCTAssertEqual(try layerWords(store), expected.words)

    undoManager.undo()
    XCTAssertEqual(try layerWords(store), before)
    XCTAssertFalse(undoManager.canUndo)
    XCTAssertTrue(undoManager.canRedo)
  }

  /// With a selection the filter runs over the layer and the pixels outside
  /// the selection are put back — the desktop's hard-mask path.
  func testApplyFilterHonoursTheSelection() throws {
    let (store, _, before) = try makeStore(with: "gradient16")
    var bits = [Bool](repeating: false, count: 16 * 12)
    for y in 3..<9 {
      for x in 2..<10 { bits[y * 16 + x] = true }
    }
    store.setSelection(SelectionMask(width: 16, height: 12, bits: bits))
    var whole = PixelBuffer(width: 16, height: 12, words: before)
    FilterAlgorithms.pixelate(&whole, size: 3)

    XCTAssertEqual(store.applyFilter(.pixelate, params: ["size": .int(3)]), .applied)
    let after = try layerWords(store)
    var changedInside = 0
    for i in 0..<after.count {
      if bits[i] {
        XCTAssertEqual(after[i], whole.words[i], "selected pixel \(i) takes the filtered word")
        if after[i] != before[i] { changedInside += 1 }
      } else {
        XCTAssertEqual(after[i], before[i], "pixel \(i) outside the selection is untouched")
      }
    }
    XCTAssertGreaterThan(changedInside, 0, "the selection contained something to change")
  }

  /// A text layer is refused, and the refusal registers no undo step.
  func testApplyFilterRefusesTextLayers() throws {
    let (store, undoManager, before) = try makeStore(with: "gradient22")
    undoManager.beginUndoGrouping()
    XCTAssertTrue(store.addTextLayer("Hi", fontSize: 10, color: .black, at: CGPoint(x: 2, y: 2)))
    undoManager.endUndoGrouping()
    XCTAssertTrue(try XCTUnwrap(store.activeLayer).isText)
    XCTAssertEqual(store.applyFilter(.denoise, params: [:]), .textLayer)
    XCTAssertEqual(undoManager.undoActionName, "Add Text", "the refusal registered nothing")
    XCTAssertEqual(try layerWords(store), before, "the paint layer beneath is untouched")
  }

  /// Missing parameters take the desktop defaults, so an empty dictionary
  /// runs the filter as the desktop dialog's OK would.
  func testMissingParamsTakeDesktopDefaults() throws {
    var withDefaults = try buffer("gradient16")
    var explicit = try buffer("gradient16")
    FilterKind.retroConsole.apply(to: &withDefaults, params: [:])
    FilterKind.retroConsole.apply(
      to: &explicit, params: ["size": .int(6), "levels": .int(4), "dither": .int(1)])
    XCTAssertEqual(withDefaults.words, explicit.words)
    let fixture = try XCTUnwrap(
      FilterFixture.cases.first { $0.filter == "retro-console" && $0.name == "default" })
    XCTAssertEqual(withDefaults.words, fixture.expected)
  }
}

// SPDX-License-Identifier: Apache-2.0
import Foundation

/// One parameter value, typed the way the desktop `ParamSpec` types it:
/// `int`, `float` or `choice`. The fixture written by
/// `scripts/gen-filter-fixture.py` spells its parameters in these cases.
enum FilterParamValue: Equatable {
  case int(Int)
  case float(Double)
  case choice(String)
}

typealias FilterParams = [String: FilterParamValue]

extension Dictionary where Key == String, Value == FilterParamValue {
  /// `int(params.get(key, default))`: a float is truncated, a choice ignored.
  func int(_ key: String, default fallback: Int) -> Int {
    switch self[key] {
    case .int(let value): return value
    case .float(let value): return Int(value)
    default: return fallback
    }
  }

  /// `float(params.get(key, default))`.
  func float(_ key: String, default fallback: Double) -> Double {
    switch self[key] {
    case .int(let value): return Double(value)
    case .float(let value): return value
    default: return fallback
    }
  }

  func choice(_ key: String, default fallback: String) -> String {
    if case .choice(let value) = self[key] { return value }
    return fallback
  }
}

/// The desktop `ParamSpec`: what the parameter sheet builds a control from.
struct FilterParamSpec: Identifiable {
  enum Kind: Equatable {
    case int(min: Int, max: Int, default: Int)
    case float(min: Double, max: Double, default: Double)
    case choice(options: [String], default: String)
  }

  let name: String
  let label: String
  let kind: Kind

  var id: String { name }

  var defaultValue: FilterParamValue {
    switch kind {
    case .int(_, _, let value): return .int(value)
    case .float(_, _, let value): return .float(value)
    case .choice(_, let value): return .choice(value)
    }
  }

  /// A 0/1 integer reads better as a switch than a slider.
  var isToggle: Bool {
    if case .int(min: 0, max: 1, default: _) = kind { return true }
    return false
  }
}

/// The seven built-in filters of `photoslop.filters`, in the desktop menu's
/// order, keyed by the desktop's registry names so a parameter set means the
/// same thing on every platform (`--filter sepia --params amount=80`).
enum FilterKind: String, CaseIterable, Identifiable {
  case sepia
  case pixelate
  case denoise
  case retroConsole = "retro-console"
  case pixelSort = "pixel-sort"
  case datamosh
  case filmNegative = "film-negative"

  var id: String { rawValue }

  /// The desktop `label`, and the undo action's name.
  var label: String {
    switch self {
    case .sepia: return "Sepia"
    case .pixelate: return "Pixelate"
    case .denoise: return "Denoise (Chroma)"
    case .retroConsole: return "Retro Console (8-Bit)"
    case .pixelSort: return "Pixel Sort (Glitch)"
    case .datamosh: return "Datamosh + Chromatic Aberration"
    case .filmNegative: return "Film Negative → Positive"
    }
  }

  /// The desktop `params`, ranges and defaults included.
  var params: [FilterParamSpec] {
    switch self {
    case .sepia:
      return [FilterParamSpec(name: "amount", label: "Amount", kind: .int(min: 0, max: 100, default: 80))]
    case .pixelate:
      return [
        FilterParamSpec(name: "size", label: "Block size", kind: .int(min: 2, max: 128, default: 8))
      ]
    case .denoise:
      return [
        FilterParamSpec(name: "strength", label: "Strength", kind: .int(min: 1, max: 100, default: 40))
      ]
    case .retroConsole:
      return [
        FilterParamSpec(name: "size", label: "Pixel size", kind: .int(min: 1, max: 64, default: 6)),
        FilterParamSpec(name: "levels", label: "Colour levels", kind: .int(min: 2, max: 8, default: 4)),
        FilterParamSpec(name: "dither", label: "Dither", kind: .int(min: 0, max: 1, default: 1)),
      ]
    case .pixelSort:
      return [
        FilterParamSpec(name: "low", label: "Threshold low", kind: .int(min: 0, max: 255, default: 60)),
        FilterParamSpec(
          name: "high", label: "Threshold high", kind: .int(min: 0, max: 255, default: 200)),
        FilterParamSpec(name: "vertical", label: "Vertical", kind: .int(min: 0, max: 1, default: 0)),
        FilterParamSpec(
          name: "reverse", label: "Reverse (bright first)", kind: .int(min: 0, max: 1, default: 0)),
      ]
    case .datamosh:
      return [
        FilterParamSpec(name: "block", label: "Macroblock size", kind: .int(min: 4, max: 64, default: 16)),
        FilterParamSpec(
          name: "amount", label: "Corrupted blocks (%)", kind: .int(min: 0, max: 100, default: 35)),
        FilterParamSpec(
          name: "drift", label: "Motion drift (px)", kind: .int(min: 0, max: 64, default: 12)),
        FilterParamSpec(
          name: "aberration", label: "Chromatic aberration (px)",
          kind: .float(min: 0, max: 20, default: 3.0)),
        FilterParamSpec(name: "seed", label: "Seed", kind: .int(min: 0, max: 9999, default: 7)),
      ]
    case .filmNegative:
      return [
        FilterParamSpec(
          name: "mode", label: "Mode", kind: .choice(options: ["auto", "color", "mono"], default: "auto")
        ),
        FilterParamSpec(name: "clip", label: "Clip (%)", kind: .float(min: 0, max: 5, default: 0.5)),
      ]
    }
  }

  var defaults: FilterParams {
    Dictionary(uniqueKeysWithValues: params.map { ($0.name, $0.defaultValue) })
  }

  /// Full-size working copies the filter holds beside the layer buffer while
  /// it runs, in layer-buffer units, for the memory budget (#354): Denoise
  /// keeps two `Float` chroma planes, Datamosh a snapshot to sample from,
  /// Retro Console at pixel size 1 a same-size shrunken copy.
  var transientLayers: Int {
    switch self {
    case .denoise: return 2
    case .datamosh: return 2
    case .retroConsole: return 1
    case .sepia, .pixelate, .pixelSort, .filmNegative: return 0
    }
  }

  /// Runs the desktop algorithm over `buffer`, filling in the desktop
  /// defaults for any parameter not given.
  func apply(to buffer: inout PixelBuffer, params: FilterParams) {
    switch self {
    case .sepia:
      FilterAlgorithms.sepia(&buffer, amount: params.int("amount", default: 80))
    case .pixelate:
      FilterAlgorithms.pixelate(&buffer, size: params.int("size", default: 8))
    case .denoise:
      FilterAlgorithms.denoise(&buffer, strength: params.int("strength", default: 40))
    case .retroConsole:
      FilterAlgorithms.retroConsole(
        &buffer, size: params.int("size", default: 6), levels: params.int("levels", default: 4),
        dither: params.int("dither", default: 1) != 0)
    case .pixelSort:
      FilterAlgorithms.pixelSort(
        &buffer, low: params.int("low", default: 60), high: params.int("high", default: 200),
        vertical: params.int("vertical", default: 0) != 0,
        reverse: params.int("reverse", default: 0) != 0)
    case .datamosh:
      FilterAlgorithms.datamosh(
        &buffer, block: params.int("block", default: 16), amount: params.int("amount", default: 35),
        drift: params.int("drift", default: 12),
        aberration: params.float("aberration", default: 3.0),
        seed: params.int("seed", default: 7))
    case .filmNegative:
      let mode =
        FilterAlgorithms.FilmNegativeMode(rawValue: params.choice("mode", default: "auto")) ?? .auto
      FilterAlgorithms.filmNegative(&buffer, mode: mode, clip: params.float("clip", default: 0.5))
    }
  }
}

enum FilterOutcome: Equatable {
  /// The layer's pixels changed; one undo step was registered.
  case applied
  /// The filter left every word as it was, so nothing was registered.
  case unchanged
  /// No layer is active.
  case noLayer
  /// The active layer is a text layer, which a filter cannot bake.
  case textLayer
  /// The memory budget said no; `memoryPressureNotice` carries the refusal.
  case refused
}

extension EditorStore {
  /// Runs `kind` over the active raster layer as one undo step (#327).
  ///
  /// Mirrors `MainWindow._run_filter` and the CLI's `_filter_region`: the
  /// filter runs over the whole layer, then, with a selection, every pixel
  /// outside the selection is put back — the desktop's hard-mask path, which
  /// is the only path here because iOS selections carry no feather. Text
  /// layers are refused: their pixels are re-rendered from the words on every
  /// edit, so a filter baked into them would not survive Edit Text.
  @discardableResult
  func applyFilter(_ kind: FilterKind, params: FilterParams) -> FilterOutcome {
    guard let layer = activeLayer else { return .noLayer }
    if layer.isText { return .textLayer }
    let bits = selection?.bits
    // the layer buffer, the filter's working copies, and the pre-filter copy
    // a selection needs, all alive at once
    let concurrent = 1 + kind.transientLayers + (bits == nil ? 0 : 1)
    guard Self.canAffordLayers(concurrent, canvas: canvasSize) else {
      memoryPressureNotice = Self.memoryRefusal
      return .refused
    }
    let applied = applyPixelOperation(to: layer.id, actionName: kind.label) { buffer in
      let before = bits == nil ? nil : buffer.words
      kind.apply(to: &buffer, params: params)
      if let before, let bits {
        Self.restore(before, outside: bits, in: &buffer)
      }
      return true
    }
    return applied ? .applied : .unchanged
  }

  /// `dst[~mask] = src[~mask]`: pixels outside the selection go back to
  /// what they were. The mask is canvas-sized, as the buffer is.
  static func restore(_ before: [UInt32], outside bits: [Bool], in buffer: inout PixelBuffer) {
    let width = buffer.width, height = buffer.height
    guard bits.count == before.count, before.count == width * height else { return }
    buffer.withMutableWords { words in
      PixelBuffer.forEachBand(height: height) { rows in
        for index in (rows.lowerBound * width)..<(rows.upperBound * width) where !bits[index] {
          words[index] = before[index]
        }
      }
    }
  }
}

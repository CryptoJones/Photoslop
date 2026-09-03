// SPDX-License-Identifier: Apache-2.0
import Foundation

/// One live appearance effect on a layer — the iOS mirror of a normalised
/// `photoslop.appearance` effect dict (#316).
///
/// This is a port of the desktop's vocabulary, not a second one. The kind
/// names (`drop-shadow`, `bevel-emboss`, …), the parameter names, their
/// defaults and clamps, and the JSON shape are `appearance.py`'s exactly, so a
/// document carrying effects means the same thing on both platforms and the
/// `photoslop-effects` attribute a desktop `.ora` writes could be read here
/// unchanged. The keys are therefore snake_case, unlike the rest of the
/// manifest, which is the price of keeping the shape identical.
///
/// Effects are data, never pixels: the compositor renders them from the
/// layer's alpha on every composite (`AppearanceRenderer`), so editing the
/// words or size of a text layer re-renders its shadow rather than stranding
/// it. Only Flatten Image and export bake them in.
struct LayerEffect: Codable, Equatable, Identifiable {
  /// `appearance.SCHEMA_VERSION`.
  static let schemaVersion = 1

  var schemaVersion: Int
  /// A UUID as 32 hex digits, the way `uuid.uuid4().hex` writes one.
  var id: String
  /// The desktop's `type`: one of `LayerEffect.defaults`' keys.
  var kind: String
  var enabled: Bool
  var blendMode: String
  var opacity: Double
  var parameters: [String: JSONValue]
  /// Unknown top-level keys, preserved but never interpreted — the desktop
  /// keeps them under `extensions` and so do we, so a round trip loses nothing.
  var extensions: [String: JSONValue]?

  enum CodingKeys: String, CodingKey, CaseIterable {
    case schemaVersion = "schema_version"
    case id
    case kind = "type"
    case enabled
    case blendMode = "blend_mode"
    case opacity
    case parameters
    case extensions
  }

  /// `appearance.EFFECT_DEFAULTS`, verbatim.
  static let defaults: [String: [String: JSONValue]] = [
    "drop-shadow": [
      "offset_x": 6, "offset_y": 6, "blur": 8, "spread": 0, "color": .rgba(0, 0, 0, 153),
    ],
    "inner-shadow": [
      "offset_x": 3, "offset_y": 3, "blur": 5, "spread": 0, "color": .rgba(0, 0, 0, 140),
    ],
    "outer-glow": ["size": 10, "spread": 0, "color": .rgba(255, 220, 120, 200)],
    "inner-glow": [
      "size": 8, "choke": 0, "source": "edge", "color": .rgba(255, 255, 255, 180),
    ],
    "outline": ["width": 3, "position": "outside", "color": .rgba(0, 0, 0, 255)],
    "color-overlay": ["color": .rgba(255, 255, 255, 255)],
    "gradient-overlay": [
      "color1": .rgba(255, 255, 255, 255),
      "color2": .rgba(0, 0, 0, 255),
      "angle": 90,
      "scale": 100,
      "offset_x": 0,
      "offset_y": 0,
      "reverse": false,
    ],
    "bevel-emboss": [
      "style": "inner-bevel",
      "depth": 100,
      "size": 5,
      "soften": 1,
      "angle": 120,
      "altitude": 30,
      "highlight_color": .rgba(255, 255, 255, 190),
      "shadow_color": .rgba(0, 0, 0, 160),
    ],
    "gaussian-blur": ["radius": 5],
    "feather": ["radius": 5],
  ]

  /// `appearance.EFFECT_LABELS`.
  static let labels: [String: String] = [
    "drop-shadow": "Drop Shadow",
    "inner-shadow": "Inner Shadow",
    "outer-glow": "Outer Glow",
    "inner-glow": "Inner Glow",
    "outline": "Outline",
    "color-overlay": "Color Overlay",
    "gradient-overlay": "Gradient Overlay",
    "bevel-emboss": "Bevel / Emboss",
    "gaussian-blur": "Gaussian Blur",
    "feather": "Feather",
  ]

  /// The kinds `AppearanceRenderer` draws, in the order the picker offers them.
  ///
  /// Gaussian Blur and Feather are the desktop's two *fill-replacing* effects:
  /// they run `npimage.gaussian_blur` over the layer's RGBA rather than
  /// colourising its alpha, which is a different algorithm from the plane
  /// pipeline below. A document carrying one keeps it (the data survives
  /// untouched) but the iOS composite draws the fill unblurred.
  static let renderableKinds = [
    "drop-shadow", "inner-shadow", "outer-glow", "inner-glow", "outline",
    "color-overlay", "gradient-overlay", "bevel-emboss",
  ]

  /// `photoslop.layer.BLEND_MODES`' names, in the desktop's order.
  static let blendModes = [
    "normal", "multiply", "screen", "overlay", "darken", "lighten", "color-dodge",
    "color-burn", "hard-light", "soft-light", "difference", "exclusion", "addition",
  ]

  var label: String { Self.labels[kind] ?? kind }

  /// `appearance.new_effect`: the kind's defaults with `parameters` laid over
  /// them, normalised. Nil for a kind the desktop does not know.
  init?(kind: String, parameters: [String: JSONValue] = [:]) {
    guard let defaults = Self.defaults[kind] else { return nil }
    var merged = defaults
    merged.merge(parameters) { _, incoming in incoming }
    self.init(
      schemaVersion: Self.schemaVersion,
      id: UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(),
      kind: kind, enabled: true, blendMode: "normal", opacity: 1, parameters: merged,
      extensions: nil)
    self = normalized()
  }

  init(
    schemaVersion: Int, id: String, kind: String, enabled: Bool, blendMode: String,
    opacity: Double, parameters: [String: JSONValue], extensions: [String: JSONValue]?
  ) {
    self.schemaVersion = schemaVersion
    self.id = id
    self.kind = kind
    self.enabled = enabled
    self.blendMode = blendMode
    self.opacity = opacity
    self.parameters = parameters
    self.extensions = extensions
  }

  /// Decode leniently, the way `normalize_effect` reads: a missing field takes
  /// its default, and unknown top-level keys land in `extensions`.
  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    let kind = try container.decodeIfPresent(String.self, forKey: .kind) ?? ""
    guard Self.defaults[kind] != nil else {
      throw DecodingError.dataCorruptedError(
        forKey: .kind, in: container, debugDescription: "Unknown appearance effect: \(kind)")
    }
    self.kind = kind
    schemaVersion = try container.decodeIfPresent(Int.self, forKey: .schemaVersion)
      ?? Self.schemaVersion
    id = try container.decodeIfPresent(String.self, forKey: .id) ?? ""
    enabled = try container.decodeIfPresent(Bool.self, forKey: .enabled) ?? true
    blendMode = try container.decodeIfPresent(String.self, forKey: .blendMode) ?? "normal"
    opacity = try container.decodeIfPresent(Double.self, forKey: .opacity) ?? 1
    parameters = try container.decodeIfPresent([String: JSONValue].self, forKey: .parameters)
      ?? [:]
    var extensions = try container.decodeIfPresent(
      [String: JSONValue].self, forKey: .extensions) ?? [:]
    let known = Set(CodingKeys.allCases.map(\.stringValue))
    let loose = try decoder.container(keyedBy: AnyCodingKey.self)
    for key in loose.allKeys where !known.contains(key.stringValue) {
      extensions[key.stringValue] = try loose.decode(JSONValue.self, forKey: key)
    }
    self.extensions = extensions.isEmpty ? nil : extensions
    self = normalized()
  }

  func encode(to encoder: Encoder) throws {
    var container = encoder.container(keyedBy: CodingKeys.self)
    try container.encode(schemaVersion, forKey: .schemaVersion)
    try container.encode(id, forKey: .id)
    try container.encode(kind, forKey: .kind)
    try container.encode(enabled, forKey: .enabled)
    try container.encode(blendMode, forKey: .blendMode)
    try container.encode(opacity, forKey: .opacity)
    try container.encode(parameters, forKey: .parameters)
    if let extensions, !extensions.isEmpty {
      try container.encode(extensions, forKey: .extensions)
    }
  }

  /// `appearance.normalize_effect`, clamp for clamp.
  ///
  /// Every parameter the kind defines is coerced to its type and range and a
  /// missing one takes the default; a parameter the kind does not define is
  /// preserved without being interpreted, so a future desktop parameter
  /// survives a trip through an older app. An unreadable colour or number
  /// falls back to the default rather than failing the whole effect.
  func normalized() -> LayerEffect {
    guard let defaults = Self.defaults[kind] else { return self }
    var params = defaults
    params.merge(parameters) { _, incoming in incoming }
    for (key, fallback) in defaults {
      let value = params[key] ?? fallback
      if key.hasSuffix("color") || key == "color1" || key == "color2" {
        params[key] = .rgba(value.rgba ?? fallback.rgba ?? [0, 0, 0, 255])
      } else if key == "reverse" {
        params[key] = .bool(value.truthy)
      } else if key == "source" || key == "position" || key == "style" {
        params[key] = .string(value.stringValue)
      } else if key.hasPrefix("offset_") {
        params[key] = .number(Self.number(value, -10_000, 10_000, fallback.doubleValue ?? 0))
      } else if key == "angle" {
        params[key] = .number(Self.number(value, 0, 360, fallback.doubleValue ?? 0))
      } else if key == "scale" || key == "depth" {
        params[key] = .number(Self.number(value, 1, 1_000, fallback.doubleValue ?? 1))
      } else {
        params[key] = .number(Self.number(value, 0, 1_000, fallback.doubleValue ?? 0))
      }
    }
    var result = self
    result.schemaVersion = Self.schemaVersion
    if result.id.isEmpty {
      result.id = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    }
    result.blendMode = Self.blendModes.contains(blendMode) ? blendMode : "normal"
    result.opacity = Self.number(.number(opacity), 0, 1, 1)
    result.parameters = params
    if let extensions, extensions.isEmpty { result.extensions = nil }
    return result
  }

  /// `appearance._number`: clamp, or the default when the value is not one.
  static func number(_ value: JSONValue, _ low: Double, _ high: Double, _ fallback: Double)
    -> Double
  {
    guard let number = value.doubleValue, number.isFinite else { return fallback }
    return max(low, min(high, number))
  }

  /// `appearance.normalize_effects`: every readable effect, in order, with the
  /// unreadable ones dropped rather than failing the document.
  static func normalized(_ values: [JSONValue]) -> [LayerEffect] {
    values.compactMap { value in
      guard let data = try? JSONEncoder().encode(value) else { return nil }
      return try? JSONDecoder().decode(LayerEffect.self, from: data)
    }
  }

  // MARK: Typed parameter access

  func number(_ key: String) -> Double {
    parameters[key]?.doubleValue ?? Self.defaults[kind]?[key]?.doubleValue ?? 0
  }

  func rgba(_ key: String) -> [Int] {
    parameters[key]?.rgba ?? Self.defaults[kind]?[key]?.rgba ?? [0, 0, 0, 255]
  }

  func string(_ key: String) -> String {
    parameters[key]?.stringValue ?? Self.defaults[kind]?[key]?.stringValue ?? ""
  }

  func bool(_ key: String) -> Bool {
    parameters[key]?.truthy ?? Self.defaults[kind]?[key]?.truthy ?? false
  }

  // MARK: Presets

  /// `appearance.BUILTIN_PRESETS`, in the desktop's order. Picking one
  /// replaces the stack, as the desktop text dialog's preset menu does.
  static let presets: [(name: String, effects: [LayerEffect])] = [
    ("Lifted", [
      LayerEffect(kind: "drop-shadow", parameters: ["offset_x": 5, "offset_y": 7, "blur": 10])!,
    ]),
    ("Sticker", [
      LayerEffect(kind: "drop-shadow", parameters: ["offset_x": 4, "offset_y": 5, "blur": 5])!,
      LayerEffect(kind: "outline", parameters: ["width": 6, "color": .rgba(255, 255, 255, 255)])!,
    ]),
    ("Neon", [
      LayerEffect(
        kind: "outer-glow", parameters: ["size": 16, "spread": 2, "color": .rgba(0, 220, 255, 230)]
      )!,
      LayerEffect(kind: "inner-glow", parameters: ["size": 5, "color": .rgba(255, 255, 255, 210)])!,
    ]),
    ("Letterpress", [
      LayerEffect(kind: "inner-shadow", parameters: ["offset_x": 2, "offset_y": 2, "blur": 3])!,
      LayerEffect(kind: "bevel-emboss", parameters: ["depth": 60, "size": 2])!,
    ]),
    ("Chrome", [
      LayerEffect(
        kind: "gradient-overlay",
        parameters: ["color1": .rgba(245, 250, 255, 255), "color2": .rgba(45, 65, 90, 255)])!,
      LayerEffect(kind: "bevel-emboss", parameters: ["depth": 180, "size": 5])!,
    ]),
    ("Soft Focus", [
      LayerEffect(kind: "gaussian-blur", parameters: ["radius": 2])!,
      LayerEffect(kind: "outer-glow", parameters: ["size": 8, "color": .rgba(255, 255, 255, 130)])!,
    ]),
  ]

  /// A preset's stack with fresh ids, the way the desktop re-`new_effect`s
  /// each entry so two layers given the same preset do not share ids.
  static func preset(named name: String) -> [LayerEffect]? {
    presets.first { $0.name == name }?.effects.compactMap {
      LayerEffect(kind: $0.kind, parameters: $0.parameters)
    }
  }
}

/// A JSON value, kept as-is so effect parameters the app does not understand
/// survive a round trip through it.
indirect enum JSONValue: Codable, Equatable {
  case null
  case bool(Bool)
  case number(Double)
  case string(String)
  case array([JSONValue])
  case object([String: JSONValue])

  static func rgba(_ r: Int, _ g: Int, _ b: Int, _ a: Int) -> JSONValue {
    .array([.number(Double(r)), .number(Double(g)), .number(Double(b)), .number(Double(a))])
  }

  static func rgba(_ values: [Int]) -> JSONValue {
    .array(values.map { .number(Double($0)) })
  }

  var doubleValue: Double? {
    switch self {
    case .number(let value): return value
    case .bool(let value): return value ? 1 : 0
    case .string(let value): return Double(value)
    default: return nil
    }
  }

  var stringValue: String {
    switch self {
    case .string(let value): return value
    case .number(let value):
      return value == value.rounded() && abs(value) < 1e15
        ? String(Int(value)) : String(value)
    case .bool(let value): return value ? "True" : "False"
    case .null: return "None"
    default: return ""
    }
  }

  /// Python truthiness, which is what `bool(params[key])` applies.
  var truthy: Bool {
    switch self {
    case .null: return false
    case .bool(let value): return value
    case .number(let value): return value != 0
    case .string(let value): return !value.isEmpty
    case .array(let values): return !values.isEmpty
    case .object(let values): return !values.isEmpty
    }
  }

  /// `appearance._rgba`: three or four channels, each clamped to 0...255 and
  /// truncated; a missing alpha is opaque. Nil when the value is not a colour.
  var rgba: [Int]? {
    guard case .array(let items) = self, (3...4).contains(items.count) else { return nil }
    let channels = items.map { item -> Int in
      guard let number = item.doubleValue, number.isFinite else { return 0 }
      return Int(max(0, min(255, number)))
    }
    return channels.count == 4 ? channels : channels + [255]
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.singleValueContainer()
    if container.decodeNil() {
      self = .null
    } else if let value = try? container.decode(Bool.self) {
      self = .bool(value)
    } else if let value = try? container.decode(Double.self) {
      self = .number(value)
    } else if let value = try? container.decode(String.self) {
      self = .string(value)
    } else if let value = try? container.decode([JSONValue].self) {
      self = .array(value)
    } else if let value = try? container.decode([String: JSONValue].self) {
      self = .object(value)
    } else {
      throw DecodingError.dataCorruptedError(
        in: container, debugDescription: "Not a JSON value")
    }
  }

  func encode(to encoder: Encoder) throws {
    var container = encoder.singleValueContainer()
    switch self {
    case .null: try container.encodeNil()
    case .bool(let value): try container.encode(value)
    case .number(let value):
      // Whole numbers as integers, so `"blur": 8` stays `8` across a save,
      // not `8.0` — the same text a desktop `json.dumps` of an int writes.
      if value == value.rounded(), abs(value) < 1e15 {
        try container.encode(Int(value))
      } else {
        try container.encode(value)
      }
    case .string(let value): try container.encode(value)
    case .array(let value): try container.encode(value)
    case .object(let value): try container.encode(value)
    }
  }
}

extension JSONValue: ExpressibleByIntegerLiteral, ExpressibleByFloatLiteral,
  ExpressibleByStringLiteral, ExpressibleByBooleanLiteral
{
  init(integerLiteral value: Int) { self = .number(Double(value)) }
  init(floatLiteral value: Double) { self = .number(value) }
  init(stringLiteral value: String) { self = .string(value) }
  init(booleanLiteral value: Bool) { self = .bool(value) }
}

/// A coding key for any string, used to sweep up the unknown keys of an effect.
struct AnyCodingKey: CodingKey {
  var stringValue: String
  var intValue: Int? { nil }
  init?(stringValue: String) { self.stringValue = stringValue }
  init?(intValue: Int) { nil }
}

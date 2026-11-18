// SPDX-License-Identifier: Apache-2.0
//
// SwatchPalette.swift — Adobe .aco and .ase swatch palette codec and models (#421).
//

import Foundation
import UIKit
import SwiftUI

// MARK: - Swatch Errors

public enum SwatchError: LocalizedError, Equatable {
  case emptyData
  case fileTooShort
  case invalidSignature
  case unsupportedVersion(String)
  case excessiveCount(Int)
  case truncatedData(String)
  case unsupportedColorModel(String)
  case invalidNameLength

  public var errorDescription: String? {
    switch self {
    case .emptyData:
      return "Palette data is empty."
    case .fileTooShort:
      return "File is too short to be a valid swatch palette."
    case .invalidSignature:
      return "Invalid file signature (expected ASEF)."
    case .unsupportedVersion(let ver):
      return "Unsupported swatch format version: \(ver)."
    case .excessiveCount(let count):
      return "Swatch count exceeds safe limit: \(count)."
    case .truncatedData(let detail):
      return "Truncated swatch stream: \(detail)."
    case .unsupportedColorModel(let model):
      return "Unsupported color model: \(model)."
    case .invalidNameLength:
      return "Invalid swatch name length."
    }
  }
}

// MARK: - Color Conversion Helpers

public enum SwatchColorSpace {
  /// CIE L*a*b* to sRGB (D65 illuminant).
  public static func labToRGB(l: Double, a: Double, b: Double) -> (r: Double, g: Double, b: Double) {
    let fy = (l + 16.0) / 116.0
    let fx = a / 500.0 + fy
    let fz = fy - b / 200.0

    let delta = 6.0 / 29.0
    let factor = 3.0 * (delta * delta)

    let xr = fx > delta ? (fx * fx * fx) : (fx - 4.0 / 29.0) * factor
    let yr = fy > delta ? (fy * fy * fy) : (fy - 4.0 / 29.0) * factor
    let zr = fz > delta ? (fz * fz * fz) : (fz - 4.0 / 29.0) * factor

    let x = xr * 0.95047
    let y = yr * 1.00000
    let z = zr * 1.08883

    let rLin =  3.2404542 * x - 1.5371385 * y - 0.4985314 * z
    let gLin = -0.9692660 * x + 1.8760108 * y + 0.0415560 * z
    let bLin =  0.0556434 * x - 0.2040259 * y + 1.0572252 * z

    func compand(_ c: Double) -> Double {
      if c <= 0.0031308 {
        return 12.92 * c
      }
      return 1.055 * pow(max(0.0, c), 1.0 / 2.4) - 0.055
    }

    let r = max(0.0, min(1.0, compand(rLin)))
    let g = max(0.0, min(1.0, compand(gLin)))
    let bl = max(0.0, min(1.0, compand(bLin)))
    return (r, g, bl)
  }

  /// sRGB to CIE L*a*b* (D65).
  public static func rgbToLab(r: Double, g: Double, b: Double) -> (l: Double, a: Double, b: Double) {
    func invCompand(_ c: Double) -> Double {
      if c <= 0.04045 {
        return c / 12.92
      }
      return pow((c + 0.055) / 1.055, 2.4)
    }

    let rLin = invCompand(r)
    let gLin = invCompand(g)
    let bLin = invCompand(b)

    let x = (0.4124564 * rLin + 0.3575761 * gLin + 0.1804375 * bLin) / 0.95047
    let y = (0.2126729 * rLin + 0.7151522 * gLin + 0.0721750 * bLin) / 1.00000
    let z = (0.0193339 * rLin + 0.1191920 * gLin + 0.9503041 * bLin) / 1.08883

    let delta = 6.0 / 29.0
    let delta3 = delta * delta * delta
    let invFactor = 1.0 / (3.0 * delta * delta)

    func f(_ t: Double) -> Double {
      if t > delta3 {
        return pow(t, 1.0 / 3.0)
      }
      return t * invFactor + 4.0 / 29.0
    }

    let fx = f(x)
    let fy = f(y)
    let fz = f(z)

    let lVal = 116.0 * fy - 16.0
    let aVal = 500.0 * (fx - fy)
    let bVal = 200.0 * (fy - fz)
    return (lVal, aVal, bVal)
  }

  /// CMYK to sRGB.
  public static func cmykToRGB(c: Double, m: Double, y: Double, k: Double) -> (r: Double, g: Double, b: Double) {
    let r = (1.0 - c) * (1.0 - k)
    let g = (1.0 - m) * (1.0 - k)
    let b = (1.0 - y) * (1.0 - k)
    return (max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)))
  }

  /// sRGB to CMYK.
  public static func rgbToCMYK(r: Double, g: Double, b: Double) -> (c: Double, m: Double, y: Double, k: Double) {
    let k = 1.0 - max(r, max(g, b))
    if k >= 0.99999 {
      return (0.0, 0.0, 0.0, 1.0)
    }
    let c = (1.0 - r - k) / (1.0 - k)
    let m = (1.0 - g - k) / (1.0 - k)
    let y = (1.0 - b - k) / (1.0 - k)
    return (max(0.0, min(1.0, c)), max(0.0, min(1.0, m)), max(0.0, min(1.0, y)), max(0.0, min(1.0, k)))
  }
}

// MARK: - Swatch Types & Models

public enum SwatchColorType: Int, Codable, Equatable, Sendable {
  case global = 0
  case spot = 1
  case process = 2
}

public struct Swatch: Identifiable, Equatable, Sendable {
  public let id: UUID
  public var name: String
  public var color: UIColor
  public var colorModel: String
  public var values: [Double]
  public var colorType: SwatchColorType

  public init(
    id: UUID = UUID(),
    name: String,
    color: UIColor,
    colorModel: String = "RGB",
    values: [Double] = [],
    colorType: SwatchColorType = .process
  ) {
    self.id = id
    self.name = name
    self.color = color
    self.colorModel = colorModel
    self.values = values.isEmpty ? Swatch.extractValues(from: color, model: colorModel) : values
    self.colorType = colorType
  }

  private static func extractValues(from uiColor: UIColor, model: String) -> [Double] {
    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
    uiColor.getRed(&r, green: &g, blue: &b, alpha: &a)
    switch model.uppercased() {
    case "CMYK":
      let cmyk = SwatchColorSpace.rgbToCMYK(r: Double(r), g: Double(g), b: Double(b))
      return [cmyk.c, cmyk.m, cmyk.y, cmyk.k]
    case "LAB":
      let lab = SwatchColorSpace.rgbToLab(r: Double(r), g: Double(g), b: Double(b))
      return [lab.l, lab.a, lab.b]
    case "GRAY":
      return [Double(r * 0.299 + g * 0.587 + b * 0.114)]
    case "HSB":
      var h: CGFloat = 0, s: CGFloat = 0, br: CGFloat = 0
      uiColor.getHue(&h, saturation: &s, brightness: &br, alpha: &a)
      return [Double(h), Double(s), Double(br)]
    default:
      return [Double(r), Double(g), Double(b)]
    }
  }

  public func toRGB() -> (r: Int, g: Int, b: Int) {
    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
    color.getRed(&r, green: &g, blue: &b, alpha: &a)
    return (Int(round(r * 255)), Int(round(g * 255)), Int(round(b * 255)))
  }

  public func toHex() -> String {
    let rgb = toRGB()
    return String(format: "#%02X%02X%02X", rgb.r, rgb.g, rgb.b)
  }
}

public struct SwatchGroup: Identifiable, Equatable, Sendable {
  public let id: UUID
  public var name: String
  public var swatches: [Swatch]

  public init(id: UUID = UUID(), name: String, swatches: [Swatch] = []) {
    self.id = id
    self.name = name
    self.swatches = swatches
  }
}

// MARK: - Swatch Palette

public final class SwatchPalette: ObservableObject, Identifiable {
  public let id: UUID
  @Published public var name: String
  @Published public var swatches: [Swatch]
  @Published public var groups: [SwatchGroup]

  public init(
    id: UUID = UUID(),
    name: String = "Swatches",
    swatches: [Swatch] = [],
    groups: [SwatchGroup] = []
  ) {
    self.id = id
    self.name = name
    self.swatches = swatches
    self.groups = groups
  }

  public func allSwatches() -> [Swatch] {
    var result = swatches
    for group in groups {
      result.append(contentsOf: group.swatches)
    }
    return result
  }

  public func addSwatch(_ swatch: Swatch, group groupName: String? = nil) {
    if let gName = groupName {
      if let idx = groups.firstIndex(where: { $0.name == gName }) {
        groups[idx].swatches.append(swatch)
      } else {
        groups.append(SwatchGroup(name: gName, swatches: [swatch]))
      }
    } else {
      swatches.append(swatch)
    }
  }

  // MARK: - Default Palette

  public static var defaultPalette: SwatchPalette {
    let colors: [(String, Int, Int, Int)] = [
      ("Black", 0, 0, 0),
      ("Dark Gray", 64, 64, 64),
      ("Gray", 128, 128, 128),
      ("Light Gray", 192, 192, 192),
      ("White", 255, 255, 255),
      ("Dark Red", 139, 0, 0),
      ("Red", 255, 0, 0),
      ("Light Coral", 240, 128, 128),
      ("Orange", 255, 128, 0),
      ("Gold", 255, 215, 0),
      ("Yellow", 255, 255, 0),
      ("Lime", 0, 255, 0),
      ("Green", 34, 139, 34),
      ("Dark Green", 0, 100, 0),
      ("Cyan", 0, 255, 255),
      ("Sky Blue", 135, 206, 235),
      ("Blue", 0, 0, 255),
      ("Navy", 0, 0, 128),
      ("Purple", 128, 0, 128),
      ("Magenta", 255, 0, 255),
      ("Hot Pink", 255, 105, 180),
      ("Saddle Brown", 139, 69, 19),
      ("Chocolate", 210, 105, 30),
      ("Wheat", 245, 222, 179)
    ]
    let items = colors.map { name, r, g, b in
      let uiColor = UIColor(red: CGFloat(r) / 255.0, green: CGFloat(g) / 255.0, blue: CGFloat(b) / 255.0, alpha: 1.0)
      return Swatch(name: name, color: uiColor, colorModel: "RGB", values: [Double(r) / 255.0, Double(g) / 255.0, Double(b) / 255.0])
    }
    return SwatchPalette(name: "Default Palette", swatches: items)
  }

  // MARK: - Format Sniffing & Loader

  public static func decode(data: Data, filename: String? = nil) throws -> SwatchPalette {
    guard !data.isEmpty else { throw SwatchError.emptyData }
    let fn = filename?.lowercased() ?? ""
    if data.starts(with: [0x41, 0x53, 0x45, 0x46]) { // "ASEF"
      return try decodeASE(data: data)
    } else if fn.hasSuffix(".ase") {
      return try decodeASE(data: data)
    } else if data.count >= 4 && (data[0] == 0x00 && (data[1] == 0x01 || data[1] == 0x02)) {
      return try decodeACO(data: data)
    } else if fn.hasSuffix(".aco") {
      return try decodeACO(data: data)
    } else {
      // Try ASE then ACO
      if let pal = try? decodeASE(data: data) {
        return pal
      }
      return try decodeACO(data: data)
    }
  }

  // MARK: - Adobe Color Swatches (.aco) Decoding

  public static func decodeACO(data: Data) throws -> SwatchPalette {
    guard data.count >= 4 else { throw SwatchError.fileTooShort }

    let version = UInt16(data[0]) << 8 | UInt16(data[1])
    let count = Int(UInt16(data[2]) << 8 | UInt16(data[3]))

    guard version == 1 || version == 2 else {
      throw SwatchError.unsupportedVersion("\(version)")
    }
    guard count <= 32768 else {
      throw SwatchError.excessiveCount(count)
    }

    func decodeColorEntry(offset: Int) throws -> (model: String, values: [Double], color: UIColor) {
      guard offset + 10 <= data.count else {
        throw SwatchError.truncatedData("ACO color entry")
      }
      let spaceID = UInt16(data[offset]) << 8 | UInt16(data[offset + 1])
      let w = UInt16(data[offset + 2]) << 8 | UInt16(data[offset + 3])
      let x = UInt16(data[offset + 4]) << 8 | UInt16(data[offset + 5])
      let y = UInt16(data[offset + 6]) << 8 | UInt16(data[offset + 7])
      let z = UInt16(data[offset + 8]) << 8 | UInt16(data[offset + 9])

      switch spaceID {
      case 0: // RGB
        let r = Double(w) / 65535.0
        let g = Double(x) / 65535.0
        let b = Double(y) / 65535.0
        let ui = UIColor(red: CGFloat(r), green: CGFloat(g), blue: CGFloat(b), alpha: 1.0)
        return ("RGB", [r, g, b], ui)
      case 1: // HSB
        let h = (Double(w) / 100.0) / 360.0
        let s = (Double(x) / 100.0) / 100.0
        let br = (Double(y) / 100.0) / 100.0
        let ui = UIColor(hue: CGFloat(h), saturation: CGFloat(s), brightness: CGFloat(br), alpha: 1.0)
        return ("HSB", [h, s, br], ui)
      case 2: // CMYK
        let c = Double(w) / 65535.0
        let m = Double(x) / 65535.0
        let yl = Double(y) / 65535.0
        let k = Double(z) / 65535.0
        let rgb = SwatchColorSpace.cmykToRGB(c: c, m: m, y: yl, k: k)
        let ui = UIColor(red: CGFloat(rgb.r), green: CGFloat(rgb.g), blue: CGFloat(rgb.b), alpha: 1.0)
        return ("CMYK", [c, m, yl, k], ui)
      case 7: // Lab
        let l = Double(w) / 100.0
        let aInt = Int16(bitPattern: x)
        let bInt = Int16(bitPattern: y)
        let a = Double(aInt) / 100.0
        let b = Double(bInt) / 100.0
        let rgb = SwatchColorSpace.labToRGB(l: l, a: a, b: b)
        let ui = UIColor(red: CGFloat(rgb.r), green: CGFloat(rgb.g), blue: CGFloat(rgb.b), alpha: 1.0)
        return ("LAB", [l, a, b], ui)
      case 8: // Grayscale
        let g = Double(w) / 10000.0
        let ui = UIColor(white: CGFloat(g), alpha: 1.0)
        return ("GRAY", [g], ui)
      default:
        let r = Double(w) / 65535.0
        let g = Double(x) / 65535.0
        let b = Double(y) / 65535.0
        let ui = UIColor(red: CGFloat(r), green: CGFloat(g), blue: CGFloat(b), alpha: 1.0)
        return ("RGB", [r, g, b], ui)
      }
    }

    if version == 1 {
      guard data.count >= 4 + count * 10 else {
        throw SwatchError.truncatedData("ACO v1 color array")
      }
      var v1Swatches: [Swatch] = []
      for i in 0..<count {
        let entry = try decodeColorEntry(offset: 4 + i * 10)
        v1Swatches.append(Swatch(name: "Swatch \(i + 1)", color: entry.color, colorModel: entry.model, values: entry.values))
      }

      // Check if version 2 section follows
      let v2Offset = 4 + count * 10
      if data.count >= v2Offset + 4 {
        let v2Ver = UInt16(data[v2Offset]) << 8 | UInt16(data[v2Offset + 1])
        let v2Count = Int(UInt16(data[v2Offset + 2]) << 8 | UInt16(data[v2Offset + 3]))
        if v2Ver == 2 && v2Count <= 32768 {
          if let v2Swatches = try? parseACOv2Entries(data: data, offset: v2Offset + 4, count: v2Count, decodeColor: decodeColorEntry) {
            return SwatchPalette(name: "Adobe Swatches", swatches: v2Swatches)
          }
        }
      }
      return SwatchPalette(name: "Adobe Swatches", swatches: v1Swatches)
    } else {
      let v2Swatches = try parseACOv2Entries(data: data, offset: 4, count: count, decodeColor: decodeColorEntry)
      return SwatchPalette(name: "Adobe Swatches", swatches: v2Swatches)
    }
  }

  private static func parseACOv2Entries(
    data: Data,
    offset: Int,
    count: Int,
    decodeColor: (Int) throws -> (model: String, values: [Double], color: UIColor)
  ) throws -> [Swatch] {
    var swatches: [Swatch] = []
    var curr = offset
    for i in 0..<count {
      guard curr + 10 <= data.count else { throw SwatchError.truncatedData("ACO v2 color record") }
      let entry = try decodeColor(curr)
      curr += 10

      guard curr + 4 <= data.count else { throw SwatchError.truncatedData("ACO v2 name length") }
      let nameLen = Int(UInt32(data[curr]) << 24 | UInt32(data[curr + 1]) << 16 | UInt32(data[curr + 2]) << 8 | UInt32(data[curr + 3]))
      curr += 4

      guard nameLen >= 1, nameLen <= 4096 else { throw SwatchError.invalidNameLength }
      let nameBytesLen = nameLen * 2
      guard curr + nameBytesLen <= data.count else { throw SwatchError.truncatedData("ACO v2 string payload") }

      let nameData = data.subdata(in: curr..<(curr + (nameLen - 1) * 2))
      let nameStr = String(data: nameData, encoding: .utf16BigEndian) ?? "Swatch \(i + 1)"
      curr += nameBytesLen

      swatches.append(Swatch(name: nameStr, color: entry.color, colorModel: entry.model, values: entry.values))
    }
    return swatches
  }

  // MARK: - Adobe Swatch Exchange (.ase) Decoding

  public static func decodeASE(data: Data) throws -> SwatchPalette {
    guard data.count >= 12 else { throw SwatchError.fileTooShort }
    guard data.starts(with: [0x41, 0x53, 0x45, 0x46]) else { // "ASEF"
      throw SwatchError.invalidSignature
    }

    let major = UInt16(data[4]) << 8 | UInt16(data[5])
    let minor = UInt16(data[6]) << 8 | UInt16(data[7])
    guard major == 1 else { throw SwatchError.unsupportedVersion("\(major).\(minor)") }

    let blockCount = Int(UInt32(data[8]) << 24 | UInt32(data[9]) << 16 | UInt32(data[10]) << 8 | UInt32(data[11]))
    guard blockCount <= 65536 else { throw SwatchError.excessiveCount(blockCount) }

    let palette = SwatchPalette(name: "Adobe Swatch Exchange")
    var currentGroup: SwatchGroup?
    var offset = 12

    for i in 0..<blockCount {
      guard offset < data.count else {
        throw SwatchError.truncatedData("expected \(blockCount) blocks, got EOF at block \(i)")
      }
      guard offset + 6 <= data.count else { throw SwatchError.truncatedData("block header") }

      let blockType = UInt16(data[offset]) << 8 | UInt16(data[offset + 1])
      let blockLen = Int(UInt32(data[offset + 2]) << 24 | UInt32(data[offset + 3]) << 16 | UInt32(data[offset + 4]) << 8 | UInt32(data[offset + 5]))
      offset += 6

      guard offset + blockLen <= data.count else { throw SwatchError.truncatedData("block body length \(blockLen)") }
      let blockData = data.subdata(in: offset..<(offset + blockLen))
      offset += blockLen

      if blockType == 0xC001 { // Group Start
        guard blockData.count >= 2 else { throw SwatchError.truncatedData("group start") }
        let nameLen = Int(UInt16(blockData[0]) << 8 | UInt16(blockData[1]))
        guard nameLen >= 1, 2 + (nameLen * 2) <= blockData.count else {
          throw SwatchError.truncatedData("group name")
        }
        let nameData = blockData.subdata(in: 2..<(2 + (nameLen - 1) * 2))
        let grpName = String(data: nameData, encoding: .utf16BigEndian) ?? "Group"
        let group = SwatchGroup(name: grpName)
        palette.groups.append(group)
        currentGroup = group

      } else if blockType == 0xC002 || blockType == 0xC000 { // Group End
        currentGroup = nil

      } else if blockType == 0x0001 { // Color Entry
        guard blockData.count >= 2 else { throw SwatchError.truncatedData("color entry") }
        let nameLen = Int(UInt16(blockData[0]) << 8 | UInt16(blockData[1]))
        guard nameLen >= 1 else { throw SwatchError.invalidNameLength }
        let nameBytesLen = (nameLen - 1) * 2
        var pos = 2 + (nameLen * 2)
        guard pos <= blockData.count else { throw SwatchError.truncatedData("color name") }

        let nameData = blockData.subdata(in: 2..<(2 + nameBytesLen))
        let colorName = String(data: nameData, encoding: .utf16BigEndian) ?? "Swatch"

        guard pos + 4 <= blockData.count else { throw SwatchError.truncatedData("color space signature") }
        let modelStr = String(data: blockData.subdata(in: pos..<(pos + 4)), encoding: .ascii) ?? ""
        pos += 4

        func readFloat(at byteOffset: Int) -> Float {
          let u = UInt32(blockData[byteOffset]) << 24 | UInt32(blockData[byteOffset + 1]) << 16 | UInt32(blockData[byteOffset + 2]) << 8 | UInt32(blockData[byteOffset + 3])
          return Float(bitPattern: u)
        }

        let swatchModel: String
        let vals: [Double]
        let uiColor: UIColor

        if modelStr == "RGB " {
          guard pos + 12 <= blockData.count else { throw SwatchError.truncatedData("RGB floats") }
          let r = Double(readFloat(at: pos))
          let g = Double(readFloat(at: pos + 4))
          let b = Double(readFloat(at: pos + 8))
          pos += 12
          swatchModel = "RGB"
          vals = [r, g, b]
          uiColor = UIColor(red: CGFloat(r), green: CGFloat(g), blue: CGFloat(b), alpha: 1.0)
        } else if modelStr == "CMYK" {
          guard pos + 16 <= blockData.count else { throw SwatchError.truncatedData("CMYK floats") }
          let c = Double(readFloat(at: pos))
          let m = Double(readFloat(at: pos + 4))
          let y = Double(readFloat(at: pos + 8))
          let k = Double(readFloat(at: pos + 12))
          pos += 16
          swatchModel = "CMYK"
          vals = [c, m, y, k]
          let rgb = SwatchColorSpace.cmykToRGB(c: c, m: m, y: y, k: k)
          uiColor = UIColor(red: CGFloat(rgb.r), green: CGFloat(rgb.g), blue: CGFloat(rgb.b), alpha: 1.0)
        } else if modelStr == "LAB " {
          guard pos + 12 <= blockData.count else { throw SwatchError.truncatedData("LAB floats") }
          var l = Double(readFloat(at: pos))
          let a = Double(readFloat(at: pos + 4))
          let b = Double(readFloat(at: pos + 8))
          pos += 12
          if l <= 1.0 && l >= 0.0 && (a != 0.0 || b != 0.0) {
            l *= 100.0
          }
          swatchModel = "LAB"
          vals = [l, a, b]
          let rgb = SwatchColorSpace.labToRGB(l: l, a: a, b: b)
          uiColor = UIColor(red: CGFloat(rgb.r), green: CGFloat(rgb.g), blue: CGFloat(rgb.b), alpha: 1.0)
        } else if modelStr == "GRAY" {
          guard pos + 4 <= blockData.count else { throw SwatchError.truncatedData("GRAY float") }
          let gray = Double(readFloat(at: pos))
          pos += 4
          swatchModel = "GRAY"
          vals = [gray]
          uiColor = UIColor(white: CGFloat(gray), alpha: 1.0)
        } else {
          throw SwatchError.unsupportedColorModel(modelStr)
        }

        var colorType: SwatchColorType = .process
        if pos + 2 <= blockData.count {
          let typeInt = Int(UInt16(blockData[pos]) << 8 | UInt16(blockData[pos + 1]))
          colorType = SwatchColorType(rawValue: typeInt) ?? .process
        }

        let swatch = Swatch(name: colorName, color: uiColor, colorModel: swatchModel, values: vals, colorType: colorType)
        if let grp = currentGroup {
          if let idx = palette.groups.firstIndex(where: { $0.id == grp.id }) {
            palette.groups[idx].swatches.append(swatch)
          }
        } else {
          palette.swatches.append(swatch)
        }
      }
    }
    return palette
  }

  // MARK: - Encoders

  public func encodeACO() -> Data {
    let all = allSwatches()
    var data = Data()

    // Helper to write big endian integers
    func appendUInt16(_ val: UInt16) {
      data.append(UInt8((val >> 8) & 0xFF))
      data.append(UInt8(val & 0xFF))
    }
    func appendUInt32(_ val: UInt32) {
      data.append(UInt8((val >> 24) & 0xFF))
      data.append(UInt8((val >> 16) & 0xFF))
      data.append(UInt8((val >> 8) & 0xFF))
      data.append(UInt8(val & 0xFF))
    }

    // Version 1
    appendUInt16(1)
    appendUInt16(UInt16(min(all.count, 65535)))
    for s in all {
      encodeACOColorBlock(swatch: s, to: &data)
    }

    // Version 2
    appendUInt16(2)
    appendUInt16(UInt16(min(all.count, 65535)))
    for (i, s) in all.enumerated() {
      encodeACOColorBlock(swatch: s, to: &data)
      let name = s.name.isEmpty ? "Swatch \(i + 1)" : s.name
      let nameData = name.data(using: .utf16BigEndian) ?? Data()
      let nameChars = UInt32((nameData.count / 2) + 1)
      appendUInt32(nameChars)
      data.append(nameData)
      data.append(contentsOf: [0x00, 0x00])
    }
    return data
  }

  private func encodeACOColorBlock(swatch: Swatch, to data: inout Data) {
    func appendUInt16(_ val: UInt16) {
      data.append(UInt8((val >> 8) & 0xFF))
      data.append(UInt8(val & 0xFF))
    }
    switch swatch.colorModel.uppercased() {
    case "CMYK":
      appendUInt16(2)
      let c = UInt16(round(max(0.0, min(1.0, swatch.values[0])) * 65535.0))
      let m = UInt16(round(max(0.0, min(1.0, swatch.values[1])) * 65535.0))
      let y = UInt16(round(max(0.0, min(1.0, swatch.values[2])) * 65535.0))
      let k = UInt16(round(max(0.0, min(1.0, swatch.values[3])) * 65535.0))
      appendUInt16(c); appendUInt16(m); appendUInt16(y); appendUInt16(k)
    case "LAB":
      appendUInt16(7)
      let l = UInt16(round(max(0.0, min(100.0, swatch.values[0])) * 100.0))
      let a = Int16(round(max(-128.0, min(127.0, swatch.values[1])) * 100.0))
      let b = Int16(round(max(-128.0, min(127.0, swatch.values[2])) * 100.0))
      appendUInt16(l)
      appendUInt16(UInt16(bitPattern: a))
      appendUInt16(UInt16(bitPattern: b))
      appendUInt16(0)
    case "GRAY":
      appendUInt16(8)
      let g = UInt16(round(max(0.0, min(1.0, swatch.values[0])) * 10000.0))
      appendUInt16(g); appendUInt16(0); appendUInt16(0); appendUInt16(0)
    case "HSB":
      appendUInt16(1)
      let h = UInt16(round((swatch.values[0].truncatingRemainder(dividingBy: 1.0)) * 36000.0))
      let s = UInt16(round(max(0.0, min(1.0, swatch.values[1])) * 10000.0))
      let br = UInt16(round(max(0.0, min(1.0, swatch.values[2])) * 10000.0))
      appendUInt16(h); appendUInt16(s); appendUInt16(br); appendUInt16(0)
    default: // RGB
      appendUInt16(0)
      let r = UInt16(round(max(0.0, min(1.0, swatch.values[0])) * 65535.0))
      let g = UInt16(round(max(0.0, min(1.0, swatch.values[1])) * 65535.0))
      let b = UInt16(round(max(0.0, min(1.0, swatch.values[2])) * 65535.0))
      appendUInt16(r); appendUInt16(g); appendUInt16(b); appendUInt16(0)
    }
  }

  public func encodeASE() -> Data {
    var body = Data()
    var blockCount: UInt32 = 0

    func appendUInt16(_ val: UInt16, to d: inout Data) {
      d.append(UInt8((val >> 8) & 0xFF))
      d.append(UInt8(val & 0xFF))
    }
    func appendUInt32(_ val: UInt32, to d: inout Data) {
      d.append(UInt8((val >> 24) & 0xFF))
      d.append(UInt8((val >> 16) & 0xFF))
      d.append(UInt8((val >> 8) & 0xFF))
      d.append(UInt8(val & 0xFF))
    }
    func appendFloat(_ val: Float, to d: inout Data) {
      appendUInt32(val.bitPattern, to: &d)
    }

    func makeColorBlock(_ s: Swatch) -> Data {
      var payload = Data()
      let name = s.name.isEmpty ? "Swatch" : s.name
      let nameData = name.data(using: .utf16BigEndian) ?? Data()
      let nameChars = UInt16((nameData.count / 2) + 1)
      appendUInt16(nameChars, to: &payload)
      payload.append(nameData)
      payload.append(contentsOf: [0x00, 0x00])

      switch s.colorModel.uppercased() {
      case "CMYK":
        payload.append(contentsOf: [0x43, 0x4D, 0x59, 0x4B]) // "CMYK"
        appendFloat(Float(s.values[0]), to: &payload)
        appendFloat(Float(s.values[1]), to: &payload)
        appendFloat(Float(s.values[2]), to: &payload)
        appendFloat(Float(s.values[3]), to: &payload)
      case "LAB":
        payload.append(contentsOf: [0x4C, 0x41, 0x42, 0x20]) // "LAB "
        appendFloat(Float(s.values[0] / 100.0), to: &payload)
        appendFloat(Float(s.values[1]), to: &payload)
        appendFloat(Float(s.values[2]), to: &payload)
      case "GRAY":
        payload.append(contentsOf: [0x47, 0x52, 0x41, 0x59]) // "GRAY"
        appendFloat(Float(s.values[0]), to: &payload)
      default: // RGB
        payload.append(contentsOf: [0x52, 0x47, 0x42, 0x20]) // "RGB "
        appendFloat(Float(s.values[0]), to: &payload)
        appendFloat(Float(s.values[1]), to: &payload)
        appendFloat(Float(s.values[2]), to: &payload)
      }

      appendUInt16(UInt16(s.colorType.rawValue), to: &payload)

      var block = Data()
      appendUInt16(0x0001, to: &block)
      appendUInt32(UInt32(payload.count), to: &block)
      block.append(payload)
      return block
    }

    for s in swatches {
      body.append(makeColorBlock(s))
      blockCount += 1
    }

    for grp in groups {
      // Group Start: 0xC001
      var gPayload = Data()
      let gName = grp.name.isEmpty ? "Group" : grp.name
      let gData = gName.data(using: .utf16BigEndian) ?? Data()
      appendUInt16(UInt16((gData.count / 2) + 1), to: &gPayload)
      gPayload.append(gData)
      gPayload.append(contentsOf: [0x00, 0x00])

      appendUInt16(0xC001, to: &body)
      appendUInt32(UInt32(gPayload.count), to: &body)
      body.append(gPayload)
      blockCount += 1

      for s in grp.swatches {
        body.append(makeColorBlock(s))
        blockCount += 1
      }

      // Group End: 0xC002
      appendUInt16(0xC002, to: &body)
      appendUInt32(0, to: &body)
      blockCount += 1
    }

    var header = Data([0x41, 0x53, 0x45, 0x46]) // "ASEF"
    appendUInt16(1, to: &header)
    appendUInt16(0, to: &header)
    appendUInt32(blockCount, to: &header)

    return header + body
  }
}

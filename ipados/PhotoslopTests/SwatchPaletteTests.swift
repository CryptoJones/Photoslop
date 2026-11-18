// SPDX-License-Identifier: Apache-2.0
//
// SwatchPaletteTests.swift — Adobe .aco and .ase swatch palette unit tests (#421).
//

import UIKit
import XCTest

@testable import PhotoslopIPad

final class SwatchPaletteTests: XCTestCase {

  func testColorConversions() {
    // LAB round-trip test
    let testColors: [(r: Double, g: Double, b: Double)] = [
      (1.0, 0.0, 0.0),
      (0.0, 1.0, 0.0),
      (0.0, 0.0, 1.0),
      (1.0, 1.0, 1.0),
      (0.0, 0.0, 0.0),
      (0.5, 0.25, 0.75)
    ]

    for c in testColors {
      let lab = SwatchColorSpace.rgbToLab(r: c.r, g: c.g, b: c.b)
      let rgb2 = SwatchColorSpace.labToRGB(l: lab.l, a: lab.a, b: lab.b)
      XCTAssertLessThanOrEqual(abs(c.r - rgb2.r), 0.015, "Red mismatch for \(c)")
      XCTAssertLessThanOrEqual(abs(c.g - rgb2.g), 0.015, "Green mismatch for \(c)")
      XCTAssertLessThanOrEqual(abs(c.b - rgb2.b), 0.015, "Blue mismatch for \(c)")
    }

    // CMYK round-trip test
    for c in testColors {
      let cmyk = SwatchColorSpace.rgbToCMYK(r: c.r, g: c.g, b: c.b)
      let rgb2 = SwatchColorSpace.cmykToRGB(c: cmyk.c, m: cmyk.m, y: cmyk.y, k: cmyk.k)
      XCTAssertLessThanOrEqual(abs(c.r - rgb2.r), 0.015, "CMYK Red mismatch for \(c)")
      XCTAssertLessThanOrEqual(abs(c.g - rgb2.g), 0.015, "CMYK Green mismatch for \(c)")
      XCTAssertLessThanOrEqual(abs(c.b - rgb2.b), 0.015, "CMYK Blue mismatch for \(c)")
    }
  }

  func testACORoundTrip() throws {
    let pal = SwatchPalette(name: "TestACO")
    let redColor = UIColor(red: 1.0, green: 0.0, blue: 0.0, alpha: 1.0)
    let greenColor = UIColor(red: 0.0, green: 1.0, blue: 0.0, alpha: 1.0)
    let blueColor = UIColor(red: 0.0, green: 0.0, blue: 1.0, alpha: 1.0)

    pal.addSwatch(Swatch(name: "Vibrant Red", color: redColor, colorModel: "RGB", values: [1.0, 0.0, 0.0]))
    pal.addSwatch(Swatch(name: "Vibrant Green", color: greenColor, colorModel: "RGB", values: [0.0, 1.0, 0.0]))
    pal.addSwatch(Swatch(name: "Vibrant Blue", color: blueColor, colorModel: "RGB", values: [0.0, 0.0, 1.0]))

    let acoData = pal.encodeACO()
    XCTAssertFalse(acoData.isEmpty)

    let decoded = try SwatchPalette.decodeACO(data: acoData)
    let swatches = decoded.allSwatches()
    XCTAssertEqual(swatches.count, 3)
    XCTAssertEqual(swatches[0].name, "Vibrant Red")
    XCTAssertEqual(swatches[0].toRGB().r, 255)
    XCTAssertEqual(swatches[0].toRGB().g, 0)
    XCTAssertEqual(swatches[0].toRGB().b, 0)

    XCTAssertEqual(swatches[1].name, "Vibrant Green")
    XCTAssertEqual(swatches[1].toRGB().r, 0)
    XCTAssertEqual(swatches[1].toRGB().g, 255)
    XCTAssertEqual(swatches[1].toRGB().b, 0)

    XCTAssertEqual(swatches[2].name, "Vibrant Blue")
    XCTAssertEqual(swatches[2].toRGB().r, 0)
    XCTAssertEqual(swatches[2].toRGB().g, 0)
    XCTAssertEqual(swatches[2].toRGB().b, 255)
  }

  func testACOColorModels() throws {
    let pal = SwatchPalette(name: "ACOModels")
    let rgbColor = UIColor(red: 1.0, green: 0.0, blue: 0.0, alpha: 1.0)
    let cmykColor = UIColor(red: 0.0, green: 1.0, blue: 1.0, alpha: 1.0)
    let hsbColor = UIColor(hue: 0.5, saturation: 1.0, brightness: 1.0, alpha: 1.0)
    let labColor = UIColor(red: 0.5, green: 0.5, blue: 0.5, alpha: 1.0)
    let grayColor = UIColor(white: 0.6, alpha: 1.0)

    pal.addSwatch(Swatch(name: "RGB Color", color: rgbColor, colorModel: "RGB", values: [1.0, 0.0, 0.0]))
    pal.addSwatch(Swatch(name: "HSB Color", color: hsbColor, colorModel: "HSB", values: [0.5, 1.0, 1.0]))
    pal.addSwatch(Swatch(name: "CMYK Color", color: cmykColor, colorModel: "CMYK", values: [1.0, 0.0, 0.0, 0.0]))
    pal.addSwatch(Swatch(name: "LAB Color", color: labColor, colorModel: "LAB", values: [50.0, 0.0, 0.0]))
    pal.addSwatch(Swatch(name: "GRAY Color", color: grayColor, colorModel: "GRAY", values: [0.6]))

    let acoData = pal.encodeACO()
    let decoded = try SwatchPalette.decodeACO(data: acoData)
    XCTAssertEqual(decoded.allSwatches().count, 5)
    XCTAssertEqual(decoded.allSwatches()[0].colorModel, "RGB")
    XCTAssertEqual(decoded.allSwatches()[1].colorModel, "HSB")
    XCTAssertEqual(decoded.allSwatches()[2].colorModel, "CMYK")
    XCTAssertEqual(decoded.allSwatches()[3].colorModel, "LAB")
    XCTAssertEqual(decoded.allSwatches()[4].colorModel, "GRAY")
  }

  func testASERoundTrip() throws {
    let pal = SwatchPalette(name: "ASEPalette")
    let orange = UIColor(red: 1.0, green: 0.5, blue: 0.0, alpha: 1.0)
    pal.addSwatch(Swatch(name: "Sunset Orange", color: orange, colorModel: "RGB", values: [1.0, 0.5, 0.0], colorType: .global))

    let grp = SwatchGroup(name: "Cool Tones")
    let teal = UIColor(red: 0.0, green: 0.5, blue: 0.5, alpha: 1.0)
    let purple = UIColor(red: 0.5, green: 0.0, blue: 0.5, alpha: 1.0)
    let gSwatches = [
      Swatch(name: "Deep Teal", color: teal, colorModel: "RGB", values: [0.0, 0.5, 0.5], colorType: .spot),
      Swatch(name: "Royal Purple", color: purple, colorModel: "RGB", values: [0.5, 0.0, 0.5], colorType: .process)
    ]
    pal.groups.append(SwatchGroup(name: grp.name, swatches: gSwatches))

    let aseData = pal.encodeASE()
    XCTAssertFalse(aseData.isEmpty)

    let decoded = try SwatchPalette.decodeASE(data: aseData)
    XCTAssertEqual(decoded.swatches.count, 1)
    XCTAssertEqual(decoded.swatches[0].name, "Sunset Orange")
    XCTAssertEqual(decoded.swatches[0].colorType, .global)

    XCTAssertEqual(decoded.groups.count, 1)
    XCTAssertEqual(decoded.groups[0].name, "Cool Tones")
    XCTAssertEqual(decoded.groups[0].swatches.count, 2)
    XCTAssertEqual(decoded.groups[0].swatches[0].name, "Deep Teal")
    XCTAssertEqual(decoded.groups[0].swatches[0].colorType, .spot)
    XCTAssertEqual(decoded.groups[0].swatches[1].name, "Royal Purple")
    XCTAssertEqual(decoded.groups[0].swatches[1].colorType, .process)
  }

  func testASEColorModels() throws {
    let pal = SwatchPalette(name: "ASEModels")
    let rgb = UIColor(red: 0.2, green: 0.4, blue: 0.8, alpha: 1.0)
    let cmyk = UIColor(red: 1.0, green: 0.0, blue: 0.0, alpha: 1.0)
    let lab = UIColor(red: 0.3, green: 0.7, blue: 0.3, alpha: 1.0)
    let gray = UIColor(white: 0.75, alpha: 1.0)

    pal.addSwatch(Swatch(name: "RGB Color", color: rgb, colorModel: "RGB", values: [0.2, 0.4, 0.8]))
    pal.addSwatch(Swatch(name: "CMYK Color", color: cmyk, colorModel: "CMYK", values: [0.0, 1.0, 1.0, 0.0]))
    pal.addSwatch(Swatch(name: "LAB Color", color: lab, colorModel: "LAB", values: [65.0, -50.0, 45.0]))
    pal.addSwatch(Swatch(name: "GRAY Color", color: gray, colorModel: "GRAY", values: [0.75]))

    let aseData = pal.encodeASE()
    let decoded = try SwatchPalette.decodeASE(data: aseData)
    XCTAssertEqual(decoded.swatches.count, 4)
    XCTAssertEqual(decoded.swatches[0].colorModel, "RGB")
    XCTAssertEqual(decoded.swatches[1].colorModel, "CMYK")
    XCTAssertEqual(decoded.swatches[2].colorModel, "LAB")
    XCTAssertEqual(decoded.swatches[3].colorModel, "GRAY")
  }

  func testACOv1OnlyStream() throws {
    var data = Data()
    // version 1, count 1
    data.append(contentsOf: [0x00, 0x01, 0x00, 0x01])
    // RGB (65535, 0, 0)
    data.append(contentsOf: [0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

    let pal = try SwatchPalette.decodeACO(data: data)
    XCTAssertEqual(pal.allSwatches().count, 1)
    XCTAssertEqual(pal.allSwatches()[0].toRGB().r, 255)
    XCTAssertEqual(pal.allSwatches()[0].toRGB().g, 0)
    XCTAssertEqual(pal.allSwatches()[0].toRGB().b, 0)
  }

  func testCorruptInputsGracefullyRefused() {
    // Empty data
    XCTAssertThrowsError(try SwatchPalette.decode(data: Data())) { error in
      XCTAssertEqual(error as? SwatchError, SwatchError.emptyData)
    }

    // Short data
    XCTAssertThrowsError(try SwatchPalette.decodeACO(data: Data([0x00, 0x01]))) { error in
      XCTAssertEqual(error as? SwatchError, SwatchError.fileTooShort)
    }

    // Invalid signature for ASE
    XCTAssertThrowsError(try SwatchPalette.decodeASE(data: Data([0x00, 0x01, 0x02, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01]))) { error in
      XCTAssertEqual(error as? SwatchError, SwatchError.invalidSignature)
    }

    // Truncated ACO
    XCTAssertThrowsError(try SwatchPalette.decodeACO(data: Data([0x00, 0x01, 0x00, 0x05, 0x00, 0x00]))) { error in
      if case .truncatedData = (error as? SwatchError) {
        // Success
      } else {
        XCTFail("Expected truncatedData error, got \(error)")
      }
    }

    // Truncated ASE block
    var badASE = Data([0x41, 0x53, 0x45, 0x46, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01])
    badASE.append(contentsOf: [0x00, 0x01, 0x00, 0x00, 0x00, 0x64]) // claims 100 bytes block payload, but none follow
    XCTAssertThrowsError(try SwatchPalette.decodeASE(data: badASE)) { error in
      if case .truncatedData = (error as? SwatchError) {
        // Success
      } else {
        XCTFail("Expected truncatedData error, got \(error)")
      }
    }
  }

  func testDefaultPalette() {
    let pal = SwatchPalette.defaultPalette
    XCTAssertGreaterThanOrEqual(pal.allSwatches().count, 16)
    XCTAssertEqual(pal.allSwatches()[0].name, "Black")
    XCTAssertEqual(pal.allSwatches()[0].toRGB().r, 0)
    XCTAssertEqual(pal.allSwatches()[0].toRGB().g, 0)
    XCTAssertEqual(pal.allSwatches()[0].toRGB().b, 0)
  }
}

// SPDX-License-Identifier: Apache-2.0
import ImageIO
import UIKit
import UniformTypeIdentifiers
import XCTest

@testable import PhotoslopIPad

final class ExportFormatTests: XCTestCase {
  /// A 2x2 image whose left half is opaque red and right half fully transparent.
  private func translucentSwatch() -> UIImage {
    let size = CGSize(width: 2, height: 2)
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: size, format: format).image { context in
      UIColor.red.setFill()
      context.fill(CGRect(x: 0, y: 0, width: 1, height: 2))
    }
  }

  func testEveryFormatEncodesToItsOwnFileType() throws {
    let image = translucentSwatch()
    for format in ExportFormat.allCases {
      let data = try XCTUnwrap(
        format.encode(image), "\(format.displayName) produced no data")
      XCTAssertFalse(data.isEmpty)

      let source = try XCTUnwrap(
        CGImageSourceCreateWithData(data as CFData, nil),
        "\(format.displayName) output was not decodable")
      let produced = try XCTUnwrap(CGImageSourceGetType(source) as String?)
      XCTAssertEqual(
        UTType(produced), format.utType,
        "\(format.displayName) encoded as \(produced)")
    }
  }

  func testEncodedImageKeepsItsPixelDimensions() throws {
    let image = translucentSwatch()
    for format in ExportFormat.allCases {
      let data = try XCTUnwrap(format.encode(image))
      let decoded = try XCTUnwrap(UIImage(data: data), "\(format.displayName)")
      XCTAssertEqual(decoded.size.width, 2, accuracy: 0.01, "\(format.displayName)")
      XCTAssertEqual(decoded.size.height, 2, accuracy: 0.01, "\(format.displayName)")
    }
  }

  /// Formats with no alpha must be flattened onto white first. Skipping that
  /// leaves transparent pixels reading as black, which is the classic
  /// "why is my JPEG background black" export bug.
  func testFormatsWithoutAlphaFlattenOntoWhiteRatherThanBlack() throws {
    for format in ExportFormat.allCases where !format.preservesTransparency {
      let data = try XCTUnwrap(format.encode(translucentSwatch()))
      let decoded = try XCTUnwrap(UIImage(data: data), "\(format.displayName)")
      let cgImage = try XCTUnwrap(decoded.cgImage, "\(format.displayName)")

      var pixel = [UInt8](repeating: 0, count: 4)
      let context = try XCTUnwrap(
        CGContext(
          data: &pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
          space: CGColorSpaceCreateDeviceRGB(),
          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
      // Sample the originally transparent right half.
      context.draw(
        cgImage, in: CGRect(x: -1, y: 0, width: 2, height: 1))

      XCTAssertGreaterThan(
        Int(pixel[0]) + Int(pixel[1]) + Int(pixel[2]), 600,
        "\(format.displayName) transparent area should be near white, got "
          + "\(pixel[0]),\(pixel[1]),\(pixel[2])")
    }
  }

  func testFilenameExtensionsAreDistinctAndNonEmpty() {
    let extensions = ExportFormat.allCases.map(\.fileExtension)
    XCTAssertEqual(Set(extensions).count, extensions.count, "extensions collide")
    for value in extensions { XCTAssertFalse(value.isEmpty) }
  }

  func testPngIsTheDefaultAndLossyFormatsAreMarked() {
    XCTAssertEqual(ExportFormat.allCases.first, .png)
    XCTAssertTrue(ExportFormat.jpeg.isLossy)
    XCTAssertTrue(ExportFormat.heic.isLossy)
    XCTAssertFalse(ExportFormat.png.isLossy)
    XCTAssertFalse(ExportFormat.bmp.isLossy)
  }

  func testLowerQualityProducesSmallerJpegData() throws {
    let size = CGSize(width: 64, height: 64)
    let image = UIGraphicsImageRenderer(size: size).image { context in
      for row in 0..<8 {
        for column in 0..<8 {
          UIColor(hue: CGFloat(row * 8 + column) / 64, saturation: 1, brightness: 1, alpha: 1)
            .setFill()
          context.fill(CGRect(x: column * 8, y: row * 8, width: 8, height: 8))
        }
      }
    }
    let low = try XCTUnwrap(ExportFormat.jpeg.encode(image, quality: 0.1))
    let high = try XCTUnwrap(ExportFormat.jpeg.encode(image, quality: 1.0))
    XCTAssertLessThan(low.count, high.count)
  }
}

/// Photos accepts fewer encodings than the Files exporter, and a rejected
/// `addResource` fails after the render with an opaque error. The narrowing is
/// pinned here so a new format has to state which destinations it works with.
extension ExportFormatTests {
  func testOnlyPhotosCompatibleFormatsAreOfferedForTheLibrary() {
    let allowed = ExportFormat.allCases.filter(\.canGoToPhotoLibrary)
    XCTAssertEqual(Set(allowed), Set([.png, .jpeg, .heic]))

    for format in ExportFormat.allCases where !format.canGoToPhotoLibrary {
      XCTAssertFalse(
        allowed.contains(format),
        "\(format.displayName) is not reliably accepted by Photos and must not be offered")
    }
  }

  func testEveryPhotosFormatCarriesAUniformTypeIdentifier() {
    // PHAssetResourceCreationOptions needs the UTI to store the bytes as the
    // right kind of asset; an empty identifier silently produces a broken one.
    for format in ExportFormat.allCases where format.canGoToPhotoLibrary {
      XCTAssertFalse(
        format.utType.identifier.isEmpty,
        "\(format.displayName) has no UTI to hand to Photos")
    }
  }

  func testBothDestinationsAreOffered() {
    XCTAssertEqual(ExportDestination.allCases.map(\.displayName), ["Files", "Photos"])
  }
}

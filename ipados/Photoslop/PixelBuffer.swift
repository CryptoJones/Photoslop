// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import UIKit

/// A mutable premultiplied RGBA8 copy of a layer's pixels — the seam every
/// pixel operation on iOS goes through (#324, DD-013).
///
/// Drawing on iOS is PencilKit, which is vector strokes, and a layer is a
/// `UIImage`, which is immutable. Neither can express a flood fill, a wand or a
/// filter. This type borrows a layer's pixels as bytes, hands them to an
/// operation, and turns the result back into the `UIImage` the layer expects
/// (scale 1, orientation `.up`, the same shape `EditorStore.normalizedImage`
/// produces), so the desktop's pixel algorithms port without a translation
/// layer between the two.
///
/// **Byte order.** The buffer is a `CGContext` with
/// `byteOrder32Little | premultipliedFirst`: in memory each pixel is the four
/// bytes B, G, R, A, and read as a little-endian `UInt32` that is `0xAARRGGBB`
/// premultiplied. That is bit for bit the word `photoslop.npimage.view_u32`
/// reads from a `QImage.Format_ARGB32_Premultiplied` — Qt's `QRgb` on a
/// little-endian machine — so a desktop algorithm written against `view_u32`
/// works on `words` unchanged, and so do its fixtures. Rows are top-down with
/// no padding (`bytesPerRow == width * 4`), the same invariant `view_u32`
/// asserts.
///
/// **Memory.** A buffer costs `width * height * 4` bytes, one canvas-sized
/// bitmap. The store budgets that through the same `canAffordLayer` check
/// import uses before any buffer is made (#354), and work inside an operation
/// is meant to go through `forEachBand`, the port of the desktop's
/// `CHUNK_ROWS` discipline, so a transient never silently grows to a second
/// full-size bitmap.
struct PixelBuffer {
  /// Rows per band in `forEachBand`; the desktop's `CHUNK_ROWS`.
  static let bandRows = 256

  let width: Int
  let height: Int
  /// Always `width * 4`: the buffer owns its layout, so there is no padding.
  var bytesPerRow: Int { width * 4 }
  var byteCount: Int { width * height * 4 }

  /// Premultiplied ARGB32 words, row-major, top row first.
  var words: [UInt32]

  private static let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
  private static let bitmapInfo: UInt32 =
    CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue

  /// A transparent buffer of the given size.
  init(width: Int, height: Int) {
    precondition(width > 0 && height > 0, "a pixel buffer needs a positive size")
    self.width = width
    self.height = height
    words = [UInt32](repeating: 0, count: width * height)
  }

  /// A buffer of the given words, which must be `width * height` of them.
  init(width: Int, height: Int, words: [UInt32]) {
    precondition(words.count == width * height, "word count must match the size")
    self.width = width
    self.height = height
    self.words = words
  }

  /// Copy an image's pixels at their native pixel size — `size * scale`, so a
  /// 2x image is not halved — honouring its orientation, so row 0 is the top
  /// of the picture as displayed. Returns nil for an image with no pixels.
  init?(image: UIImage) {
    let width = Int((image.size.width * image.scale).rounded())
    let height = Int((image.size.height * image.scale).rounded())
    guard width > 0, height > 0 else { return nil }
    self.width = width
    self.height = height
    words = [UInt32](repeating: 0, count: width * height)
    let drawn = words.withUnsafeMutableBytes { raw -> Bool in
      guard
        let context = CGContext(
          data: raw.baseAddress, width: width, height: height, bitsPerComponent: 8,
          bytesPerRow: width * 4, space: Self.colorSpace, bitmapInfo: Self.bitmapInfo)
      else { return false }
      // Blit rather than blend: the destination is already clear, and a copy
      // is what keeps the round trip byte-exact.
      context.setBlendMode(.copy)
      context.interpolationQuality = .none
      let rect = CGRect(x: 0, y: 0, width: width, height: height)
      if image.imageOrientation == .up, let cgImage = image.cgImage {
        context.draw(cgImage, in: rect)
      } else {
        // UIKit draws with the origin top-left; flip the CG context to match
        // and let UIImage apply its own orientation.
        context.translateBy(x: 0, y: CGFloat(height))
        context.scaleBy(x: 1, y: -1)
        UIGraphicsPushContext(context)
        image.draw(in: rect)
        UIGraphicsPopContext()
      }
      return true
    }
    guard drawn else { return nil }
  }

  /// The buffer as a layer image: scale 1, orientation `.up`, the shape every
  /// raster operation in `EditorStore` expects.
  ///
  /// The bytes are copied once into the image's backing store; the buffer can
  /// be released as soon as this returns, so a caller holds at most the
  /// buffer and the result together, never a third copy.
  func makeImage() -> UIImage? {
    let data = words.withUnsafeBytes { Data($0) }
    guard let provider = CGDataProvider(data: data as CFData),
      let cgImage = CGImage(
        width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
        bytesPerRow: bytesPerRow, space: Self.colorSpace,
        bitmapInfo: CGBitmapInfo(rawValue: Self.bitmapInfo), provider: provider,
        decode: nil, shouldInterpolate: false, intent: .defaultIntent)
    else { return nil }
    return UIImage(cgImage: cgImage, scale: 1, orientation: .up)
  }

  /// One pixel of a layer image, as the word a full buffer would hold, read
  /// through a 1x1 context so that asking costs four bytes rather than a
  /// canvas. Nil off the image. The UI-test pixel probe uses this.
  static func probe(image: UIImage, x: Int, y: Int) -> UInt32? {
    guard let cgImage = image.cgImage, image.imageOrientation == .up else { return nil }
    let width = cgImage.width, height = cgImage.height
    guard x >= 0, y >= 0, x < width, y < height else { return nil }
    var word: UInt32 = 0
    let drawn = withUnsafeMutableBytes(of: &word) { raw -> Bool in
      guard
        let context = CGContext(
          data: raw.baseAddress, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
          space: colorSpace, bitmapInfo: bitmapInfo)
      else { return false }
      context.setBlendMode(.copy)
      context.interpolationQuality = .none
      // Core Graphics counts rows from the bottom; place the wanted pixel
      // over the context's single one.
      context.draw(
        cgImage, in: CGRect(x: -x, y: -(height - 1 - y), width: width, height: height))
      return true
    }
    return drawn ? word : nil
  }

  /// The premultiplied word at (x, y).
  func word(x: Int, y: Int) -> UInt32 {
    words[y * width + x]
  }

  mutating func setWord(_ word: UInt32, x: Int, y: Int) {
    words[y * width + x] = word
  }

  /// Read the words through a pointer without copying the array.
  func withWords<R>(_ body: (UnsafeBufferPointer<UInt32>) throws -> R) rethrows -> R {
    try words.withUnsafeBufferPointer(body)
  }

  /// Write the words through a pointer without copying the array.
  mutating func withMutableWords<R>(_ body: (UnsafeMutableBufferPointer<UInt32>) throws -> R)
    rethrows -> R
  {
    try words.withUnsafeMutableBufferPointer { try body($0) }
  }

  /// Visit the rows in bands of `bandRows`, each inside its own autorelease
  /// pool — the desktop's `for y0 in range(0, h, CHUNK_ROWS)` loop.
  ///
  /// An operation that needs a transient per row (a float plane, a blurred
  /// copy) allocates it for a band, not for the picture, and whatever
  /// Foundation autoreleases inside the band is released before the next one
  /// starts. Every row is visited exactly once; the last band is short when
  /// the height is not a multiple of `bandRows`.
  func forEachBand(_ body: (Range<Int>) throws -> Void) rethrows {
    try Self.forEachBand(height: height, body)
  }

  static func forEachBand(height: Int, _ body: (Range<Int>) throws -> Void) rethrows {
    var start = 0
    while start < height {
      let end = min(start + bandRows, height)
      try autoreleasepool { try body(start..<end) }
      start = end
    }
  }

  /// A premultiplied ARGB32 word from straight 8-bit channels, computed the
  /// way `photoslop.npimage.premultiplied_u32` does (`c * a / 255`, floored),
  /// so an ink chosen on either platform fills with the identical word.
  static func premultipliedWord(r: Int, g: Int, b: Int, a: Int) -> UInt32 {
    let pr = UInt32(r * a / 255)
    let pg = UInt32(g * a / 255)
    let pb = UInt32(b * a / 255)
    return (UInt32(a) << 24) | (pr << 16) | (pg << 8) | pb
  }

  /// `premultipliedWord` for a `UIColor`, with `opacity` (0...1) multiplied
  /// into its alpha the way the ink swatch shows it.
  static func premultipliedWord(color: UIColor, opacity: CGFloat = 1) -> UInt32 {
    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
    color.getRed(&r, green: &g, blue: &b, alpha: &a)
    func channel(_ value: CGFloat) -> Int { Int((min(1, max(0, value)) * 255).rounded()) }
    return premultipliedWord(
      r: channel(r), g: channel(g), b: channel(b),
      a: channel(a * min(1, max(0, opacity))))
  }

  // MARK: - Weighted writes (#370)

  /// `npimage.blend_by_weights` for one pixel: `original * (1 - w) + result
  /// * w` per premultiplied channel, rounded half up, with `w = weight / 255`
  /// — how every write through a feathered selection lands.
  static func blend(_ original: UInt32, toward result: UInt32, weight: UInt8) -> UInt32 {
    switch weight {
    case 0: return original
    case 255: return result
    default:
      let w = Float(weight) / 255
      var out: UInt32 = 0
      for shift in stride(from: 24, through: 0, by: -8) {
        let o = Float((original >> UInt32(shift)) & 0xFF)
        let r = Float((result >> UInt32(shift)) & 0xFF)
        let value = UInt32(min(max((o * (1 - w) + r * w + 0.5).rounded(.down), 0), 255))
        out |= value << UInt32(shift)
      }
      return out
    }
  }

  /// A stroke pixel composited over a layer pixel, source-over in
  /// premultiplied space, with the stroke first scaled by `weight / 255` —
  /// what ink through a selection leaves behind: nothing at weight 0, the
  /// stroke as PencilKit would have drawn it at 255.
  static func over(_ dst: UInt32, source: UInt32, weight: UInt8) -> UInt32 {
    let src = scaled(source, by: weight)
    let alpha = src >> 24
    guard alpha != 0 else { return dst }
    guard alpha != 255 else { return src }
    let keep = 255 - alpha
    var out: UInt32 = 0
    for shift in stride(from: 24, through: 0, by: -8) {
      let s = (src >> UInt32(shift)) & 0xFF
      let d = (dst >> UInt32(shift)) & 0xFF
      out |= min(255, s + (d * keep + 127) / 255) << UInt32(shift)
    }
    return out
  }

  /// A layer pixel with a stroke's coverage taken out of it, every channel
  /// alike — the eraser through a selection. `coverage` is the stroke pixel's
  /// alpha, scaled by `weight / 255` first.
  static func erased(_ dst: UInt32, by coverage: UInt32, weight: UInt8) -> UInt32 {
    let alpha = scaled(coverage, by: weight) >> 24
    guard alpha != 0 else { return dst }
    guard alpha != 255 else { return 0 }
    let keep = 255 - alpha
    var out: UInt32 = 0
    for shift in stride(from: 24, through: 0, by: -8) {
      let d = (dst >> UInt32(shift)) & 0xFF
      out |= ((d * keep + 127) / 255) << UInt32(shift)
    }
    return out
  }

  /// Every channel of a premultiplied word multiplied by `weight / 255`.
  private static func scaled(_ word: UInt32, by weight: UInt8) -> UInt32 {
    switch weight {
    case 0: return 0
    case 255: return word
    default:
      let w = UInt32(weight)
      var out: UInt32 = 0
      for shift in stride(from: 24, through: 0, by: -8) {
        let c = (word >> UInt32(shift)) & 0xFF
        out |= ((c * w + 127) / 255) << UInt32(shift)
      }
      return out
    }
  }
}

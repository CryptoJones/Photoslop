// SPDX-License-Identifier: Apache-2.0
import Compression
import UIKit
import UniformTypeIdentifiers

extension UTType {
  /// Adobe's registered type for `.psd`. The system knows it and it conforms
  /// to `public.image`, so the `.image` file importer already admits one.
  static let photoshopDocument = UTType("com.adobe.photoshop-image") ?? .image
  /// `.psb`, the large-document variant, has no system type; Info.plist
  /// imports this one so the document browser lists and opens it.
  static let photoshopLargeDocument = UTType(importedAs: "io.ronin48.photoslop.psb")
  static func isPhotoshop(_ type: UTType) -> Bool {
    type.conforms(to: .photoshopDocument) || type.conforms(to: .photoshopLargeDocument)
  }
}

enum PSDError: LocalizedError {
  case notPSD
  case truncated
  case unsupported(String)
  case resourceLimit(String)

  var errorDescription: String? {
    switch self {
    case .notPSD: "That file is not a Photoshop document."
    case .truncated: "The Photoshop document ends early; it may be damaged."
    case .unsupported(let what): "This Photoshop document uses \(what), which Photoslop cannot open."
    case .resourceLimit(let message): message
    }
  }
}

/// Photoshop `.psd` / `.psb` open and export — the iPad twin of the desktop's
/// `io_psd.py`, and byte-compatible with it.
///
/// Writes 8-bit RGB with per-layer RLE channels and a merged RGBA composite;
/// reads 8- and 16-bit RGB, Grayscale, CMYK, Indexed, Duotone and Bitmap with
/// raw, RLE and zip channels. The iPad layer model has no blend modes, groups
/// or masks, so on open a mask is multiplied into the layer's alpha, a hidden
/// folder hides its members, and blend modes and clipping are dropped.
enum PSDCodec {
  private static let signature: [UInt8] = Array("8BPS".utf8)
  private static let modeRGB: UInt16 = 3
  private static let resolutionResource: UInt16 = 0x03ED

  static func isPSD(_ data: Data) -> Bool {
    data.count >= 4 && Array(data.prefix(4)) == signature
  }

  // MARK: - Encoding

  /// The layer stack as a layered PSD. `onWhite` adds an opaque white
  /// background layer underneath, the layered equivalent of flattening onto
  /// white.
  static func encode(layers: [RasterLayer], canvasSize: CGSize, onWhite: Bool = false) -> Data? {
    let width = Int(canvasSize.width.rounded())
    let height = Int(canvasSize.height.rounded())
    guard width > 0, height > 0, width <= 30_000, height <= 30_000 else { return nil }
    var stack = layers
    if onWhite {
      stack.insert(
        RasterLayer(name: "Background", image: EditorStore.solidImage(size: canvasSize, color: .white)),
        at: 0)
    }
    var records = ByteWriter()
    var channelData = ByteWriter()
    var written = 0
    for layer in stack {
      guard let buffer = rasterize(layer, canvas: canvasSize) else { continue }
      appendLayer(
        buffer, name: layer.name, opacity: layer.opacity, fillOpacity: layer.fillOpacity,
        visible: layer.isVisible, records: &records, channels: &channelData)
      written += 1
    }
    guard let merged = PixelBuffer(image: EditorStore.render(layers: stack, size: canvasSize)) else {
      return nil
    }
    return assemble(
      width: width, height: height, layerCount: written, records: records.bytes,
      channelData: channelData.bytes, merged: merged)
  }

  /// One flat image as a single-layer PSD; what `ExportFormat.encode` uses.
  static func encode(flat image: UIImage) -> Data? {
    guard let buffer = PixelBuffer(image: image) else { return nil }
    var records = ByteWriter()
    var channelData = ByteWriter()
    appendLayer(
      buffer, name: "Background", opacity: 1, fillOpacity: 1, visible: true,
      records: &records, channels: &channelData)
    return assemble(
      width: buffer.width, height: buffer.height, layerCount: 1, records: records.bytes,
      channelData: channelData.bytes, merged: buffer)
  }

  /// A layer's own pixels plus its unbaked strokes over the whole canvas, at
  /// full opacity. Live effects are not baked, matching the desktop writer.
  private static func rasterize(_ layer: RasterLayer, canvas: CGSize) -> PixelBuffer? {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let image = UIGraphicsImageRenderer(size: canvas, format: format).image { _ in
      layer.image.draw(in: layer.frame, blendMode: .normal, alpha: 1)
      guard !layer.drawing.strokes.isEmpty else { return }
      let box = layer.drawing.bounds.intersection(CGRect(origin: .zero, size: canvas)).integral
      guard !box.isEmpty else { return }
      layer.drawing.literalImage(from: box, scale: 1).draw(in: box, blendMode: .normal, alpha: 1)
    }
    return PixelBuffer(image: image)
  }

  private static func appendLayer(
    _ buffer: PixelBuffer, name: String, opacity: Double, fillOpacity: Double, visible: Bool,
    records: inout ByteWriter, channels: inout ByteWriter
  ) {
    // Tight bounds around the painted pixels keep a signature in one corner
    // from costing a canvas-sized rectangle of transparent rows.
    var minX = buffer.width, minY = buffer.height, maxX = -1, maxY = -1
    for y in 0..<buffer.height {
      let row = y * buffer.width
      for x in 0..<buffer.width where buffer.words[row + x] >> 24 != 0 {
        if x < minX { minX = x }
        if x > maxX { maxX = x }
        if y < minY { minY = y }
        if y > maxY { maxY = y }
      }
    }
    if maxX < 0 { minX = 0; minY = 0; maxX = 0; maxY = 0 }  // empty layer: one clear pixel
    let w = maxX - minX + 1
    let h = maxY - minY + 1
    var planes = [[UInt8]](repeating: [UInt8](repeating: 0, count: w * h), count: 4)  // A R G B
    for y in 0..<h {
      for x in 0..<w {
        let word = buffer.words[(y + minY) * buffer.width + x + minX]
        let a = word >> 24
        let i = y * w + x
        planes[0][i] = UInt8(a)
        if a == 0 { continue }
        planes[1][i] = UInt8((((word >> 16) & 0xFF) * 255 + a / 2) / a)
        planes[2][i] = UInt8((((word >> 8) & 0xFF) * 255 + a / 2) / a)
        planes[3][i] = UInt8(((word & 0xFF) * 255 + a / 2) / a)
      }
    }
    let ids: [Int16] = [-1, 0, 1, 2]
    var encoded: [[UInt8]] = []
    for plane in planes {
      var out = ByteWriter()
      out.u16(1)
      let rows = (0..<h).map { packBits(Array(plane[($0 * w)..<(($0 + 1) * w)])) }
      for row in rows { out.u16(UInt16(row.count)) }
      for row in rows { out.bytes += row }
      encoded.append(out.bytes)
    }
    records.i32(Int32(minY))
    records.i32(Int32(minX))
    records.i32(Int32(maxY + 1))
    records.i32(Int32(maxX + 1))
    records.u16(4)
    for (id, bytes) in zip(ids, encoded) {
      records.i16(id)
      records.u32(UInt32(bytes.count))
      channels.bytes += bytes
    }
    records.bytes += Array("8BIMnorm".utf8)
    records.u8(UInt8((max(0, min(1, opacity)) * 255).rounded()))
    records.u8(0)  // not clipped
    records.u8(visible ? 0x08 : 0x0A)
    records.u8(0)
    var extra = ByteWriter()
    extra.u32(0)  // no mask
    extra.u32(0)  // no blending ranges
    extra.pascal(name, pad: 4)
    let utf16 = Array(name.utf16)
    var luni = ByteWriter()
    luni.u32(UInt32(utf16.count))
    for unit in utf16 { luni.u16(unit) }
    extra.infoBlock("luni", luni.bytes)
    if fillOpacity < 1 {
      extra.infoBlock("iOpa", [UInt8((max(0, fillOpacity) * 255).rounded()), 0, 0, 0])
    }
    records.u32(UInt32(extra.bytes.count))
    records.bytes += extra.bytes
  }

  private static func assemble(
    width: Int, height: Int, layerCount: Int, records: [UInt8], channelData: [UInt8],
    merged: PixelBuffer
  ) -> Data {
    var layerInfo = ByteWriter()
    layerInfo.i16(Int16(-layerCount))  // negative: the merged image carries alpha
    layerInfo.bytes += records
    layerInfo.bytes += channelData
    if layerInfo.bytes.count % 2 == 1 { layerInfo.u8(0) }

    var file = ByteWriter()
    file.bytes += signature
    file.u16(1)
    file.bytes += [UInt8](repeating: 0, count: 6)
    file.u16(4)
    file.u32(UInt32(height))
    file.u32(UInt32(width))
    file.u16(8)
    file.u16(modeRGB)
    file.u32(0)  // colour mode data
    var resources = ByteWriter()
    resources.bytes += Array("8BIM".utf8)
    resources.u16(resolutionResource)
    resources.u16(0)  // empty Pascal name, padded
    resources.u32(16)
    let dpi: Int32 = 72 << 16
    resources.i32(dpi); resources.u16(1); resources.u16(1)
    resources.i32(dpi); resources.u16(1); resources.u16(1)
    file.u32(UInt32(resources.bytes.count))
    file.bytes += resources.bytes
    file.u32(UInt32(layerInfo.bytes.count + 8))
    file.u32(UInt32(layerInfo.bytes.count))
    file.bytes += layerInfo.bytes
    file.u32(0)  // global layer mask info

    // Merged image: RLE, every channel's row counts first, then the rows.
    let count = width * height
    var planes = [[UInt8]](repeating: [UInt8](repeating: 0, count: count), count: 4)  // R G B A
    for i in 0..<count {
      let word = merged.words[i]
      let a = word >> 24
      planes[3][i] = UInt8(a)
      if a == 0 { continue }
      planes[0][i] = UInt8((((word >> 16) & 0xFF) * 255 + a / 2) / a)
      planes[1][i] = UInt8((((word >> 8) & 0xFF) * 255 + a / 2) / a)
      planes[2][i] = UInt8(((word & 0xFF) * 255 + a / 2) / a)
    }
    file.u16(1)
    var rows: [[UInt8]] = []
    rows.reserveCapacity(height * 4)
    for plane in planes {
      for y in 0..<height {
        rows.append(packBits(Array(plane[(y * width)..<((y + 1) * width)])))
      }
    }
    for row in rows { file.u16(UInt16(row.count)) }
    for row in rows { file.bytes += row }
    return Data(file.bytes)
  }

  /// PackBits: runs of three or more repeat, everything else is literal.
  static func packBits(_ row: [UInt8]) -> [UInt8] {
    var out: [UInt8] = []
    let n = row.count
    var i = 0
    while i < n {
      var run = 1
      while i + run < n, run < 128, row[i + run] == row[i] { run += 1 }
      if run >= 3 {
        out.append(UInt8(257 - run))
        out.append(row[i])
        i += run
        continue
      }
      let start = i
      while i < n, i - start < 128 {
        var ahead = 1
        while i + ahead < n, ahead < 3, row[i + ahead] == row[i] { ahead += 1 }
        if ahead >= 3 { break }
        i += 1
      }
      out.append(UInt8(i - start - 1))
      out += row[start..<i]
    }
    return out
  }

  // MARK: - Decoding

  private struct Header {
    var psb: Bool
    var channels: Int
    var width: Int
    var height: Int
    var depth: Int
    var mode: Int

    var colourChannels: Int {
      switch mode {
      case 4: 4
      case 3, 9: 3
      default: 1
      }
    }
  }

  private struct LayerRecord {
    var rect = (top: 0, left: 0, bottom: 0, right: 0)
    var channels: [(id: Int, length: Int)] = []
    var opacity = 1.0
    var fillOpacity = 1.0
    var hidden = false
    var name = ""
    var maskRect: (top: Int, left: Int, bottom: Int, right: Int)?
    var maskDefault: UInt8 = 255
    var maskFlags: UInt8 = 0
    var section: Int?

    var width: Int { max(0, rect.right - rect.left) }
    var height: Int { max(0, rect.bottom - rect.top) }
  }

  /// The document as editor state: canvas size, bottom-first layers, the top
  /// layer active.
  static func decode(_ data: Data) throws -> EditorState {
    guard data.count <= ProjectArchive.maximumProjectBytes else {
      throw PSDError.resourceLimit("That Photoshop document is larger than 1 GB.")
    }
    var reader = ByteReader(bytes: [UInt8](data))
    let header = try readHeader(&reader)
    let canvas = CGSize(width: header.width, height: header.height)
    guard ProjectArchive.isValidCanvas(canvas) else {
      throw PSDError.resourceLimit(
        "That document is \(header.width) × \(header.height) px, which is more than a canvas can be.")
    }
    let paletteLength = Int(try reader.u32())
    let palette = try reader.take(paletteLength)
    try skipResources(&reader)

    var layers: [RasterLayer] = []
    let layerMaskLength = try reader.length()
    let layerMaskEnd = reader.position + layerMaskLength
    var mergedHasAlpha = false
    if layerMaskLength > 0 {
      let layerInfoLength = try reader.length()
      let layerInfoEnd = reader.position + layerInfoLength
      if layerInfoLength > 0 {
        (layers, mergedHasAlpha) = try readLayerInfo(&reader, header: header, palette: palette, canvas: canvas)
      }
      reader.position = layerInfoEnd
      if layers.isEmpty, header.depth == 16 || header.depth == 32,
        var deep = try deepLayerBlock(&reader, end: layerMaskEnd)
      {
        // Photoshop keeps a 16/32-bit document's layers in a global
        // `Lr16`/`Lr32` block and leaves the main layer section empty.
        (layers, mergedHasAlpha) = try readLayerInfo(&deep, header: header, palette: palette, canvas: canvas)
      }
    }
    reader.position = layerMaskEnd
    if layers.isEmpty {
      let merged = try readMerged(&reader, header: header, hasAlpha: mergedHasAlpha, palette: palette)
      guard let image = merged.makeImage() else { throw PSDError.unsupported("an undecodable composite") }
      layers = [RasterLayer(name: "Background", image: image)]
    }
    return EditorState(layers: layers, activeLayerID: layers.last?.id, canvasSize: canvas)
  }

  /// (bottom-first layers, merged-has-alpha) from a layer info section.
  private static func readLayerInfo(
    _ reader: inout ByteReader, header: Header, palette: [UInt8], canvas: CGSize
  ) throws -> ([RasterLayer], Bool) {
    var layers: [RasterLayer] = []
    let signed = try reader.i16()
    let mergedHasAlpha = signed < 0
    let count = Int(abs(Int32(signed)))
    guard count <= ProjectArchive.maximumLayers else {
      throw PSDError.resourceLimit("That document has more than \(ProjectArchive.maximumLayers) layers.")
    }
    var records: [LayerRecord] = []
    for _ in 0..<count { records.append(try readLayerRecord(&reader)) }
    var pendingGroups: [[Int]] = []  // indices into `layers`, innermost group last
    for record in records {
      if record.section == 3 {
        try skipChannels(&reader, record)
        pendingGroups.append([])
        continue
      }
      if record.section == 1 || record.section == 2 {
        try skipChannels(&reader, record)
        let members = pendingGroups.popLast() ?? []
        if record.hidden { for index in members { layers[index].isVisible = false } }
        if !pendingGroups.isEmpty { pendingGroups[pendingGroups.count - 1] += members }
        continue
      }
      let layer = try readLayer(&reader, header: header, record: record, palette: palette, canvas: canvas)
      layers.append(layer)
      if !pendingGroups.isEmpty { pendingGroups[pendingGroups.count - 1].append(layers.count - 1) }
    }
    return (layers, mergedHasAlpha)
  }

  /// A reader over the `Lr16`/`Lr32` global block, or nil. `reader` sits just
  /// past the layer info; `end` closes the layer and mask section.
  private static func deepLayerBlock(_ reader: inout ByteReader, end: Int) throws -> ByteReader? {
    guard reader.position + 4 <= end else { return nil }
    let globalMask = Int(try reader.u32())
    reader.position += globalMask
    let pad = reader.psb ? 4 : 2
    while reader.position + 12 <= end {
      let signature = try reader.take(4)
      guard signature == Array("8BIM".utf8) || signature == Array("8B64".utf8) else { return nil }
      let key = String(decoding: try reader.take(4), as: UTF8.self)
      var length = (reader.psb && psbWideKeys.contains(key)) ? Int(try reader.u64()) : Int(try reader.u32())
      length = min(length, end - reader.position)
      let data = try reader.take(length)
      if key == "Lr16" || key == "Lr32" { return ByteReader(bytes: data, psb: reader.psb) }
      reader.position += (pad - length % pad) % pad
    }
    return nil
  }

  private static func readHeader(_ reader: inout ByteReader) throws -> Header {
    guard try reader.take(4) == signature else { throw PSDError.notPSD }
    let version = try reader.u16()
    guard version == 1 || version == 2 else { throw PSDError.unsupported("version \(version)") }
    reader.psb = version == 2
    _ = try reader.take(6)
    let channels = Int(try reader.u16())
    let height = Int(try reader.u32())
    let width = Int(try reader.u32())
    let depth = Int(try reader.u16())
    let mode = Int(try reader.u16())
    guard [1, 8, 16, 32].contains(depth) else { throw PSDError.unsupported("\(depth)-bit colour") }
    guard [0, 1, 2, 3, 4, 8, 9].contains(mode) else { throw PSDError.unsupported("colour mode \(mode)") }
    return Header(psb: reader.psb, channels: channels, width: width, height: height, depth: depth, mode: mode)
  }

  private static func skipResources(_ reader: inout ByteReader) throws {
    let length = Int(try reader.u32())
    _ = try reader.take(length)
  }

  private static func readRect(_ reader: inout ByteReader) throws -> (top: Int, left: Int, bottom: Int, right: Int) {
    let top = Int(try reader.i32())
    let left = Int(try reader.i32())
    let bottom = Int(try reader.i32())
    let right = Int(try reader.i32())
    return (top, left, bottom, right)
  }

  private static let psbWideKeys: Set<String> = [
    "LMsk", "Lr16", "Lr32", "Layr", "Mt16", "Mt32", "Mtrn", "Alph", "FMsk", "lnk2", "FEid", "FXid", "PxSD",
  ]

  private static func readLayerRecord(_ reader: inout ByteReader) throws -> LayerRecord {
    var record = LayerRecord()
    record.rect = try readRect(&reader)
    let channelCount = Int(try reader.u16())
    for _ in 0..<channelCount {
      let id = Int(try reader.i16())
      record.channels.append((id, try reader.length()))
    }
    guard try reader.take(4) == Array("8BIM".utf8) else { throw PSDError.truncated }
    _ = try reader.take(4)  // blend key: the iPad composites everything as normal
    record.opacity = Double(try reader.u8()) / 255
    _ = try reader.u8()  // clipping
    record.hidden = (try reader.u8()) & 0x02 != 0
    _ = try reader.u8()
    let extraLength = Int(try reader.u32())
    var extra = ByteReader(bytes: try reader.take(extraLength), psb: reader.psb)
    let maskLength = Int(try extra.u32())
    if maskLength >= 20 {
      var mask = ByteReader(bytes: try extra.take(maskLength), psb: reader.psb)
      record.maskRect = try readRect(&mask)
      record.maskDefault = try mask.u8()
      record.maskFlags = try mask.u8()
    } else if maskLength > 0 {
      _ = try extra.take(maskLength)
    }
    _ = try extra.take(Int(try extra.u32()))  // blending ranges
    record.name = try extra.pascal(pad: 4)
    while extra.remaining >= 12 {
      let sig = try extra.take(4)
      guard sig == Array("8BIM".utf8) || sig == Array("8B64".utf8) else { break }
      let key = String(decoding: try extra.take(4), as: UTF8.self)
      let size = (reader.psb && psbWideKeys.contains(key)) ? Int(try extra.u64()) : Int(try extra.u32())
      var payload = ByteReader(bytes: try extra.take(size), psb: reader.psb)
      if size % 2 == 1, extra.remaining > 0 { _ = try extra.take(1) }
      switch key {
      case "luni":
        let count = Int(try payload.u32())
        var units: [UInt16] = []
        units.reserveCapacity(count)
        for _ in 0..<count { units.append(try payload.u16()) }
        record.name = String(decoding: units, as: UTF16.self)
      case "lsct":
        record.section = Int(try payload.u32())
      case "iOpa":
        record.fillOpacity = Double(try payload.u8()) / 255
      default:
        break
      }
    }
    return record
  }

  private static func skipChannels(_ reader: inout ByteReader, _ record: LayerRecord) throws {
    for channel in record.channels { _ = try reader.take(channel.length) }
  }

  private static func readLayer(
    _ reader: inout ByteReader, header: Header, record: LayerRecord, palette: [UInt8], canvas: CGSize
  ) throws -> RasterLayer {
    let w = record.width
    let h = record.height
    guard w * h <= ProjectArchive.maximumPixels else {
      throw PSDError.resourceLimit("A layer in that document is larger than a canvas can be.")
    }
    var planes: [Int: [UInt8]] = [:]
    var maskPlane: [UInt8]?
    for channel in record.channels {
      var sub = ByteReader(bytes: try reader.take(channel.length), psb: reader.psb)
      guard channel.length >= 2 else { continue }
      let compression = Int(try sub.u16())
      if channel.id == -2, let maskRect = record.maskRect {
        let mw = max(0, maskRect.right - maskRect.left)
        let mh = max(0, maskRect.bottom - maskRect.top)
        guard mw > 0, mh > 0, mw * mh <= ProjectArchive.maximumPixels else { continue }
        maskPlane = try decodeChannel(&sub, compression: compression, width: mw, height: mh, depth: header.depth)
      } else if channel.id >= -1, w > 0, h > 0 {
        planes[channel.id] = try decodeChannel(
          &sub, compression: compression, width: w, height: h, depth: header.depth,
          srgb: header.depth == 32 && channel.id >= 0)
      }
    }
    let visible = !record.hidden
    guard w > 0, h > 0 else {
      return RasterLayer(
        name: record.name, image: clearPixel(), isVisible: visible, opacity: record.opacity,
        fillOpacity: record.fillOpacity)
    }
    var alpha = planes[-1] ?? [UInt8](repeating: 255, count: w * h)
    if let maskPlane, let maskRect = record.maskRect, record.maskFlags & 0x02 == 0 {
      applyMask(
        maskPlane, rect: maskRect, defaultValue: record.maskDefault, flags: record.maskFlags,
        layerRect: record.rect, into: &alpha, width: w, height: h)
    }
    let (r, g, b) = toRGB(mode: header.mode, planes: planes, count: w * h, palette: palette)
    // Keep what lies on the canvas: the editor positions a layer by its frame
    // and a frame hanging off the canvas edge is not a state it reaches itself.
    let left = max(0, record.rect.left)
    let top = max(0, record.rect.top)
    let right = min(Int(canvas.width), record.rect.right)
    let bottom = min(Int(canvas.height), record.rect.bottom)
    guard right > left, bottom > top else {
      return RasterLayer(
        name: record.name, image: clearPixel(), isVisible: visible, opacity: record.opacity,
        fillOpacity: record.fillOpacity)
    }
    let cw = right - left
    let ch = bottom - top
    var words = [UInt32](repeating: 0, count: cw * ch)
    for y in 0..<ch {
      let srcRow = (y + top - record.rect.top) * w + (left - record.rect.left)
      for x in 0..<cw {
        let i = srcRow + x
        let a = UInt32(alpha[i])
        guard a > 0 else { continue }
        let pr = (UInt32(r[i]) * a + 127) / 255
        let pg = (UInt32(g[i]) * a + 127) / 255
        let pb = (UInt32(b[i]) * a + 127) / 255
        words[y * cw + x] = (a << 24) | (pr << 16) | (pg << 8) | pb
      }
    }
    guard let image = PixelBuffer(width: cw, height: ch, words: words).makeImage() else {
      throw PSDError.unsupported("an undecodable layer")
    }
    return RasterLayer(
      name: record.name, image: image, isVisible: visible, opacity: record.opacity,
      fillOpacity: record.fillOpacity, origin: CGPoint(x: left, y: top))
  }

  private static func clearPixel() -> UIImage {
    PixelBuffer(width: 1, height: 1).makeImage() ?? UIImage()
  }

  private static func applyMask(
    _ mask: [UInt8], rect: (top: Int, left: Int, bottom: Int, right: Int), defaultValue: UInt8,
    flags: UInt8, layerRect: (top: Int, left: Int, bottom: Int, right: Int),
    into alpha: inout [UInt8], width: Int, height: Int
  ) {
    let mw = rect.right - rect.left
    // Mask rects are in canvas coordinates unless flagged layer-relative.
    let ox = flags & 0x01 != 0 ? 0 : layerRect.left
    let oy = flags & 0x01 != 0 ? 0 : layerRect.top
    let invert = flags & 0x04 != 0
    for y in 0..<height {
      let my = y + oy - rect.top
      for x in 0..<width {
        let mx = x + ox - rect.left
        var value = defaultValue
        if my >= 0, my < rect.bottom - rect.top, mx >= 0, mx < mw { value = mask[my * mw + mx] }
        if invert { value = 255 &- value }
        let i = y * width + x
        alpha[i] = UInt8((UInt32(alpha[i]) * UInt32(value) + 127) / 255)
      }
    }
  }

  private static func toRGB(
    mode: Int, planes: [Int: [UInt8]], count: Int, palette: [UInt8]
  ) -> ([UInt8], [UInt8], [UInt8]) {
    func plane(_ i: Int) -> [UInt8] { planes[i] ?? [UInt8](repeating: 0, count: count) }
    switch mode {
    case 3:
      return (plane(0), plane(1), plane(2))
    case 4:
      let c = plane(0), m = plane(1), yl = plane(2), k = plane(3)  // stored inverted: 255 = no ink
      var r = [UInt8](repeating: 0, count: count)
      var g = r, b = r
      for i in 0..<count {
        let kk = UInt32(k[i])
        r[i] = UInt8(UInt32(c[i]) * kk / 255)
        g[i] = UInt8(UInt32(m[i]) * kk / 255)
        b[i] = UInt8(UInt32(yl[i]) * kk / 255)
      }
      return (r, g, b)
    case 2 where palette.count >= 768:
      let idx = plane(0)
      var r = [UInt8](repeating: 0, count: count)
      var g = r, b = r
      for i in 0..<count {
        let p = Int(idx[i])
        r[i] = palette[p]
        g[i] = palette[256 + p]
        b[i] = palette[512 + p]
      }
      return (r, g, b)
    default:
      let gray = plane(0)
      return (gray, gray, gray)
    }
  }

  private static func readMerged(
    _ reader: inout ByteReader, header: Header, hasAlpha: Bool, palette: [UInt8]
  ) throws -> PixelBuffer {
    let compression = Int(try reader.u16())
    let w = header.width, h = header.height
    var planes: [Int: [UInt8]] = [:]
    if compression == 1 {
      var counts: [Int] = []
      counts.reserveCapacity(h * header.channels)
      for _ in 0..<(h * header.channels) {
        counts.append(reader.psb ? Int(try reader.u32()) : Int(try reader.u16()))
      }
      let rowBytes = rowBytes(width: w, depth: header.depth)
      for c in 0..<header.channels {
        var raw: [UInt8] = []
        raw.reserveCapacity(rowBytes * h)
        for y in 0..<h {
          raw += try unpackBits(try reader.take(counts[c * h + y]), expected: rowBytes)
        }
        var sub = ByteReader(bytes: raw, psb: reader.psb)
        planes[c] = try decodeChannel(
          &sub, compression: 0, width: w, height: h, depth: header.depth,
          srgb: header.depth == 32 && c < header.colourChannels)
      }
    } else {
      for c in 0..<header.channels {
        planes[c] = try decodeChannel(
          &reader, compression: compression, width: w, height: h, depth: header.depth,
          srgb: header.depth == 32 && c < header.colourChannels)
      }
    }
    let (r, g, b) = toRGB(mode: header.mode, planes: planes, count: w * h, palette: palette)
    let alpha = (hasAlpha && header.channels > header.colourChannels) ? planes[header.colourChannels] : nil
    var words = [UInt32](repeating: 0, count: w * h)
    for i in 0..<(w * h) {
      let a = UInt32(alpha?[i] ?? 255)
      guard a > 0 else { continue }
      let pr = (UInt32(r[i]) * a + 127) / 255
      let pg = (UInt32(g[i]) * a + 127) / 255
      let pb = (UInt32(b[i]) * a + 127) / 255
      words[i] = (a << 24) | (pr << 16) | (pg << 8) | pb
    }
    return PixelBuffer(width: w, height: h, words: words)
  }

  static func bytesPerSample(_ depth: Int) -> Int { depth == 32 ? 4 : (depth == 16 ? 2 : 1) }
  static func rowBytes(width: Int, depth: Int) -> Int {
    depth == 1 ? (width + 7) / 8 : width * bytesPerSample(depth)
  }

  /// A linear 0…1 sample as 8-bit sRGB (32-bit documents are linear light).
  static func srgb8(_ linear: Float) -> UInt8 {
    let v = linear.isNaN ? 0 : min(max(linear, 0), 1)
    let encoded = v <= 0.0031308 ? v * 12.92 : 1.055 * powf(v, 1 / 2.4) - 0.055
    return UInt8((encoded * 255).rounded())
  }

  /// One channel as an 8-bit plane; 16-bit samples keep their high byte and
  /// 32-bit floats are clipped to 0…1 (`srgb` marks a colour channel, which
  /// is sRGB-encoded on the way; alpha and masks scale linearly).
  private static func decodeChannel(
    _ reader: inout ByteReader, compression: Int, width: Int, height: Int, depth: Int, srgb: Bool = false
  ) throws -> [UInt8] {
    let bytesPerSample = bytesPerSample(depth)
    let rowBytes = rowBytes(width: width, depth: depth)
    let expected = rowBytes * height
    var raw: [UInt8]
    switch compression {
    case 0:
      raw = try reader.take(expected)
    case 1:
      var counts: [Int] = []
      counts.reserveCapacity(height)
      for _ in 0..<height { counts.append(reader.psb ? Int(try reader.u32()) : Int(try reader.u16())) }
      raw = []
      raw.reserveCapacity(expected)
      for count in counts { raw += try unpackBits(try reader.take(count), expected: rowBytes) }
    case 2, 3:
      let compressed = try reader.take(reader.remaining)
      raw = try inflate(compressed, expected: expected)
      if compression == 3 {
        if bytesPerSample == 4 {
          // A byte delta over the row, whose bytes are stored plane by
          // plane: all first bytes, then all second bytes, and so on.
          var row = [UInt8](repeating: 0, count: rowBytes)
          for y in 0..<height {
            let base = y * rowBytes
            for x in 1..<max(1, rowBytes) { raw[base + x] = raw[base + x] &+ raw[base + x - 1] }
            for x in 0..<width { for k in 0..<4 { row[x * 4 + k] = raw[base + k * width + x] } }
            raw.replaceSubrange(base..<(base + rowBytes), with: row)
          }
        } else if bytesPerSample == 2 {
          for y in 0..<height {
            var acc: UInt16 = 0
            for x in 0..<width {
              let i = y * rowBytes + x * 2
              acc = acc &+ (UInt16(raw[i]) << 8 | UInt16(raw[i + 1]))
              raw[i] = UInt8(acc >> 8)
              raw[i + 1] = UInt8(acc & 0xFF)
            }
          }
        } else {
          for y in 0..<height {
            for x in 1..<max(1, rowBytes) { raw[y * rowBytes + x] = raw[y * rowBytes + x] &+ raw[y * rowBytes + x - 1] }
          }
        }
      }
    default:
      throw PSDError.unsupported("compression \(compression)")
    }
    switch depth {
    case 1:
      var out = [UInt8](repeating: 0, count: width * height)
      for y in 0..<height {
        for x in 0..<width {
          let bit = (raw[y * rowBytes + x / 8] >> (7 - UInt8(x % 8))) & 1
          out[y * width + x] = bit == 1 ? 0 : 255  // bitmap mode: 1 = black
        }
      }
      return out
    case 16:
      var out = [UInt8](repeating: 0, count: width * height)
      for i in 0..<(width * height) { out[i] = raw[i * 2] }
      return out
    case 32:
      var out = [UInt8](repeating: 0, count: width * height)
      for i in 0..<(width * height) {
        let bits = UInt32(raw[i * 4]) << 24 | UInt32(raw[i * 4 + 1]) << 16
          | UInt32(raw[i * 4 + 2]) << 8 | UInt32(raw[i * 4 + 3])
        let value = Float(bitPattern: bits)
        out[i] = srgb ? srgb8(value) : UInt8((min(max(value.isNaN ? 0 : value, 0), 1) * 255).rounded())
      }
      return out
    default:
      return raw
    }
  }

  static func unpackBits(_ src: [UInt8], expected: Int) throws -> [UInt8] {
    var out: [UInt8] = []
    out.reserveCapacity(expected)
    var i = 0
    while i < src.count, out.count < expected {
      let header = Int(src[i])
      i += 1
      if header < 128 {
        let count = header + 1
        guard i + count <= src.count else { throw PSDError.truncated }
        out += src[i..<(i + count)]
        i += count
      } else if header > 128 {
        guard i < src.count else { throw PSDError.truncated }
        out += [UInt8](repeating: src[i], count: 257 - header)
        i += 1
      }
    }
    guard out.count >= expected else { throw PSDError.truncated }
    return Array(out.prefix(expected))
  }

  /// zlib-wrapped deflate, as Photoshop writes it: two header bytes, then
  /// the raw stream `Compression` understands.
  private static func inflate(_ src: [UInt8], expected: Int) throws -> [UInt8] {
    guard src.count > 2 else { throw PSDError.truncated }
    var out = [UInt8](repeating: 0, count: expected)
    let produced = src.withUnsafeBufferPointer { input -> Int in
      out.withUnsafeMutableBufferPointer { output in
        compression_decode_buffer(
          output.baseAddress!, expected, input.baseAddress! + 2, src.count - 2, nil, COMPRESSION_ZLIB)
      }
    }
    guard produced == expected else { throw PSDError.truncated }
    return out
  }
}

// MARK: - Byte helpers

private struct ByteWriter {
  var bytes: [UInt8] = []

  mutating func u8(_ v: UInt8) { bytes.append(v) }
  mutating func u16(_ v: UInt16) { bytes += [UInt8(v >> 8), UInt8(v & 0xFF)] }
  mutating func i16(_ v: Int16) { u16(UInt16(bitPattern: v)) }
  mutating func u32(_ v: UInt32) {
    bytes += [UInt8(v >> 24), UInt8((v >> 16) & 0xFF), UInt8((v >> 8) & 0xFF), UInt8(v & 0xFF)]
  }
  mutating func i32(_ v: Int32) { u32(UInt32(bitPattern: v)) }

  mutating func pascal(_ name: String, pad: Int) {
    let raw = Array(name.utf8.prefix(255))
    u8(UInt8(raw.count))
    bytes += raw
    let total = 1 + raw.count
    if total % pad != 0 { bytes += [UInt8](repeating: 0, count: pad - total % pad) }
  }

  mutating func infoBlock(_ key: String, _ payload: [UInt8]) {
    var body = payload
    if body.count % 2 == 1 { body.append(0) }
    bytes += Array("8BIM".utf8) + Array(key.utf8)
    u32(UInt32(body.count))
    bytes += body
  }
}

private struct ByteReader {
  let bytes: [UInt8]
  var position = 0
  var psb = false

  init(bytes: [UInt8], psb: Bool = false) {
    self.bytes = bytes
    self.psb = psb
  }

  var remaining: Int { bytes.count - position }

  mutating func take(_ n: Int) throws -> [UInt8] {
    guard n >= 0, position + n <= bytes.count else { throw PSDError.truncated }
    defer { position += n }
    return Array(bytes[position..<(position + n)])
  }

  mutating func u8() throws -> UInt8 { try take(1)[0] }
  mutating func u16() throws -> UInt16 {
    let b = try take(2)
    return UInt16(b[0]) << 8 | UInt16(b[1])
  }
  mutating func i16() throws -> Int16 { Int16(bitPattern: try u16()) }
  mutating func u32() throws -> UInt32 {
    let b = try take(4)
    return UInt32(b[0]) << 24 | UInt32(b[1]) << 16 | UInt32(b[2]) << 8 | UInt32(b[3])
  }
  mutating func i32() throws -> Int32 { Int32(bitPattern: try u32()) }
  mutating func u64() throws -> UInt64 {
    let high = UInt64(try u32())
    return high << 32 | UInt64(try u32())
  }
  /// A section length: 4 bytes in a PSD, 8 in a PSB.
  mutating func length() throws -> Int { psb ? Int(try u64()) : Int(try u32()) }

  mutating func pascal(pad: Int) throws -> String {
    let n = Int(try u8())
    let raw = try take(n)
    let total = 1 + n
    if total % pad != 0 { _ = try take(pad - total % pad) }
    return String(decoding: raw, as: UTF8.self)
  }
}

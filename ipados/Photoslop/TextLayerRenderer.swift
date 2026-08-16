// SPDX-License-Identifier: Apache-2.0
import UIKit

/// Rasterises plain text into a layer, mirroring the desktop `--text` op.
///
/// `photoslop-cli --text "X,Y,SIZE[,R,G,B]:TEXT"` renders onto a **new layer**
/// whose top-left sits at the anchor, so text placed on either surface lands in
/// the same spot. The one difference is the canvas: desktop layers carry their
/// own offset and can be tight around the glyphs, while an iPad project
/// validates that every layer image matches the canvas exactly, so the text is
/// drawn at the anchor inside a full-canvas transparent image instead.
enum TextLayerRenderer {
  /// Matches the desktop's naming: the first line, truncated, or "Text".
  static func layerName(for text: String) -> String {
    let firstLine = text.split(separator: "\n", omittingEmptySubsequences: false).first ?? ""
    let trimmed = firstLine.trimmingCharacters(in: .whitespaces)
    return trimmed.isEmpty ? "Text" : String(trimmed.prefix(24))
  }

  /// The face for a stored family name, or the system font when there is
  /// none — including a family that left the OS since the document was saved,
  /// which must degrade to readable rather than fail to render.
  static func font(family: String?, size: CGFloat) -> UIFont {
    guard let family, let named = UIFont(name: family, size: max(1, size)) else {
      return UIFont.systemFont(ofSize: max(1, size))
    }
    return named
  }

  /// How much room the words take at this size.
  ///
  /// The placement box needs this twice: to open around text that is already on
  /// the canvas, and to work out what size the type must be for the words to
  /// span a box the user has dragged.
  /// `wrapWidth` constrains layout: lines break to stay inside it, and the
  /// height grows instead. Nil is the historical single-line-per-newline
  /// behaviour.
  static func measure(
    text: String, fontSize: CGFloat, fontFamily: String? = nil, wrapWidth: CGFloat? = nil
  ) -> CGSize {
    let body = text.trimmingCharacters(in: .newlines)
    guard !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return .zero }
    let attributes: [NSAttributedString.Key: Any] = [
      .font: font(family: fontFamily, size: fontSize)
    ]
    let bounds = NSAttributedString(string: body, attributes: attributes).boundingRect(
      with: CGSize(
        width: wrapWidth ?? CGFloat.greatestFiniteMagnitude,
        height: CGFloat.greatestFiniteMagnitude),
      options: [.usesLineFragmentOrigin, .usesFontLeading],
      context: nil)
    return CGSize(width: ceil(bounds.width), height: ceil(bounds.height))
  }

  /// The largest font size whose wrapped layout fits inside `box` — what
  /// "fit this text to the region I dragged" means (#296). The words wrap at
  /// the box's width and the type grows until width or height runs out; the
  /// first version measured a single line, so a caption fitted to a square
  /// stayed one long tiny strip across it.
  static func fittingFontSize(
    text: String, fontFamily: String? = nil, in box: CGSize
  ) -> CGFloat? {
    guard box.width > 4, box.height > 4,
      !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    else { return nil }
    var low: CGFloat = 1
    var high: CGFloat = 1024
    for _ in 0..<24 {
      let mid = (low + high) / 2
      let measured = measure(text: text, fontSize: mid, fontFamily: fontFamily, wrapWidth: box.width)
      if measured.width <= box.width, measured.height <= box.height {
        low = mid
      } else {
        high = mid
      }
    }
    return max(1, low.rounded(.down))
  }

  /// Nil when there is nothing to draw, matching the desktop returning no layer
  /// for blank input rather than adding an empty one.
  static func render(
    text: String,
    fontSize: CGFloat,
    color: UIColor,
    at anchor: CGPoint,
    canvasSize: CGSize,
    fontFamily: String? = nil,
    wrapWidth: CGFloat? = nil
  ) -> UIImage? {
    let body = text.trimmingCharacters(in: .newlines)
    guard !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      canvasSize.width > 0, canvasSize.height > 0
    else { return nil }

    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .left
    let attributes: [NSAttributedString.Key: Any] = [
      .font: font(family: fontFamily, size: fontSize),
      .foregroundColor: color,
      .paragraphStyle: paragraph,
    ]

    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: canvasSize, format: format).image { _ in
      // The same 2 px inset the desktop renderer uses, so antialiased edges are
      // not clipped at the anchor.
      let pad: CGFloat = 2
      let origin = CGPoint(x: anchor.x + pad, y: anchor.y + pad)
      // A fitted layer wraps at its box's width wherever the box sits; an
      // unfitted one lays out to the canvas edge, as it always has.
      let available = CGSize(
        width: wrapWidth ?? max(1, canvasSize.width - origin.x),
        height: max(1, canvasSize.height - origin.y)
      )
      NSAttributedString(string: body, attributes: attributes)
        .draw(with: CGRect(origin: origin, size: available),
              options: [.usesLineFragmentOrigin, .usesFontLeading],
              context: nil)
    }
  }

  /// Just the words, on a transparent image sized tight around them.
  ///
  /// This is what the placement box shows while text is being fitted: an image
  /// scaled into the box previews the committed size honestly, in the current
  /// face and colour. The first preview cropped the glyphs out of the layer's
  /// canvas-sized rendering instead, and on device that produced nothing to
  /// show — rendering the words directly cannot miss.
  static func glyphs(
    text: String,
    fontSize: CGFloat,
    color: UIColor,
    fontFamily: String? = nil,
    wrapWidth: CGFloat? = nil
  ) -> UIImage? {
    let measured = measure(
      text: text, fontSize: fontSize, fontFamily: fontFamily, wrapWidth: wrapWidth)
    guard measured.width > 0, measured.height > 0 else { return nil }

    let pad: CGFloat = 2
    let size = CGSize(width: measured.width + 2 * pad, height: measured.height + 2 * pad)
    let attributes: [NSAttributedString.Key: Any] = [
      .font: font(family: fontFamily, size: fontSize),
      .foregroundColor: color,
    ]
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    return UIGraphicsImageRenderer(size: size, format: format).image { _ in
      NSAttributedString(string: text.trimmingCharacters(in: .newlines), attributes: attributes)
        .draw(with: CGRect(origin: CGPoint(x: pad, y: pad), size: measured),
              options: [.usesLineFragmentOrigin, .usesFontLeading],
              context: nil)
    }
  }
}

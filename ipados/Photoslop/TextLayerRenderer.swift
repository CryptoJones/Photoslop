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

  /// How much room the words take at this size.
  ///
  /// The placement box needs this twice: to open around text that is already on
  /// the canvas, and to work out what size the type must be for the words to
  /// span a box the user has dragged.
  static func measure(text: String, fontSize: CGFloat) -> CGSize {
    let body = text.trimmingCharacters(in: .newlines)
    guard !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return .zero }
    let attributes: [NSAttributedString.Key: Any] = [
      .font: UIFont.systemFont(ofSize: max(1, fontSize))
    ]
    let bounds = NSAttributedString(string: body, attributes: attributes).boundingRect(
      with: CGSize(
        width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude),
      options: [.usesLineFragmentOrigin, .usesFontLeading],
      context: nil)
    return CGSize(width: ceil(bounds.width), height: ceil(bounds.height))
  }

  /// Nil when there is nothing to draw, matching the desktop returning no layer
  /// for blank input rather than adding an empty one.
  static func render(
    text: String,
    fontSize: CGFloat,
    color: UIColor,
    at anchor: CGPoint,
    canvasSize: CGSize
  ) -> UIImage? {
    let body = text.trimmingCharacters(in: .newlines)
    guard !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      canvasSize.width > 0, canvasSize.height > 0
    else { return nil }

    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .left
    let attributes: [NSAttributedString.Key: Any] = [
      .font: UIFont.systemFont(ofSize: max(1, fontSize)),
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
      let available = CGSize(
        width: max(1, canvasSize.width - origin.x),
        height: max(1, canvasSize.height - origin.y)
      )
      NSAttributedString(string: body, attributes: attributes)
        .draw(with: CGRect(origin: origin, size: available),
              options: [.usesLineFragmentOrigin, .usesFontLeading],
              context: nil)
    }
  }
}

// SPDX-License-Identifier: Apache-2.0
import QuickLookThumbnailing
import UIKit

/// Draws the Files-app thumbnail for a `.photoslop` document.
///
/// It only ever reads the `preview.png` the editor wrote at save time (#267):
/// compositing the real layers means decoding every layer PNG plus PencilKit
/// data inside an extension's memory budget, for a picture the app already
/// rendered more cheaply when it saved. A document from before previews were
/// written has no `preview.png`; reporting the error leaves the generic icon,
/// which is exactly what those documents showed before, until their next save.
final class ThumbnailProvider: QLThumbnailProvider {
  override func provideThumbnail(
    for request: QLFileThumbnailRequest,
    _ handler: @escaping (QLThumbnailReply?, Error?) -> Void
  ) {
    let previewURL = request.fileURL.appendingPathComponent("preview.png")
    guard let image = UIImage(contentsOfFile: previewURL.path), image.size.width > 0,
      image.size.height > 0
    else {
      handler(nil, CocoaError(.fileReadNoSuchFile))
      return
    }

    // Aspect-fit inside what Files asked for; the reply's context is exactly
    // the fitted size, so Files adds no letterboxing of its own.
    let maximum = request.maximumSize
    let scale = min(maximum.width / image.size.width, maximum.height / image.size.height)
    let fitted = CGSize(
      width: max(1, image.size.width * scale),
      height: max(1, image.size.height * scale)
    )
    handler(
      QLThumbnailReply(contextSize: fitted) {
        image.draw(in: CGRect(origin: .zero, size: fitted))
        return true
      },
      nil
    )
  }
}

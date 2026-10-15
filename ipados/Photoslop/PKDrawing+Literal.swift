// SPDX-License-Identifier: Apache-2.0
import PencilKit
import UIKit

extension PKDrawing {
  /// The strokes rasterised with their colours taken literally.
  ///
  /// PencilKit treats an ink's colour as a *light-mode* value and swaps it for
  /// display under a dark trait collection: black paints white, white paints
  /// black, and mid-tones pass through. That is right for notes on a themed
  /// page and wrong for paint on a picture, so the on-screen canvas pins
  /// itself to light (`PencilCanvas`). `image(from:scale:)` has no view to
  /// pin and renders under whatever trait collection is current — which,
  /// with the app a dark studio (`UIUserInterfaceStyle: Dark`), is dark
  /// everywhere: the composite, the bake through a selection, the sample
  /// under the eyedropper, the document preview and the layer thumbnail all
  /// drew black strokes as white. The unit tests caught it the moment the
  /// plist key landed. Every offscreen render goes through here, so the
  /// pixels are the ones the user chose whatever the appearance — including
  /// on a device that was already in dark mode before the app was.
  func literalImage(from rect: CGRect, scale: CGFloat) -> UIImage {
    var image = UIImage()
    UITraitCollection(userInterfaceStyle: .light).performAsCurrent {
      image = self.image(from: rect, scale: scale)
    }
    return image
  }
}

// SPDX-License-Identifier: Apache-2.0
import SwiftUI

/// The marching ants (#326): the selection's boundary, stroked white under a
/// black dash whose phase walks, so the border reads on any picture.
///
/// Hosted inside `PencilCanvas`'s overlay, which lives in document pixels, so
/// the outline is drawn where the selection is and pans and zooms with the
/// artwork for free. Only the *chrome* is corrected for zoom: the line width
/// and the dash are divided by `scale`, so the ants stay one screen point wide
/// at every magnification instead of turning into a fat border zoomed in and
/// a hairline zoomed out — the same idea `CanvasBox` uses for its handles.
///
/// Building the outline walks every pixel edge once, which is fine for a tap
/// but not for every animation frame, so the path is built once per selection
/// (keyed by `SelectionMask.id`) and only the dash phase changes. A very busy
/// border — a wand over a noisy photograph can leave tens of thousands of
/// segments — is drawn once and left still rather than re-stroked ten times a
/// second.
struct SelectionOutline: View {
  let selection: SelectionMask
  let scale: CGFloat

  /// Past this many segments the ants stand still.
  static let animatedSegmentLimit = 40_000
  /// One step of the walk, in screen points.
  static let dashLength: CGFloat = 4

  @State private var outline: (id: UUID, path: Path, segments: Int)?

  var body: some View {
    let size = CGSize(width: selection.width, height: selection.height)
    Group {
      if let outline, outline.id == selection.id {
        if outline.segments <= Self.animatedSegmentLimit {
          TimelineView(.periodic(from: .now, by: 0.12)) { context in
            let step = context.date.timeIntervalSinceReferenceDate / 0.12
            ants(outline.path, phase: CGFloat(step.truncatingRemainder(dividingBy: 2)) * Self.dashLength)
          }
        } else {
          ants(outline.path, phase: 0)
        }
      } else {
        Color.clear
      }
    }
    .frame(width: size.width, height: size.height)
    .allowsHitTesting(false)
    .accessibilityHidden(true)
    .onChange(of: selection.id, initial: true) { _, _ in rebuild() }
  }

  /// Stroked as shapes, the way `CanvasBox` draws its hairlines, rather than
  /// into a `Canvas`: a shape is drawn in the same pass as the rest of the
  /// view, while anything that rasterises a document-sized view into its own
  /// bitmap costs a canvas of memory (#309).
  private func ants(_ path: Path, phase: CGFloat) -> some View {
    let zoom = max(scale, 0.0001)
    let width = 1 / zoom
    let dash = Self.dashLength / zoom
    return ZStack(alignment: .topLeading) {
      path.stroke(.white, lineWidth: width)
      path.stroke(
        .black, style: StrokeStyle(lineWidth: width, dash: [dash, dash], dashPhase: phase / zoom))
    }
  }

  private func rebuild() {
    let segments = selection.outlineSegments()
    var path = Path()
    for (a, b) in segments {
      path.move(to: a)
      path.addLine(to: b)
    }
    outline = (selection.id, path, segments.count)
  }
}

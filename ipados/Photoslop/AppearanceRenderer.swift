// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import UIKit

/// A single-channel float plane, row-major — the desktop's `np.float32`
/// alpha array, which is what every appearance effect is computed on.
struct AlphaPlane: Equatable {
  let width: Int
  let height: Int
  var values: [Float]

  init(width: Int, height: Int, values: [Float]) {
    precondition(values.count == width * height, "plane size must match its values")
    self.width = width
    self.height = height
    self.values = values
  }

  init(width: Int, height: Int, fill: Float = 0) {
    self.init(width: width, height: height, values: [Float](repeating: fill, count: width * height))
  }

  subscript(x: Int, y: Int) -> Float {
    get { values[y * width + x] }
    set { values[y * width + x] = newValue }
  }
}

/// One rendered effect layer: a premultiplied bitmap and where it sits
/// relative to the layer's own top-left. The desktop's `appearance.Plane`.
struct EffectPlane {
  let buffer: PixelBuffer
  /// Offset from the source image's top-left, in pixels.
  let offsetX: Int
  let offsetY: Int
  /// Under the fill (a shadow, a glow) or over it (an overlay, a bevel).
  let under: Bool
  let blendMode: String
  let opacity: Double
}

/// The iOS port of `photoslop.appearance.render` (#316).
///
/// Every effect is derived from the layer's alpha: pad it, grow or shrink it,
/// blur it, shift it, colourise it, and stack the result under or over the
/// fill. The arithmetic is the desktop's step for step — the same three-pass
/// box blur over the same `float32` cumulative sums, the same truncating
/// colourise — so `scripts/gen-appearance-fixture.py` can write what the
/// desktop produced and `AppearanceParityTests` can demand it back.
///
/// **Memory (DD-001).** Planes are layer-sized-plus-padding `Float` arrays
/// and live only inside the composite that asked for them: nothing here is
/// cached per layer, so a document with effects costs no resident bitmaps
/// beyond the layers themselves. A text layer is already its tight glyph box
/// (#309), which is what keeps these transients small in the case the feature
/// exists for; a full-canvas raster layer is cropped to its opaque bounds
/// first (`sourcePlane`).
enum AppearanceRenderer {
  /// The layer's alpha as a plane, cropped to where it is opaque, and where
  /// that crop sits in the layer. Nil when the layer is fully transparent or
  /// its pixels cannot be read.
  ///
  /// The crop is widened by the stack's reach so a shadow cast off the edge
  /// of the opaque box is not cut short; a bounded text layer is normally
  /// smaller than that and used whole, which is also what keeps its result
  /// identical to the desktop's, which never crops.
  static func sourcePlane(
    of image: UIImage, effects: [LayerEffect]
  ) -> (plane: AlphaPlane, originX: Int, originY: Int)? {
    guard let buffer = PixelBuffer(image: image) else { return nil }
    let width = buffer.width, height = buffer.height
    var minX = width, minY = height, maxX = -1, maxY = -1
    buffer.withWords { words in
      for y in 0..<height {
        let row = y * width
        for x in 0..<width where words[row + x] >> 24 != 0 {
          if x < minX { minX = x }
          if x > maxX { maxX = x }
          if y < minY { minY = y }
          if y > maxY { maxY = y }
        }
      }
    }
    guard maxX >= 0 else { return nil }
    let reach = margin(of: effects) * 2
    let x0 = max(0, minX - reach), y0 = max(0, minY - reach)
    let x1 = min(width, maxX + 1 + reach), y1 = min(height, maxY + 1 + reach)
    var plane = AlphaPlane(width: x1 - x0, height: y1 - y0)
    buffer.withWords { words in
      for y in y0..<y1 {
        let row = y * width
        for x in x0..<x1 {
          plane[x - x0, y - y0] = Float((words[row + x] >> 24) & 0xFF)
        }
      }
    }
    return (plane, x0, y0)
  }

  /// `appearance.effect_margin`: how far any of these effects can reach
  /// beyond the layer.
  static func margin(of effects: [LayerEffect]) -> Int {
    var margin = 0
    for effect in effects where effect.enabled {
      switch effect.kind {
      case "drop-shadow":
        margin = max(
          margin,
          pyRound(
            effect.number("blur") + effect.number("spread")
              + max(abs(effect.number("offset_x")), abs(effect.number("offset_y")))))
      case "outer-glow":
        margin = max(margin, pyRound(effect.number("size") + effect.number("spread")))
      case "outline":
        margin = max(margin, pyRound(effect.number("width")))
      case "gaussian-blur", "feather":
        margin = max(margin, pyRound(effect.number("radius") * 2))
      default:
        break
      }
    }
    return margin
  }

  /// Python's `round()`: to the nearest integer, ties to even.
  static func pyRound(_ value: Double) -> Int {
    Int(value.rounded(.toNearestOrEven))
  }

  // MARK: Plane arithmetic — `appearance.py` helpers, in its order

  /// `npimage._box_blur_plane`: one box pass of radius `r`, as a running sum
  /// down each column and then along each row, truncated at the edges, every
  /// term in `Float` so the rounding is the desktop's.
  ///
  /// The desktop raises for a plane narrower than `r + 1`; here the radius is
  /// clamped instead, which only matters for planes too small to blur.
  static func boxBlur(_ plane: AlphaPlane, r radius: Int) -> AlphaPlane {
    let width = plane.width, height = plane.height
    guard width > 0, height > 0 else { return plane }
    let r = max(0, min(radius, width - 1, height - 1))
    let k = Float(2 * r + 1)
    var out = plane
    var csum = [Float](repeating: 0, count: width * height)
    // Down the columns.
    for x in 0..<width {
      var running: Float = 0
      for y in 0..<height {
        running += plane.values[y * width + x]
        csum[y * width + x] = running
      }
    }
    for y in 0..<height {
      let ahead = min(y + r, height - 1) * width
      let behind = y >= r + 1 ? (y - r - 1) * width : -1
      for x in 0..<width {
        let lead = csum[ahead + x]
        let trail: Float = behind >= 0 ? csum[behind + x] : 0
        out.values[y * width + x] = (lead - trail) / k
      }
    }
    // Along the rows.
    for y in 0..<height {
      let row = y * width
      var running: Float = 0
      for x in 0..<width {
        running += out.values[row + x]
        csum[row + x] = running
      }
    }
    for y in 0..<height {
      let row = y * width
      for x in 0..<width {
        let lead = csum[row + min(x + r, width - 1)]
        let trail: Float = x >= r + 1 ? csum[row + x - r - 1] : 0
        out.values[row + x] = (lead - trail) / k
      }
    }
    return out
  }

  /// `appearance._blur_plane`: three box passes of radius `radius / 2 + 1`.
  static func blur(_ plane: AlphaPlane, radius: Int) -> AlphaPlane {
    guard radius > 0 else { return plane }
    let r = max(1, radius / 2 + 1)
    var result = plane
    for _ in 0..<3 { result = boxBlur(result, r: r) }
    return result
  }

  /// `appearance._morph`: threshold at 1, then dilate or erode `amount`
  /// times with a 3x3 structuring element, back to a 0/255 plane.
  static func morph(_ plane: AlphaPlane, amount: Int, grow: Bool) -> AlphaPlane {
    let width = plane.width, height = plane.height
    var mask = plane.values.map { $0 > 1 }
    for _ in 0..<max(0, amount) {
      var next = mask
      for y in 0..<height {
        for x in 0..<width {
          var hit = !grow
          for dy in -1...1 {
            let ny = y + dy
            for dx in -1...1 {
              let nx = x + dx
              let inside = nx >= 0 && nx < width && ny >= 0 && ny < height
              let value = inside ? mask[ny * width + nx] : false
              if grow {
                if value { hit = true }
              } else if !value {
                hit = false
              }
            }
          }
          next[y * width + x] = hit
        }
      }
      mask = next
    }
    return AlphaPlane(width: width, height: height, values: mask.map { $0 ? 255 : 0 })
  }

  /// `appearance._color_image`: a plane as a premultiplied bitmap of one
  /// colour, the plane scaling the colour's alpha. Truncates exactly where
  /// the desktop's `astype(np.uint32)` does.
  static func colorImage(_ plane: AlphaPlane, rgba: [Int]) -> PixelBuffer {
    let color = rgba.count == 4 ? rgba : [0, 0, 0, 255]
    let alphaScale = Float(color[3])
    var buffer = PixelBuffer(width: max(1, plane.width), height: max(1, plane.height))
    buffer.withMutableWords { words in
      for index in 0..<plane.values.count {
        // `np.clip(alpha * a / 255.0, 0, 255).astype(np.uint32)`, in float32.
        let scaled = plane.values[index] * alphaScale / Float(255.0)
        let a = UInt32(max(0, min(255, scaled)))
        // `scale = a / 255.0` promotes to float64 on the desktop.
        let scale = Double(a) / 255.0
        let r = UInt32(Double(color[0]) * scale)
        let g = UInt32(Double(color[1]) * scale)
        let b = UInt32(Double(color[2]) * scale)
        words[index] = (a << 24) | (r << 16) | (g << 8) | b
      }
    }
    return buffer
  }

  /// `appearance._padded_alpha`: the plane with `pad` transparent pixels
  /// on every side.
  static func padded(_ plane: AlphaPlane, pad: Int) -> AlphaPlane {
    guard pad > 0 else { return plane }
    var out = AlphaPlane(width: plane.width + pad * 2, height: plane.height + pad * 2)
    for y in 0..<plane.height {
      for x in 0..<plane.width {
        out[x + pad, y + pad] = plane[x, y]
      }
    }
    return out
  }

  /// `appearance._shift`: the plane moved by (dx, dy), the vacated edge
  /// transparent.
  static func shift(_ plane: AlphaPlane, dx: Int, dy: Int) -> AlphaPlane {
    var out = AlphaPlane(width: plane.width, height: plane.height)
    let x0 = max(0, dx), x1 = min(plane.width, plane.width + dx)
    let y0 = max(0, dy), y1 = min(plane.height, plane.height + dy)
    guard x1 > x0, y1 > y0 else { return out }
    let sx0 = max(0, -dx), sy0 = max(0, -dy)
    for y in y0..<y1 {
      for x in x0..<x1 {
        out[x, y] = plane[sx0 + x - x0, sy0 + y - y0]
      }
    }
    return out
  }

  /// `np.gradient` along both axes: central differences inside, one-sided
  /// at the edges, in `Float`. An axis of length one has no gradient.
  static func gradient(_ plane: AlphaPlane) -> (gy: AlphaPlane, gx: AlphaPlane) {
    let width = plane.width, height = plane.height
    var gy = AlphaPlane(width: width, height: height)
    var gx = AlphaPlane(width: width, height: height)
    if height >= 2 {
      for x in 0..<width {
        gy[x, 0] = (plane[x, 1] - plane[x, 0]) / Float(1.0)
        gy[x, height - 1] = (plane[x, height - 1] - plane[x, height - 2]) / Float(1.0)
        if height > 2 {
          for y in 1..<(height - 1) {
            gy[x, y] = (plane[x, y + 1] - plane[x, y - 1]) / Float(2.0)
          }
        }
      }
    }
    if width >= 2 {
      for y in 0..<height {
        gx[0, y] = (plane[1, y] - plane[0, y]) / Float(1.0)
        gx[width - 1, y] = (plane[width - 1, y] - plane[width - 2, y]) / Float(1.0)
        if width > 2 {
          for x in 1..<(width - 1) {
            gx[x, y] = (plane[x + 1, y] - plane[x - 1, y]) / Float(2.0)
          }
        }
      }
    }
    return (gy, gx)
  }

  /// `appearance._gradient_image`: a linear gradient through the source's
  /// alpha, premultiplied.
  static func gradientImage(_ alpha: AlphaPlane, effect: LayerEffect) -> PixelBuffer {
    let width = alpha.width, height = alpha.height
    let angle = (effect.number("angle") - 90) * Double.pi / 180
    let span = max(1.0, (Double(width * width + height * height)).squareRoot()
      * effect.number("scale") / 100.0)
    let cx = Double(width) / 2 + effect.number("offset_x")
    let cy = Double(height) / 2 + effect.number("offset_y")
    let c1 = effect.rgba("color1").map { Float($0) }
    let c2 = effect.rgba("color2").map { Float($0) }
    let reverse = effect.bool("reverse")
    let cosA = Float(cos(angle)), sinA = Float(sin(angle))
    let fcx = Float(cx), fcy = Float(cy), fspan = Float(span)
    var buffer = PixelBuffer(width: max(1, width), height: max(1, height))
    buffer.withMutableWords { words in
      for y in 0..<height {
        for x in 0..<width {
          var t = ((Float(x) - fcx) * cosA + (Float(y) - fcy) * sinA) / fspan + Float(0.5)
          t = max(0, min(1, t))
          if reverse { t = 1 - t }
          let sourceAlpha = alpha[x, y] / Float(255.0)
          let a = UInt32(max(0, min(255, (c1[3] * (1 - t) + c2[3] * t) * sourceAlpha)))
          let scale = Float(a) / Float(255.0)
          let r = UInt32((c1[0] * (1 - t) + c2[0] * t) * scale)
          let g = UInt32((c1[1] * (1 - t) + c2[1] * t) * scale)
          let b = UInt32((c1[2] * (1 - t) + c2[2] * t) * scale)
          words[y * width + x] = (a << 24) | (r << 16) | (g << 8) | b
        }
      }
    }
    return buffer
  }

  // MARK: The stack

  /// `appearance.render`: the planes for `effects` over `alpha`, in stack
  /// order. Offsets are relative to the plane's top-left. Kinds the renderer
  /// does not draw (`LayerEffect.renderableKinds`) contribute nothing.
  static func render(alpha: AlphaPlane, effects: [LayerEffect]) -> [EffectPlane] {
    var planes: [EffectPlane] = []
    for effect in effects where effect.enabled {
      let blend = effect.blendMode, opacity = effect.opacity
      switch effect.kind {
      case "drop-shadow":
        let spread = pyRound(effect.number("spread")), blur = pyRound(effect.number("blur"))
        let pad = spread + blur
        var plane = padded(alpha, pad: pad)
        if spread != 0 { plane = morph(plane, amount: spread, grow: true) }
        plane = Self.blur(plane, radius: blur)
        planes.append(
          EffectPlane(
            buffer: colorImage(plane, rgba: effect.rgba("color")),
            offsetX: pyRound(effect.number("offset_x")) - pad,
            offsetY: pyRound(effect.number("offset_y")) - pad,
            under: true, blendMode: blend, opacity: opacity))
      case "outer-glow":
        let spread = pyRound(effect.number("spread")), size = pyRound(effect.number("size"))
        let pad = spread + size
        var plane = padded(alpha, pad: pad)
        if spread != 0 { plane = morph(plane, amount: spread, grow: true) }
        let original = padded(alpha, pad: pad)
        plane = Self.blur(plane, radius: size)
        for index in 0..<plane.values.count {
          plane.values[index] = max(0, min(255, plane.values[index] - original.values[index]))
        }
        planes.append(
          EffectPlane(
            buffer: colorImage(plane, rgba: effect.rgba("color")),
            offsetX: -pad, offsetY: -pad, under: true, blendMode: blend, opacity: opacity))
      case "outline":
        let width = max(1, pyRound(effect.number("width")))
        let position = effect.string("position")
        if position == "inside" {
          let eroded = morph(alpha, amount: width, grow: false)
          var plane = alpha
          for index in 0..<plane.values.count {
            plane.values[index] = max(0, min(255, alpha.values[index] - eroded.values[index]))
          }
          planes.append(
            EffectPlane(
              buffer: colorImage(plane, rgba: effect.rgba("color")),
              offsetX: 0, offsetY: 0, under: false, blendMode: blend, opacity: opacity))
        } else {
          let outside = position == "outside" ? width : max(1, width / 2)
          let source = padded(alpha, pad: outside)
          let grown = morph(source, amount: outside, grow: true)
          var plane = source
          for index in 0..<plane.values.count {
            plane.values[index] = max(0, min(255, grown.values[index] - source.values[index]))
          }
          if position == "center" {
            let eroded = morph(alpha, amount: width - outside, grow: false)
            for y in 0..<alpha.height {
              for x in 0..<alpha.width {
                let inside = max(0, min(255, alpha[x, y] - eroded[x, y]))
                plane[x + outside, y + outside] += inside
              }
            }
          }
          planes.append(
            EffectPlane(
              buffer: colorImage(plane, rgba: effect.rgba("color")),
              offsetX: -outside, offsetY: -outside, under: position == "outside",
              blendMode: blend, opacity: opacity))
        }
      case "inner-shadow":
        var shifted = shift(
          alpha, dx: -pyRound(effect.number("offset_x")), dy: -pyRound(effect.number("offset_y")))
        shifted = Self.blur(shifted, radius: pyRound(effect.number("blur")))
        var plane = alpha
        for index in 0..<plane.values.count {
          plane.values[index] =
            alpha.values[index] * (Float(1) - shifted.values[index] / Float(255.0))
        }
        let spread = effect.number("spread")
        if spread != 0 {
          let eroded = morph(alpha, amount: pyRound(spread), grow: false)
          for index in 0..<plane.values.count {
            plane.values[index] = max(
              plane.values[index], alpha.values[index] - eroded.values[index])
          }
        }
        planes.append(
          EffectPlane(
            buffer: colorImage(plane, rgba: effect.rgba("color")),
            offsetX: 0, offsetY: 0, under: false, blendMode: blend, opacity: opacity))
      case "inner-glow":
        let size = pyRound(effect.number("size"))
        let choke = pyRound(effect.number("choke"))
        var plane: AlphaPlane
        if effect.string("source") == "center" {
          plane = Self.blur(morph(alpha, amount: choke, grow: false), radius: size)
        } else {
          let eroded = morph(alpha, amount: max(1, size + choke), grow: false)
          var edge = alpha
          for index in 0..<edge.values.count {
            edge.values[index] = max(0, min(255, alpha.values[index] - eroded.values[index]))
          }
          plane = Self.blur(edge, radius: max(1, size / 2))
          for index in 0..<plane.values.count {
            plane.values[index] *= alpha.values[index] / Float(255.0)
          }
        }
        planes.append(
          EffectPlane(
            buffer: colorImage(plane, rgba: effect.rgba("color")),
            offsetX: 0, offsetY: 0, under: false, blendMode: blend, opacity: opacity))
      case "color-overlay":
        planes.append(
          EffectPlane(
            buffer: colorImage(alpha, rgba: effect.rgba("color")),
            offsetX: 0, offsetY: 0, under: false, blendMode: blend, opacity: opacity))
      case "gradient-overlay":
        planes.append(
          EffectPlane(
            buffer: gradientImage(alpha, effect: effect),
            offsetX: 0, offsetY: 0, under: false, blendMode: blend, opacity: opacity))
      case "bevel-emboss":
        var height = Self.blur(alpha, radius: pyRound(effect.number("soften")))
        for index in 0..<height.values.count { height.values[index] /= Float(255.0) }
        let (gy, gx) = gradient(height)
        let azimuth = effect.number("angle") * Double.pi / 180
        let altitude = effect.number("altitude") * Double.pi / 180
        let cosAz = Float(cos(azimuth)), sinAz = Float(sin(azimuth))
        let depthScale = Float(cos(altitude) * effect.number("depth") / 100.0)
        let ambient = Float(sin(altitude) * 0.05)
        var highlight = AlphaPlane(width: alpha.width, height: alpha.height)
        var shadow = AlphaPlane(width: alpha.width, height: alpha.height)
        for index in 0..<alpha.values.count {
          var light = -gx.values[index] * cosAz - gy.values[index] * sinAz
          light *= depthScale
          light += ambient
          let edge = alpha.values[index] / Float(255.0)
          highlight.values[index] = max(0, min(1, light)) * Float(255) * edge
          shadow.values[index] = max(0, min(1, -light)) * Float(255) * edge
        }
        planes.append(
          EffectPlane(
            buffer: colorImage(highlight, rgba: effect.rgba("highlight_color")),
            offsetX: 0, offsetY: 0, under: false, blendMode: "screen", opacity: opacity))
        planes.append(
          EffectPlane(
            buffer: colorImage(shadow, rgba: effect.rgba("shadow_color")),
            offsetX: 0, offsetY: 0, under: false, blendMode: "multiply", opacity: opacity))
      default:
        // gaussian-blur and feather replace the fill on the desktop; see
        // `LayerEffect.renderableKinds`.
        continue
      }
    }
    return planes
  }

  /// `photoslop.layer.BLEND_MODES` as Core Graphics knows them.
  static func blendMode(named name: String) -> CGBlendMode {
    switch name {
    case "multiply": return .multiply
    case "screen": return .screen
    case "overlay": return .overlay
    case "darken": return .darken
    case "lighten": return .lighten
    case "color-dodge": return .colorDodge
    case "color-burn": return .colorBurn
    case "hard-light": return .hardLight
    case "soft-light": return .softLight
    case "difference": return .difference
    case "exclusion": return .exclusion
    case "addition": return .plusLighter
    default: return .normal
    }
  }

  /// Draw one layer's effect planes — those under the fill or those over it
  /// — into the current UIKit context, at the layer's place on the canvas.
  ///
  /// `EditorStore.render` calls this twice around the fill, which is the
  /// desktop compositor's `_draw_effects(under=True)` / fill /
  /// `_draw_effects(under=False)` sequence. The planes are rendered here and
  /// released when the call returns.
  static func draw(
    planes: [EffectPlane], under: Bool, origin: CGPoint, layerOpacity: Double
  ) {
    for plane in planes where plane.under == under {
      autoreleasepool {
        guard let image = plane.buffer.makeImage() else { return }
        image.draw(
          at: CGPoint(
            x: origin.x + CGFloat(plane.offsetX), y: origin.y + CGFloat(plane.offsetY)),
          blendMode: blendMode(named: plane.blendMode),
          alpha: CGFloat(layerOpacity * plane.opacity))
      }
    }
  }

  /// The planes for a layer, or an empty list when it has no enabled,
  /// renderable effect or nothing opaque to cast them from.
  static func planes(for layer: RasterLayer) -> (planes: [EffectPlane], origin: CGPoint) {
    let active = layer.effects.filter {
      $0.enabled && LayerEffect.renderableKinds.contains($0.kind)
    }
    guard !active.isEmpty, let source = sourcePlane(of: layer.image, effects: active) else {
      return ([], .zero)
    }
    let planes = render(alpha: source.plane, effects: active)
    return (
      planes,
      CGPoint(
        x: layer.origin.x + CGFloat(source.originX), y: layer.origin.y + CGFloat(source.originY))
    )
  }
}

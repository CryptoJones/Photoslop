// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import Foundation

/// Cascadic Multigrid Poisson solver with Successive Over-Relaxation (SOR) for
/// gradient-domain image editing, seamless cloning, and spot healing (Issue #415).
///
/// Solves Δf = div v over masked domain Ω with Dirichlet boundary conditions
/// matching surrounding pixels:
/// - Inpainting / Spot Healing: solves Laplace Δf = 0 (membrane interpolation).
/// - Seamless Cloning / Healing Brush: guidance v = ∇g where g is source texture
///   (solved via harmonic offset field u = f - g with boundary condition
///   u = f_dest - g_src).
/// - Mixed Gradients: guidance v = argmax_mag(∇g, ∇f_dest).
///
/// Cascadic Multigrid:
/// 1. Builds a 2-3 level half-resolution pyramid of the patch.
/// 2. Solves coarsest level with Red-Black SOR (omega ≈ 1.7).
/// 3. Upsamples (bilinear) to warm-start finer levels.
/// 4. Performs smoothing iterations at finest level.
/// Converges in milliseconds per stroke or selection.
///
/// Memory Frugality (DD-001):
/// Operates strictly on the bounding box of the mask plus padding (2-4px).
/// Never allocates canvas-wide floating point matrices.
enum MultigridPoisson {

  struct Plane {
    let width: Int
    let height: Int
    var data: [Float]

    init(width: Int, height: Int, initialValue: Float = 0) {
      self.width = width
      self.height = height
      self.data = [Float](repeating: initialValue, count: width * height)
    }

    init(width: Int, height: Int, data: [Float]) {
      precondition(data.count == width * height)
      self.width = width
      self.height = height
      self.data = data
    }

    subscript(x: Int, y: Int) -> Float {
      get { data[y * width + x] }
      set { data[y * width + x] = newValue }
    }

    func downsample2x() -> Plane {
      let nw = (width + 1) / 2
      let nh = (height + 1) / 2
      var out = [Float](repeating: 0, count: nw * nh)
      var counts = [Float](repeating: 0, count: nw * nh)

      for y in 0..<height {
        let ny = y / 2
        let rIn = y * width
        let rOut = ny * nw
        for x in 0..<width {
          let nx = x / 2
          out[rOut + nx] += data[rIn + x]
          counts[rOut + nx] += 1
        }
      }

      for i in 0..<out.count {
        if counts[i] > 0 {
          out[i] /= counts[i]
        }
      }
      return Plane(width: nw, height: nh, data: out)
    }

    func upsampleBilinear(to targetWidth: Int, targetHeight: Int) -> Plane {
      var out = [Float](repeating: 0, count: targetWidth * targetHeight)
      let scaleX = Float(width - 1) / Float(max(1, targetWidth - 1))
      let scaleY = Float(height - 1) / Float(max(1, targetHeight - 1))

      for y in 0..<targetHeight {
        let fy = Float(y) * scaleY
        let y0 = Int(fy)
        let y1 = min(y0 + 1, height - 1)
        let wy = fy - Float(y0)
        let r0 = y0 * width
        let r1 = y1 * width
        let rOut = y * targetWidth

        for x in 0..<targetWidth {
          let fx = Float(x) * scaleX
          let x0 = Int(fx)
          let x1 = min(x0 + 1, width - 1)
          let wx = fx - Float(x0)

          let top = data[r0 + x0] * (1.0 - wx) + data[r0 + x1] * wx
          let bottom = data[r1 + x0] * (1.0 - wx) + data[r1 + x1] * wx
          out[rOut + x] = top * (1.0 - wy) + bottom * wy
        }
      }
      return Plane(width: targetWidth, height: targetHeight, data: out)
    }
  }

  // MARK: - Core Multigrid Solver

  /// Solve Poisson equation on a single channel plane using cascadic multigrid.
  static func solveChannel(
    dest: Plane,
    mask: [Bool],
    src: Plane? = nil,
    mixed: Bool = false,
    omega: Float = 1.7,
    neumann: (top: Bool, bottom: Bool, left: Bool, right: Bool) = (false, false, false, false)
  ) -> Plane {
    let w = dest.width
    let h = dest.height
    guard w >= 3, h >= 3 else { return dest }

    let levels = min(w, h) >= 32 ? 3 : (min(w, h) >= 16 ? 2 : 1)

    var masks: [[Bool]] = [mask]
    var maskSizes: [(width: Int, height: Int)] = [(w, h)]
    var dests: [Plane] = [dest]
    var srcs: [Plane]? = src != nil ? [src!] : nil

    // Level 0 mask outer border is always false
    for x in 0..<w {
      masks[0][x] = false
      masks[0][(h - 1) * w + x] = false
    }
    for y in 0..<h {
      masks[0][y * w] = false
      masks[0][y * w + (w - 1)] = false
    }

    // Build pyramid
    for lvl in 0..<(levels - 1) {
      let prevMask = masks[lvl]
      let (curW, curH) = maskSizes[lvl]
      let nw = (curW + 1) / 2
      let nh = (curH + 1) / 2

      var coarseMask = [Bool](repeating: false, count: nw * nh)
      for y in 0..<curH {
        let ny = y / 2
        let rIn = y * curW
        let rOut = ny * nw
        for x in 0..<curW {
          if prevMask[rIn + x] {
            coarseMask[rOut + (x / 2)] = true
          }
        }
      }
      for x in 0..<nw {
        coarseMask[x] = false
        coarseMask[(nh - 1) * nw + x] = false
      }
      for y in 0..<nh {
        coarseMask[y * nw] = false
        coarseMask[y * nw + (nw - 1)] = false
      }
      masks.append(coarseMask)
      maskSizes.append((nw, nh))

      dests.append(dests[lvl].downsample2x())
      if srcs != nil {
        srcs!.append(srcs![lvl].downsample2x())
      }
    }

    func applyNeumann(plane: inout Plane) {
      let pw = plane.width
      let ph = plane.height
      if neumann.top && ph > 1 {
        for x in 0..<pw { plane.data[x] = plane.data[pw + x] }
      }
      if neumann.bottom && ph > 1 {
        let rLast = (ph - 1) * pw
        let rPrev = (ph - 2) * pw
        for x in 0..<pw { plane.data[rLast + x] = plane.data[rPrev + x] }
      }
      if neumann.left && pw > 1 {
        for y in 0..<ph { plane.data[y * pw] = plane.data[y * pw + 1] }
      }
      if neumann.right && pw > 1 {
        for y in 0..<ph { plane.data[y * pw + pw - 1] = plane.data[y * pw + pw - 2] }
      }
    }

    let coarsest = levels - 1
    let (cw, ch) = maskSizes[coarsest]
    let mC = masks[coarsest]
    let dC = dests[coarsest]
    let sC = srcs?[coarsest]

    var val = Plane(width: cw, height: ch)

    if src == nil {
      val = dC
      var sum: Float = 0
      var count: Float = 0
      for y in 0..<ch {
        let r = y * cw
        for x in 0..<cw {
          let idx = r + x
          if !mC[idx] {
            if (y == 0 && neumann.top) || (y == ch - 1 && neumann.bottom)
              || (x == 0 && neumann.left) || (x == cw - 1 && neumann.right)
            {
              continue
            }
            sum += dC.data[idx]
            count += 1
          }
        }
      }
      let fillVal = count > 0 ? (sum / count) : 128.0
      for i in 0..<val.data.count where mC[i] {
        val.data[i] = fillVal
      }
    } else if !mixed {
      // u = dest - src on boundary, 0 inside
      guard let sC else { return dest }
      for i in 0..<val.data.count {
        val.data[i] = mC[i] ? 0.0 : (dC.data[i] - sC.data[i])
      }
    } else {
      val = dC
    }

    applyNeumann(plane: &val)

    let itersPerLevel = levels == 3 ? [20, 30, 45] : (levels == 2 ? [25, 40] : [50])

    for lvl in stride(from: levels - 1, through: 0, by: -1) {
      let (curW, curH) = maskSizes[lvl]
      let m = masks[lvl]
      let d = dests[lvl]
      let s = srcs?[lvl]

      if lvl < coarsest {
        val = val.upsampleBilinear(to: curW, targetHeight: curH)
        for i in 0..<val.data.count where !m[i] {
          if src == nil || mixed {
            val.data[i] = d.data[i]
          } else if let s {
            val.data[i] = d.data[i] - s.data[i]
          }
        }
        applyNeumann(plane: &val)
      }

      var rhs: Plane? = nil
      if mixed, let s {
        rhs = computeMixedDivergence(dest: d, src: s)
      }

      let itCount = itersPerLevel[levels - 1 - lvl]

      for _ in 0..<itCount {
        applyNeumann(plane: &val)

        // Red pass ((y + x) % 2 == 0)
        for y in 1..<(curH - 1) {
          let r = y * curW
          let rUp = (y - 1) * curW
          let rDown = (y + 1) * curW
          for x in 1..<(curW - 1) {
            let idx = r + x
            if ((y + x) & 1) == 0 && m[idx] {
              let nbrs = val.data[rUp + x] + val.data[rDown + x] + val.data[r + x - 1] + val.data[r + x + 1]
              let b = rhs?.data[idx] ?? 0.0
              let target = 0.25 * (nbrs + b)
              val.data[idx] = (1.0 - omega) * val.data[idx] + omega * target
            }
          }
        }

        applyNeumann(plane: &val)

        // Black pass ((y + x) % 2 == 1)
        for y in 1..<(curH - 1) {
          let r = y * curW
          let rUp = (y - 1) * curW
          let rDown = (y + 1) * curW
          for x in 1..<(curW - 1) {
            let idx = r + x
            if ((y + x) & 1) == 1 && m[idx] {
              let nbrs = val.data[rUp + x] + val.data[rDown + x] + val.data[r + x - 1] + val.data[r + x + 1]
              let b = rhs?.data[idx] ?? 0.0
              let target = 0.25 * (nbrs + b)
              val.data[idx] = (1.0 - omega) * val.data[idx] + omega * target
            }
          }
        }

        applyNeumann(plane: &val)
      }
    }

    var result = Plane(width: w, height: h)
    if let src, !mixed {
      for i in 0..<result.data.count {
        result.data[i] = min(max(src.data[i] + val.data[i], 0.0), 255.0)
      }
    } else {
      for i in 0..<result.data.count {
        result.data[i] = min(max(val.data[i], 0.0), 255.0)
      }
    }
    return result
  }

  private static func computeMixedDivergence(dest: Plane, src: Plane) -> Plane {
    let w = dest.width
    let h = dest.height
    var b = [Float](repeating: 0, count: w * h)
    let shifts = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    for y in 1..<(h - 1) {
      let r = y * w
      for x in 1..<(w - 1) {
        var sum: Float = 0
        let pSrc = src.data[r + x]
        let pDst = dest.data[r + x]
        for (dy, dx) in shifts {
          let qIdx = (y + dy) * w + (x + dx)
          let dg = pSrc - src.data[qIdx]
          let df = pDst - dest.data[qIdx]
          sum += abs(dg) >= abs(df) ? dg : df
        }
        b[r + x] = sum
      }
    }
    return Plane(width: w, height: h, data: b)
  }

  // MARK: - Inpainting / Spot Healing

  /// Inpaint the masked pixels in `buffer` using Poisson / Laplace multigrid solver.
  /// Operates strictly within the bounding box of `mask` plus padding (DD-001).
  @discardableResult
  static func inpaint(
    buffer: inout PixelBuffer,
    mask: [Bool],
    bounds: PixelRect? = nil
  ) -> PixelRect? {
    let w = buffer.width
    let h = buffer.height
    guard mask.count == w * h else { return nil }

    // Measure bounding box if not provided
    var minX = Int.max, maxX = -1, minY = Int.max, maxY = -1, count = 0
    if let b = bounds {
      minX = b.x
      minY = b.y
      maxX = b.x + b.width - 1
      maxY = b.y + b.height - 1
      count = b.width * b.height
    } else {
      for y in 0..<h {
        let r = y * w
        for x in 0..<w where mask[r + x] {
          count += 1
          if x < minX { minX = x }
          if x > maxX { maxX = x }
          if y < minY { minY = y }
          if y > maxY { maxY = y }
        }
      }
    }
    guard count > 0, minX <= maxX, minY <= maxY else { return nil }

    let pad = 4
    let x0 = max(0, minX - pad)
    let x1 = min(w, maxX + 1 + pad)
    let y0 = max(0, minY - pad)
    let y1 = min(h, maxY + 1 + pad)
    let cropW = x1 - x0
    let cropH = y1 - y0
    guard cropW >= 3, cropH >= 3 else { return nil }

    let topPad = max(0, 1 - (minY - y0))
    let bottomPad = max(0, 1 - (y1 - 1 - maxY))
    let leftPad = max(0, 1 - (minX - x0))
    let rightPad = max(0, 1 - (x1 - 1 - maxX))

    let padW = cropW + leftPad + rightPad
    let padH = cropH + topPad + bottomPad

    var cropMask = [Bool](repeating: false, count: padW * padH)
    var planeA = [Float](repeating: 0, count: padW * padH)
    var planeR = [Float](repeating: 0, count: padW * padH)
    var planeG = [Float](repeating: 0, count: padW * padH)
    var planeB = [Float](repeating: 0, count: padW * padH)

    buffer.withWords { words in
      for cy in 0..<padH {
        let sy = min(max(cy - topPad + y0, 0), h - 1)
        let rBuf = sy * w
        let rPad = cy * padW
        for cx in 0..<padW {
          let sx = min(max(cx - leftPad + x0, 0), w - 1)
          let pIdx = rPad + cx
          let word = words[rBuf + sx]

          planeA[pIdx] = Float((word >> 24) & 0xFF)
          planeR[pIdx] = Float((word >> 16) & 0xFF)
          planeG[pIdx] = Float((word >> 8) & 0xFF)
          planeB[pIdx] = Float(word & 0xFF)

          if cy >= topPad && cy < topPad + cropH && cx >= leftPad && cx < leftPad + cropW {
            let my = cy - topPad + y0
            let mx = cx - leftPad + x0
            cropMask[pIdx] = mask[my * w + mx]
          }
        }
      }
    }

    let neumann = (topPad > 0, bottomPad > 0, leftPad > 0, rightPad > 0)

    let solvedA = solveChannel(dest: Plane(width: padW, height: padH, data: planeA), mask: cropMask, neumann: neumann)
    let solvedR = solveChannel(dest: Plane(width: padW, height: padH, data: planeR), mask: cropMask, neumann: neumann)
    let solvedG = solveChannel(dest: Plane(width: padW, height: padH, data: planeG), mask: cropMask, neumann: neumann)
    let solvedB = solveChannel(dest: Plane(width: padW, height: padH, data: planeB), mask: cropMask, neumann: neumann)

    buffer.withMutableWords { words in
      for cy in 0..<cropH {
        let pIdx = (cy + topPad) * padW + leftPad
        let bufIdx = (cy + y0) * w + x0
        for cx in 0..<cropW {
          if cropMask[pIdx + cx] {
            let a = UInt32(min(max(solvedA.data[pIdx + cx] + 0.5, 0.0), 255.0))
            var r = UInt32(min(max(solvedR.data[pIdx + cx] + 0.5, 0.0), 255.0))
            var g = UInt32(min(max(solvedG.data[pIdx + cx] + 0.5, 0.0), 255.0))
            var b = UInt32(min(max(solvedB.data[pIdx + cx] + 0.5, 0.0), 255.0))

            // Premultiplied clamp
            r = min(r, a)
            g = min(g, a)
            b = min(b, a)

            words[bufIdx + cx] = (a << 24) | (r << 16) | (g << 8) | b
          }
        }
      }
    }

    return PixelRect(x: x0, y: y0, width: cropW, height: cropH)
  }

  // MARK: - Seamless Cloning / Healing Brush

  /// Transplant source texture sampled at offset (dx, dy) into the masked pixels in `buffer`.
  @discardableResult
  static func seamlessClone(
    buffer: inout PixelBuffer,
    mask: [Bool],
    bounds: PixelRect? = nil,
    dx: Int,
    dy: Int,
    mixed: Bool = false
  ) -> PixelRect? {
    let w = buffer.width
    let h = buffer.height
    guard mask.count == w * h else { return nil }

    var minX = Int.max, maxX = -1, minY = Int.max, maxY = -1, count = 0
    if let b = bounds {
      minX = b.x
      minY = b.y
      maxX = b.x + b.width - 1
      maxY = b.y + b.height - 1
      count = b.width * b.height
    } else {
      for y in 0..<h {
        let r = y * w
        for x in 0..<w where mask[r + x] {
          count += 1
          if x < minX { minX = x }
          if x > maxX { maxX = x }
          if y < minY { minY = y }
          if y > maxY { maxY = y }
        }
      }
    }
    guard count > 0, minX <= maxX, minY <= maxY else { return nil }

    let pad = 4
    let x0 = max(0, minX - pad)
    let x1 = min(w, maxX + 1 + pad)
    let y0 = max(0, minY - pad)
    let y1 = min(h, maxY + 1 + pad)
    let cropW = x1 - x0
    let cropH = y1 - y0

    let sx0 = x0 + dx
    let sy0 = y0 + dy
    let sx1 = x1 + dx
    let sy1 = y1 + dy
    guard sx0 >= 0, sy0 >= 0, sx1 <= w, sy1 <= h else { return nil }

    let topPad = max(0, 1 - (minY - y0))
    let bottomPad = max(0, 1 - (y1 - 1 - maxY))
    let leftPad = max(0, 1 - (minX - x0))
    let rightPad = max(0, 1 - (x1 - 1 - maxX))

    let padW = cropW + leftPad + rightPad
    let padH = cropH + topPad + bottomPad

    var cropMask = [Bool](repeating: false, count: padW * padH)
    var dR = [Float](repeating: 0, count: padW * padH)
    var dG = [Float](repeating: 0, count: padW * padH)
    var dB = [Float](repeating: 0, count: padW * padH)
    var sR = [Float](repeating: 0, count: padW * padH)
    var sG = [Float](repeating: 0, count: padW * padH)
    var sB = [Float](repeating: 0, count: padW * padH)

    buffer.withWords { words in
      for cy in 0..<padH {
        let dyCoord = min(max(cy - topPad + y0, 0), h - 1)
        let syCoord = min(max(cy - topPad + sy0, 0), h - 1)
        let rDst = dyCoord * w
        let rSrc = syCoord * w
        let rPad = cy * padW

        for cx in 0..<padW {
          let dxCoord = min(max(cx - leftPad + x0, 0), w - 1)
          let sxCoord = min(max(cx - leftPad + sx0, 0), w - 1)
          let pIdx = rPad + cx

          let dWord = words[rDst + dxCoord]
          let sWord = words[rSrc + sxCoord]

          dR[pIdx] = Float((dWord >> 16) & 0xFF)
          dG[pIdx] = Float((dWord >> 8) & 0xFF)
          dB[pIdx] = Float(dWord & 0xFF)

          sR[pIdx] = Float((sWord >> 16) & 0xFF)
          sG[pIdx] = Float((sWord >> 8) & 0xFF)
          sB[pIdx] = Float(sWord & 0xFF)

          if cy >= topPad && cy < topPad + cropH && cx >= leftPad && cx < leftPad + cropW {
            let my = cy - topPad + y0
            let mx = cx - leftPad + x0
            cropMask[pIdx] = mask[my * w + mx]
          }
        }
      }
    }

    let neumann = (topPad > 0, bottomPad > 0, leftPad > 0, rightPad > 0)

    let solvedR = solveChannel(
      dest: Plane(width: padW, height: padH, data: dR),
      mask: cropMask,
      src: Plane(width: padW, height: padH, data: sR),
      mixed: mixed,
      neumann: neumann
    )
    let solvedG = solveChannel(
      dest: Plane(width: padW, height: padH, data: dG),
      mask: cropMask,
      src: Plane(width: padW, height: padH, data: sG),
      mixed: mixed,
      neumann: neumann
    )
    let solvedB = solveChannel(
      dest: Plane(width: padW, height: padH, data: dB),
      mask: cropMask,
      src: Plane(width: padW, height: padH, data: sB),
      mixed: mixed,
      neumann: neumann
    )

    buffer.withMutableWords { words in
      for cy in 0..<cropH {
        let pIdx = (cy + topPad) * padW + leftPad
        let bufIdx = (cy + y0) * w + x0
        for cx in 0..<cropW {
          if cropMask[pIdx + cx] {
            let dWord = words[bufIdx + cx]
            let a = (dWord >> 24) & 0xFF

            var r = UInt32(min(max(solvedR.data[pIdx + cx] + 0.5, 0.0), 255.0))
            var g = UInt32(min(max(solvedG.data[pIdx + cx] + 0.5, 0.0), 255.0))
            var b = UInt32(min(max(solvedB.data[pIdx + cx] + 0.5, 0.0), 255.0))

            r = min(r, a)
            g = min(g, a)
            b = min(b, a)

            words[bufIdx + cx] = (a << 24) | (r << 16) | (g << 8) | b
          }
        }
      }
    }

    return PixelRect(x: x0, y: y0, width: cropW, height: cropH)
  }

  // MARK: - Point / Brush Dab Conveniences

  /// Spot heal a circular dab at `center` with `radius`.
  @discardableResult
  static func spotHeal(
    buffer: inout PixelBuffer,
    center: CGPoint,
    radius: CGFloat
  ) -> PixelRect? {
    let w = buffer.width
    let h = buffer.height
    let cx = Int(center.x.rounded())
    let cy = Int(center.y.rounded())
    let r = max(1, Int(radius.rounded()))

    let x0 = max(0, cx - r)
    let x1 = min(w, cx + r + 1)
    let y0 = max(0, cy - r)
    let y1 = min(h, cy + r + 1)
    guard x0 < x1, y0 < y1 else { return nil }

    var mask = [Bool](repeating: false, count: w * h)
    let rSq = r * r
    for y in y0..<y1 {
      let dy = y - cy
      let rRow = y * w
      for x in x0..<x1 {
        let dx = x - cx
        if dx * dx + dy * dy <= rSq {
          mask[rRow + x] = true
        }
      }
    }

    let bounds = PixelRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)
    return inpaint(buffer: &buffer, mask: mask, bounds: bounds)
  }

  /// Heal brush: seamless clone from `sourceCenter` to `center` with `radius`.
  @discardableResult
  static func heal(
    buffer: inout PixelBuffer,
    center: CGPoint,
    from sourceCenter: CGPoint,
    radius: CGFloat,
    mixed: Bool = false
  ) -> PixelRect? {
    let w = buffer.width
    let h = buffer.height
    let cx = Int(center.x.rounded())
    let cy = Int(center.y.rounded())
    let sx = Int(sourceCenter.x.rounded())
    let sy = Int(sourceCenter.y.rounded())
    let r = max(1, Int(radius.rounded()))

    let x0 = max(0, cx - r)
    let x1 = min(w, cx + r + 1)
    let y0 = max(0, cy - r)
    let y1 = min(h, cy + r + 1)
    guard x0 < x1, y0 < y1 else { return nil }

    var mask = [Bool](repeating: false, count: w * h)
    let rSq = r * r
    for y in y0..<y1 {
      let dy = y - cy
      let rRow = y * w
      for x in x0..<x1 {
        let dx = x - cx
        if dx * dx + dy * dy <= rSq {
          mask[rRow + x] = true
        }
      }
    }

    let dx = sx - cx
    let dy = sy - cy
    let bounds = PixelRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)
    return seamlessClone(buffer: &buffer, mask: mask, bounds: bounds, dx: dx, dy: dy, mixed: mixed)
  }
}

// MARK: - EditorStore Extension

extension EditorStore {
  /// Spot heal the current selection using the multigrid Poisson solver.
  @discardableResult
  func spotHealSelection() -> Bool {
    guard let layer = activeLayer, let selection, !selection.isEmpty else { return false }
    return applyPixelOperation(to: layer.id, actionName: "Spot Heal") { buffer in
      MultigridPoisson.inpaint(buffer: &buffer, mask: selection.bits, bounds: selection.bounds) != nil
    }
  }

  /// Seamless clone texture into selection using source offset (dx, dy).
  @discardableResult
  func healSelection(dx: Int, dy: Int) -> Bool {
    guard let layer = activeLayer, let selection, !selection.isEmpty else { return false }
    return applyPixelOperation(to: layer.id, actionName: "Healing Brush") { buffer in
      MultigridPoisson.seamlessClone(
        buffer: &buffer, mask: selection.bits, bounds: selection.bounds, dx: dx, dy: dy
      ) != nil
    }
  }

  /// Spot heal a circular dab at `center` with `radius`.
  @discardableResult
  func spotHeal(at center: CGPoint, radius: CGFloat) -> Bool {
    guard let layer = activeLayer else { return false }
    return applyPixelOperation(to: layer.id, actionName: "Spot Heal") { buffer in
      MultigridPoisson.spotHeal(buffer: &buffer, center: center, radius: radius) != nil
    }
  }

  /// Healing brush dab at `center` sampled from `sourceCenter` with `radius`.
  @discardableResult
  func heal(at center: CGPoint, from sourceCenter: CGPoint, radius: CGFloat) -> Bool {
    guard let layer = activeLayer else { return false }
    return applyPixelOperation(to: layer.id, actionName: "Healing Brush") { buffer in
      MultigridPoisson.heal(
        buffer: &buffer, center: center, from: sourceCenter, radius: radius
      ) != nil
    }
  }
}

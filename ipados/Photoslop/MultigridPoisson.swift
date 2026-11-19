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
/// Cascadic multigrid (mirrors photoslop/npimage.py):
/// 1. Builds half-resolution levels by injection until the coarsest grid's
///    shorter side is below 8 px (dynamic depth — large holes get more levels).
/// 2. Solves the coarsest level with Red-Black SOR (omega ≈ 1.7).
/// 3. Prolongs (bilinear, injection-aligned) to warm-start finer levels.
/// 4. Smooths each level until its max residual drops below a tolerance or a
///    per-level sweep cap is hit. The residual stop is what makes large masks
///    converge: a fixed sweep budget cannot carry boundary values to the centre
///    of a big hole, but the coarse solve carries the low-frequency part.
///
/// Memory (DD-001): work is proportional to the patch it is given — callers pass
/// the mask's bounding box plus padding, not the canvas. A selection that covers
/// (nearly) the whole canvas therefore does allocate (nearly) canvas-sized
/// planes: on a 4096×4096 image with a one-pixel unselected border the clone path
/// holds six full-canvas input planes (~384 MiB of Float) before solver scratch.
/// The bound is the crop, not a constant; dab conveniences keep their masks
/// crop-local so a stroke scales with the dab, not the canvas.
enum MultigridPoisson {

  // Residual stop: a quarter of a quantisation step (result is rounded to u8).
  private static let residualTol: Float = 0.02
  private static let maxSweeps = 80
  private static let coarsestSweeps = 400

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

    /// Injection restriction: coarse cell (i, j) is fine pixel (2i, 2j).
    ///
    /// Averaging 2×2 blocks would place each coarse value at a block centre
    /// (half a pixel off the coarse grid point) and mix erased hole pixels into
    /// coarse boundary data. Injection keeps coarse boundary cells exact copies
    /// of real known pixels and keeps the grids aligned, so bilinear
    /// prolongation reproduces linear fields exactly at every level.
    ///
    /// With an even fine size n, plain injection's last coarse cell lands on
    /// fine n-2 (possibly inside the hole). The grid is extended by one cell at
    /// fine position n carrying the linear extrapolation from the nearest known
    /// row/column: spacing stays uniform and linear ramps restrict exactly.
    /// `linear == false` replicates unconditionally — texture planes have no
    /// linear trend, and extrapolating a checker boundary overshoots badly.
    func restrict2x(known: [Bool]? = nil, linear: Bool = true) -> Plane {
      var src = data
      var sw = width
      var sh = height
      var kn = known

      if sh % 2 == 0 {
        var extra = [Float](repeating: 0, count: sw)
        for x in 0..<sw {
          let last = src[(sh - 1) * sw + x]
          var val = last
          if linear {
            var k = -1
            if let kn {
              for y in stride(from: sh - 2, through: 0, by: -1) where kn[y * sw + x] {
                k = y
                break
              }
            } else {
              k = sh - 2
            }
            if k >= 0 {
              let prev = src[k * sw + x]
              val = last + (last - prev) / Float((sh - 1) - k)
            }
          }
          extra[x] = val
        }
        src.append(contentsOf: extra)
        if kn != nil { kn!.append(contentsOf: [Bool](repeating: true, count: sw)) }
        sh += 1
      }

      if sw % 2 == 0 {
        var out = [Float](repeating: 0, count: sh * (sw + 1))
        for y in 0..<sh {
          let last = src[y * sw + (sw - 1)]
          var val = last
          if linear {
            var k = -1
            if let kn {
              for x in stride(from: sw - 2, through: 0, by: -1) where kn[y * sw + x] {
                k = x
                break
              }
            } else {
              k = sw - 2
            }
            if k >= 0 {
              let prev = src[y * sw + k]
              val = last + (last - prev) / Float((sw - 1) - k)
            }
          }
          for x in 0..<sw { out[y * (sw + 1) + x] = src[y * sw + x] }
          out[y * (sw + 1) + sw] = val
        }
        src = out
        sw += 1
      }

      let nw = (sw + 1) / 2
      let nh = (sh + 1) / 2
      var out = [Float](repeating: 0, count: nw * nh)
      for y in 0..<nh {
        for x in 0..<nw {
          out[y * nw + x] = src[(2 * y) * sw + (2 * x)]
        }
      }
      return Plane(width: nw, height: nh, data: out)
    }

    /// Injection-aligned bilinear prolongation: coarse cell i sits at fine 2i,
    /// so the inverse map is u = x/2 (clamped), NOT an endpoint-aligned linspace.
    /// This keeps linear fields exact across the prolongation.
    func prolong(to targetWidth: Int, targetHeight: Int) -> Plane {
      var out = [Float](repeating: 0, count: targetWidth * targetHeight)
      for y in 0..<targetHeight {
        let fy = min(Float(y) * 0.5, Float(height - 1))
        let y0 = Int(fy)
        let y1 = min(y0 + 1, height - 1)
        let wy = fy - Float(y0)
        let r0 = y0 * width
        let r1 = y1 * width
        let rOut = y * targetWidth
        for x in 0..<targetWidth {
          let fx = min(Float(x) * 0.5, Float(width - 1))
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

  private static func clearRing(_ m: inout [Bool], _ w: Int, _ h: Int) {
    for x in 0..<w {
      m[x] = false
      m[(h - 1) * w + x] = false
    }
    for y in 0..<h {
      m[y * w] = false
      m[y * w + (w - 1)] = false
    }
  }

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
    guard mask.contains(true) else { return dest }

    var masks: [[Bool]] = [mask]
    var sizes: [(w: Int, h: Int)] = [(w, h)]
    var dests: [Plane] = [dest]
    var srcs: [Plane]? = src != nil ? [src!] : nil

    clearRing(&masks[0], w, h)

    // Build the pyramid while the grid is big enough that SOR alone would not
    // reach the interior, and while the hole still has an interior next level.
    while min(sizes[sizes.count - 1].w, sizes[sizes.count - 1].h) >= 8 && masks.count < 16 {
      let mFine = masks[masks.count - 1]
      let fw = sizes[sizes.count - 1].w
      let fh = sizes[sizes.count - 1].h
      let injW = (fw + 1) / 2
      let injH = (fh + 1) / 2
      let cw = injW + (fw % 2 == 0 ? 1 : 0)
      let ch = injH + (fh % 2 == 0 ? 1 : 0)

      var coarseMask = [Bool](repeating: false, count: cw * ch)
      for y in 0..<injH {
        for x in 0..<injW {
          coarseMask[y * cw + x] = mFine[(2 * y) * fw + (2 * x)]
        }
      }
      // Appended coarse row/column (even-size extension) stays known (false).
      clearRing(&coarseMask, cw, ch)
      if ch < 3 || cw < 3 { break }
      var hasInterior = false
      for y in 1..<(ch - 1) {
        for x in 1..<(cw - 1) where coarseMask[y * cw + x] {
          hasInterior = true
          break
        }
        if hasInterior { break }
      }
      if !hasInterior { break }

      masks.append(coarseMask)
      sizes.append((cw, ch))
      if srcs == nil {
        let known = mFine.map { !$0 }
        dests.append(dests[dests.count - 1].restrict2x(known: known, linear: true))
      } else {
        dests.append(dests[dests.count - 1].restrict2x(linear: false))
        srcs!.append(srcs![srcs!.count - 1].restrict2x(linear: false))
      }
    }

    func applyNeumann(_ plane: inout Plane) {
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

    let coarsest = masks.count - 1
    let cw = sizes[coarsest].w
    let ch = sizes[coarsest].h
    let mC = masks[coarsest]
    let dC = dests[coarsest]
    let sC = srcs?[coarsest]

    var val: Plane
    if src == nil {
      val = dC
      var sum: Float = 0
      var count: Float = 0
      for y in 0..<ch {
        for x in 0..<cw {
          let idx = y * cw + x
          if mC[idx] { continue }
          if (y == 0 && neumann.top) || (y == ch - 1 && neumann.bottom)
            || (x == 0 && neumann.left) || (x == cw - 1 && neumann.right)
          {
            continue
          }
          sum += dC.data[idx]
          count += 1
        }
      }
      if count > 0 {
        let fill = sum / count
        for i in 0..<val.data.count where mC[i] { val.data[i] = fill }
      } else {
        // No non-Neumann boundary: fall back to the mean of all known pixels.
        var s2: Float = 0
        var c2: Float = 0
        for i in 0..<val.data.count where !mC[i] {
          s2 += dC.data[i]
          c2 += 1
        }
        if c2 > 0 {
          let fill = s2 / c2
          for i in 0..<val.data.count where mC[i] { val.data[i] = fill }
        }
      }
    } else if !mixed {
      guard let sC else { return dest }
      val = Plane(width: cw, height: ch)
      for i in 0..<val.data.count {
        val.data[i] = mC[i] ? 0.0 : (dC.data[i] - sC.data[i])
      }
    } else {
      val = dC
    }

    applyNeumann(&val)

    for lvl in stride(from: coarsest, through: 0, by: -1) {
      let curW = sizes[lvl].w
      let curH = sizes[lvl].h
      let m = masks[lvl]
      let d = dests[lvl]
      let s = srcs?[lvl]

      if lvl < coarsest {
        val = val.prolong(to: curW, targetHeight: curH)
        for i in 0..<val.data.count where !m[i] {
          if src == nil || mixed {
            val.data[i] = d.data[i]
          } else if let s {
            val.data[i] = d.data[i] - s.data[i]
          }
        }
        applyNeumann(&val)
      }

      var rhs: Plane? = nil
      if mixed, let s {
        rhs = computeMixedDivergence(dest: d, src: s)
      }

      var interior = [Bool](repeating: false, count: curW * curH)
      var hasInterior = false
      for y in 1..<(curH - 1) {
        for x in 1..<(curW - 1) {
          let idx = y * curW + x
          if m[idx] {
            interior[idx] = true
            hasInterior = true
          }
        }
      }
      if !hasInterior { continue }

      let itCap = lvl == coarsest ? coarsestSweeps : maxSweeps
      for it in 0..<itCap {
        applyNeumann(&val)

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

        applyNeumann(&val)

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

        applyNeumann(&val)

        // Residual stop: r = b - (4·val - Σ neighbours) on masked interior cells.
        if (it + 1) % 4 == 0 || it + 1 == itCap {
          var rmax: Float = 0
          for y in 1..<(curH - 1) {
            let r = y * curW
            for x in 1..<(curW - 1) {
              let idx = r + x
              if !interior[idx] { continue }
              let nbrs = val.data[r - curW + x] + val.data[r + curW + x] + val.data[idx - 1] + val.data[idx + 1]
              let b = rhs?.data[idx] ?? 0.0
              let res = abs(b - (4.0 * val.data[idx] - nbrs))
              if res > rmax { rmax = res }
            }
          }
          if rmax <= residualTol { break }
        }
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

  /// Inpaint the masked pixels in `buffer` using the Poisson / Laplace multigrid
  /// solver. Operates within the bounding box of `mask` plus padding (DD-001).
  ///
  /// `mask` is canvas-sized by default. When `maskIsLocal` is true, `mask` is
  /// crop-local (size `bounds.width * bounds.height`) so dab callers need not
  /// allocate a canvas-wide mask. Returns nil (no edit) when there is no masked
  /// pixel, no known boundary pixel to solve against, or the crop is too small.
  @discardableResult
  static func inpaint(
    buffer: inout PixelBuffer,
    mask: [Bool],
    bounds: PixelRect? = nil,
    maskIsLocal: Bool = false
  ) -> PixelRect? {
    let w = buffer.width
    let h = buffer.height

    var minX = Int.max, maxX = -1, minY = Int.max, maxY = -1, count = 0
    if let b = bounds {
      minX = b.x
      minY = b.y
      maxX = b.x + b.width - 1
      maxY = b.y + b.height - 1
      count = b.width * b.height
    } else {
      guard mask.count == w * h else { return nil }
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

    let topPad = max(0, 1 - (minY - y0))
    let bottomPad = max(0, 1 - (y1 - 1 - maxY))
    let leftPad = max(0, 1 - (minX - x0))
    let rightPad = max(0, 1 - (x1 - 1 - maxX))
    let padW = cropW + leftPad + rightPad
    let padH = cropH + topPad + bottomPad
    // Check the solve size AFTER the ghost border: a 2×8 crop becomes 4 wide.
    guard padW >= 3, padH >= 3 else { return nil }

    let neumann = (topPad > 0, bottomPad > 0, leftPad > 0, rightPad > 0)

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
            cropMask[pIdx] = maskIsLocal
              ? mask[(my - y0) * cropW + (mx - x0)]
              : mask[my * w + mx]
          }
        }
      }
    }

    // Refuse when no known pixel can anchor the solve (e.g. spot-healing an
    // entire opaque image: every border is reflective, nothing contributes).
    guard hasKnownBoundary(cropMask, padW, padH, neumann) else { return nil }

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

  /// True when at least one known (unmasked) pixel sits off a reflective
  /// (Neumann) edge — i.e. there is real boundary data to solve against.
  private static func hasKnownBoundary(
    _ cropMask: [Bool], _ padW: Int, _ padH: Int,
    _ neumann: (top: Bool, bottom: Bool, left: Bool, right: Bool)
  ) -> Bool {
    for cy in 0..<padH {
      for cx in 0..<padW {
        if cropMask[cy * padW + cx] { continue }
        let onNeumann = (cy == 0 && neumann.top) || (cy == padH - 1 && neumann.bottom)
          || (cx == 0 && neumann.left) || (cx == padW - 1 && neumann.right)
        if !onNeumann { return true }
      }
    }
    return false
  }

  // MARK: - Seamless Cloning / Healing Brush

  /// Transplant source texture sampled at offset (dx, dy) into the masked pixels
  /// in `buffer`. The source footprint of the masked pixels must fit on-canvas;
  /// the solver halo around it is edge-replicated, not refused. `maskIsLocal`
  /// matches `inpaint`.
  @discardableResult
  static func seamlessClone(
    buffer: inout PixelBuffer,
    mask: [Bool],
    bounds: PixelRect? = nil,
    maskIsLocal: Bool = false,
    dx: Int,
    dy: Int,
    mixed: Bool = false
  ) -> PixelRect? {
    let w = buffer.width
    let h = buffer.height

    var minX = Int.max, maxX = -1, minY = Int.max, maxY = -1, count = 0
    if let b = bounds {
      minX = b.x
      minY = b.y
      maxX = b.x + b.width - 1
      maxY = b.y + b.height - 1
      count = b.width * b.height
    } else {
      guard mask.count == w * h else { return nil }
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

    // Validate the translated masked footprint itself — not the padded crop.
    // The halo (pad below) may cross the canvas edge even when every sampled
    // source pixel fits; that halo is edge-replicated by the clamped sampling.
    guard minX + dx >= 0, maxX + dx < w, minY + dy >= 0, maxY + dy < h else { return nil }

    let pad = 4
    let x0 = max(0, minX - pad)
    let x1 = min(w, maxX + 1 + pad)
    let y0 = max(0, minY - pad)
    let y1 = min(h, maxY + 1 + pad)
    let cropW = x1 - x0
    let cropH = y1 - y0

    let sx0 = x0 + dx
    let sy0 = y0 + dy

    let topPad = max(0, 1 - (minY - y0))
    let bottomPad = max(0, 1 - (y1 - 1 - maxY))
    let leftPad = max(0, 1 - (minX - x0))
    let rightPad = max(0, 1 - (x1 - 1 - maxX))
    let padW = cropW + leftPad + rightPad
    let padH = cropH + topPad + bottomPad
    guard padW >= 3, padH >= 3 else { return nil }

    let neumann = (topPad > 0, bottomPad > 0, leftPad > 0, rightPad > 0)

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
            cropMask[pIdx] = maskIsLocal
              ? mask[(my - y0) * cropW + (mx - x0)]
              : mask[my * w + mx]
          }
        }
      }
    }

    guard hasKnownBoundary(cropMask, padW, padH, neumann) else { return nil }

    let solvedR = solveChannel(
      dest: Plane(width: padW, height: padH, data: dR),
      mask: cropMask,
      src: Plane(width: padW, height: padH, data: sR),
      mixed: mixed, neumann: neumann
    )
    let solvedG = solveChannel(
      dest: Plane(width: padW, height: padH, data: dG),
      mask: cropMask,
      src: Plane(width: padW, height: padH, data: sG),
      mixed: mixed, neumann: neumann
    )
    let solvedB = solveChannel(
      dest: Plane(width: padW, height: padH, data: dB),
      mask: cropMask,
      src: Plane(width: padW, height: padH, data: sB),
      mixed: mixed, neumann: neumann
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

  /// Build a crop-local circular dab mask (scales with the dab, not the canvas).
  /// Returns nil when the clipped dab covers no pixel.
  private static func dabMask(
    cx: Int, cy: Int, r: Int, w: Int, h: Int
  ) -> (mask: [Bool], bounds: PixelRect)? {
    let x0 = max(0, cx - r)
    let x1 = min(w, cx + r + 1)
    let y0 = max(0, cy - r)
    let y1 = min(h, cy + r + 1)
    guard x0 < x1, y0 < y1 else { return nil }
    let bw = x1 - x0
    let bh = y1 - y0
    var mask = [Bool](repeating: false, count: bw * bh)
    let rSq = r * r
    var any = false
    for y in y0..<y1 {
      let dy = y - cy
      let rRow = (y - y0) * bw
      for x in x0..<x1 {
        let dx = x - cx
        if dx * dx + dy * dy <= rSq {
          mask[rRow + (x - x0)] = true
          any = true
        }
      }
    }
    guard any else { return nil }
    return (mask, PixelRect(x: x0, y: y0, width: bw, height: bh))
  }

  /// Spot heal a circular dab at `center` with `radius`.
  @discardableResult
  static func spotHeal(
    buffer: inout PixelBuffer,
    center: CGPoint,
    radius: CGFloat
  ) -> PixelRect? {
    let cx = Int(center.x.rounded())
    let cy = Int(center.y.rounded())
    let r = max(1, Int(radius.rounded()))
    guard let dab = dabMask(cx: cx, cy: cy, r: r, w: buffer.width, h: buffer.height) else {
      return nil
    }
    return inpaint(buffer: &buffer, mask: dab.mask, bounds: dab.bounds, maskIsLocal: true)
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
    let cx = Int(center.x.rounded())
    let cy = Int(center.y.rounded())
    let sx = Int(sourceCenter.x.rounded())
    let sy = Int(sourceCenter.y.rounded())
    let r = max(1, Int(radius.rounded()))
    guard let dab = dabMask(cx: cx, cy: cy, r: r, w: buffer.width, h: buffer.height) else {
      return nil
    }
    return seamlessClone(
      buffer: &buffer, mask: dab.mask, bounds: dab.bounds, maskIsLocal: true,
      dx: sx - cx, dy: sy - cy, mixed: mixed
    )
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
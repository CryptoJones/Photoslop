// SPDX-License-Identifier: Apache-2.0
import Foundation

/// Select and Mask algorithms (Issue #417):
/// 1. Guided Image Filter (local linear regression of the selection mask against
///    underlying color image pixels to extract hair, fur, and soft defocus borders).
/// 2. Smart Radius: adapts edge bandwidth locally to observed transition width.
/// 3. Global Refinements: Smooth (morphological close-then-open), Feather (3-pass box blur),
///    Contrast (steepening ramp around 50%), and Shift Edge (grey morphology -100%..+100%).
/// 4. Color Decontamination: normalized convolution from interior into fringe pixels.
/// 5. Memory Frugality (DD-001): Restrict processing strictly to tiles/strips intersecting
///    the selection boundary dilated by the search radius, with zero persistent allocation overhead.
struct RefineSelectionOptions: Equatable {
  var radius: Int = 0
  var smartRadius: Bool = false
  var smooth: Int = 0
  var feather: Int = 0
  var contrast: Int = 0
  var shiftEdge: Int = 0
  var decontaminate: Bool = false
  var decontaminateAmount: Float = 1.0
}

enum RefineSelectionAlgorithms {

  // MARK: - Box Blur (Float Plane)

  /// Normalized 2D box blur of a Float plane with window radius r.
  /// Exact O(1) running sum per pixel with boundary count normalization.
  static func boxBlurPlane(_ src: [Float], width w: Int, height h: Int, radius r: Int) -> [Float] {
    guard r > 0, w > 0, h > 0 else { return src }
    var temp = [Float](repeating: 0, count: w * h)
    var out = [Float](repeating: 0, count: w * h)

    // Horizontal pass
    for y in 0..<h {
      let rowOffset = y * w
      var sum: Float = 0
      let initialCount = min(r, w - 1)
      for x in 0...initialCount {
        sum += src[rowOffset + x]
      }
      for x in 0..<w {
        if x + r < w && x > 0 {
          sum += src[rowOffset + x + r]
        }
        if x - r - 1 >= 0 {
          sum -= src[rowOffset + x - r - 1]
        }
        let left = max(0, x - r)
        let right = min(w - 1, x + r)
        let count = Float(right - left + 1)
        temp[rowOffset + x] = sum / count
      }
    }

    // Vertical pass
    for x in 0..<w {
      var sum: Float = 0
      let initialCount = min(r, h - 1)
      for y in 0...initialCount {
        sum += temp[y * w + x]
      }
      for y in 0..<h {
        if y + r < h && y > 0 {
          sum += temp[(y + r) * w + x]
        }
        if y - r - 1 >= 0 {
          sum -= temp[(y - r - 1) * w + x]
        }
        let top = max(0, y - r)
        let bottom = min(h - 1, y + r)
        let count = Float(bottom - top + 1)
        out[y * w + x] = sum / count
      }
    }

    return out
  }

  // MARK: - Grey Morphology (3x3 8-connected)

  static func greyDilate(_ plane: [Float], width w: Int, height h: Int) -> [Float] {
    var out = plane
    for y in 0..<h {
      let row = y * w
      let prevRow = (y > 0) ? (y - 1) * w : row
      let nextRow = (y < h - 1) ? (y + 1) * w : row
      for x in 0..<w {
        let prevX = (x > 0) ? x - 1 : x
        let nextX = (x < w - 1) ? x + 1 : x

        var m = plane[row + x]
        m = max(m, plane[prevRow + x])
        m = max(m, plane[nextRow + x])
        m = max(m, plane[row + prevX])
        m = max(m, plane[row + nextX])
        m = max(m, plane[prevRow + prevX])
        m = max(m, plane[prevRow + nextX])
        m = max(m, plane[nextRow + prevX])
        m = max(m, plane[nextRow + nextX])
        out[row + x] = m
      }
    }
    return out
  }

  static func greyErode(_ plane: [Float], width w: Int, height h: Int) -> [Float] {
    var out = plane
    for y in 0..<h {
      let row = y * w
      let prevRow = (y > 0) ? (y - 1) * w : row
      let nextRow = (y < h - 1) ? (y + 1) * w : row
      for x in 0..<w {
        let prevX = (x > 0) ? x - 1 : x
        let nextX = (x < w - 1) ? x + 1 : x

        var m = plane[row + x]
        m = min(m, plane[prevRow + x])
        m = min(m, plane[nextRow + x])
        m = min(m, plane[row + prevX])
        m = min(m, plane[row + nextX])
        m = min(m, plane[prevRow + prevX])
        m = min(m, plane[prevRow + nextX])
        m = min(m, plane[nextRow + prevX])
        m = min(m, plane[nextRow + nextX])
        out[row + x] = m
      }
    }
    return out
  }

  // MARK: - Guided Image Filter

  static func guidedFilter(
    red: [Float],
    green: [Float],
    blue: [Float],
    p: [Float],
    width w: Int,
    height h: Int,
    radius r: Int,
    eps: Float = 1e-3,
    smartRadius: Bool = false
  ) -> [Float] {
    guard r > 0, w > 0, h > 0 else { return p }
    let count = w * h

    func filterCore(_ curRadius: Int) -> [Float] {
      let meanR = boxBlurPlane(red, width: w, height: h, radius: curRadius)
      let meanG = boxBlurPlane(green, width: w, height: h, radius: curRadius)
      let meanB = boxBlurPlane(blue, width: w, height: h, radius: curRadius)
      let meanP = boxBlurPlane(p, width: w, height: h, radius: curRadius)

      var rp = [Float](repeating: 0, count: count)
      var gp = [Float](repeating: 0, count: count)
      var bp = [Float](repeating: 0, count: count)

      var rr = [Float](repeating: 0, count: count)
      var rg = [Float](repeating: 0, count: count)
      var rb = [Float](repeating: 0, count: count)
      var gg = [Float](repeating: 0, count: count)
      var gb = [Float](repeating: 0, count: count)
      var bb = [Float](repeating: 0, count: count)

      for i in 0..<count {
        rp[i] = red[i] * p[i]
        gp[i] = green[i] * p[i]
        bp[i] = blue[i] * p[i]

        rr[i] = red[i] * red[i]
        rg[i] = red[i] * green[i]
        rb[i] = red[i] * blue[i]
        gg[i] = green[i] * green[i]
        gb[i] = green[i] * blue[i]
        bb[i] = blue[i] * blue[i]
      }

      let meanRP = boxBlurPlane(rp, width: w, height: h, radius: curRadius)
      let meanGP = boxBlurPlane(gp, width: w, height: h, radius: curRadius)
      let meanBP = boxBlurPlane(bp, width: w, height: h, radius: curRadius)

      let meanRR = boxBlurPlane(rr, width: w, height: h, radius: curRadius)
      let meanRG = boxBlurPlane(rg, width: w, height: h, radius: curRadius)
      let meanRB = boxBlurPlane(rb, width: w, height: h, radius: curRadius)
      let meanGG = boxBlurPlane(gg, width: w, height: h, radius: curRadius)
      let meanGB = boxBlurPlane(gb, width: w, height: h, radius: curRadius)
      let meanBB = boxBlurPlane(bb, width: w, height: h, radius: curRadius)

      var aR = [Float](repeating: 0, count: count)
      var aG = [Float](repeating: 0, count: count)
      var aB = [Float](repeating: 0, count: count)
      var b = [Float](repeating: 0, count: count)

      for i in 0..<count {
        let covRP = meanRP[i] - meanR[i] * meanP[i]
        let covGP = meanGP[i] - meanG[i] * meanP[i]
        let covBP = meanBP[i] - meanB[i] * meanP[i]

        let varRR = meanRR[i] - meanR[i] * meanR[i] + eps
        let varRG = meanRG[i] - meanR[i] * meanG[i]
        let varRB = meanRB[i] - meanR[i] * meanB[i]
        let varGG = meanGG[i] - meanG[i] * meanG[i] + eps
        let varGB = meanGB[i] - meanG[i] * meanB[i]
        let varBB = meanBB[i] - meanB[i] * meanB[i] + eps

        let inv00 = varGG * varBB - varGB * varGB
        let inv01 = varGB * varRB - varRG * varBB
        let inv02 = varRG * varGB - varGG * varRB

        let inv11 = varRR * varBB - varRB * varRB
        let inv12 = varRB * varRG - varRR * varGB

        let inv22 = varRR * varGG - varRG * varRG

        var det = varRR * inv00 + varRG * inv01 + varRB * inv02
        if det <= 1e-10 { det = 1.0 }

        let ar = (inv00 * covRP + inv01 * covGP + inv02 * covBP) / det
        let ag = (inv01 * covRP + inv11 * covGP + inv12 * covBP) / det
        let ab = (inv02 * covRP + inv12 * covGP + inv22 * covBP) / det

        aR[i] = ar
        aG[i] = ag
        aB[i] = ab
        b[i] = meanP[i] - (ar * meanR[i] + ag * meanG[i] + ab * meanB[i])
      }

      let meanAR = boxBlurPlane(aR, width: w, height: h, radius: curRadius)
      let meanAG = boxBlurPlane(aG, width: w, height: h, radius: curRadius)
      let meanAB = boxBlurPlane(aB, width: w, height: h, radius: curRadius)
      let meanB_ = boxBlurPlane(b, width: w, height: h, radius: curRadius)

      var q = [Float](repeating: 0, count: count)
      for i in 0..<count {
        let val = meanAR[i] * red[i] + meanAG[i] * green[i] + meanAB[i] * blue[i] + meanB_[i]
        q[i] = min(max(val, 0.0), 1.0)
      }
      return q
    }

    let qFull = filterCore(r)
    guard smartRadius else { return qFull }

    let rSmall = max(1, Int((Float(r) * 0.25).rounded()))
    guard rSmall < r else { return qFull }

    let qSmall = filterCore(rSmall)

    // Compute luma for gradient and variance estimation
    var luma = [Float](repeating: 0, count: count)
    var lumaSq = [Float](repeating: 0, count: count)
    for i in 0..<count {
      let y = 0.299 * red[i] + 0.587 * green[i] + 0.114 * blue[i]
      luma[i] = y
      lumaSq[i] = y * y
    }

    var grad = [Float](repeating: 0, count: count)
    for y in 0..<h {
      let row = y * w
      let prevRow = (y > 0) ? (y - 1) * w : row
      let nextRow = (y < h - 1) ? (y + 1) * w : row
      for x in 0..<w {
        let prevX = (x > 0) ? x - 1 : x
        let nextX = (x < w - 1) ? x + 1 : x

        let gx = 0.5 * abs(luma[row + nextX] - luma[row + prevX])
        let gy = 0.5 * abs(luma[nextRow + x] - luma[prevRow + x])
        grad[row + x] = sqrt(gx * gx + gy * gy)
      }
    }
    let peakG = boxBlurPlane(grad, width: w, height: h, radius: 2)

    let meanLuma = boxBlurPlane(luma, width: w, height: h, radius: r)
    let meanLumaSq = boxBlurPlane(lumaSq, width: w, height: h, radius: r)

    var wArr = [Float](repeating: 0, count: count)
    for i in 0..<count {
      let v = max(0.0, meanLumaSq[i] - meanLuma[i] * meanLuma[i])
      let sigma = sqrt(v)
      let factor = min(max(1.0 - 2.0 * peakG[i] + sigma, 0.0), 1.0)
      wArr[i] = factor
    }
    let wSmooth = boxBlurPlane(wArr, width: w, height: h, radius: max(1, rSmall))

    var qSmart = [Float](repeating: 0, count: count)
    for i in 0..<count {
      let weight = wSmooth[i]
      qSmart[i] = min(max((1.0 - weight) * qSmall[i] + weight * qFull[i], 0.0), 1.0)
    }
    return qSmart
  }

  // MARK: - Color Decontamination

  static func decontaminateColors(
    buffer: inout PixelBuffer,
    mask: [Float],
    roiX: Int,
    roiY: Int,
    roiW: Int,
    roiH: Int,
    radius: Int,
    amount: Float
  ) {
    let rDec = max(1, radius)
    let roiCount = roiW * roiH

    var interior = [Float](repeating: 0, count: roiCount)
    var hasInterior = false
    for i in 0..<roiCount {
      if mask[i] > 0.75 {
        interior[i] = 1.0
        hasInterior = true
      }
    }
    if !hasInterior {
      for i in 0..<roiCount {
        if mask[i] > 0.5 {
          interior[i] = 1.0
          hasInterior = true
        }
      }
    }
    guard hasInterior else { return }

    var red = [Float](repeating: 0, count: roiCount)
    var green = [Float](repeating: 0, count: roiCount)
    var blue = [Float](repeating: 0, count: roiCount)
    var alpha = [Float](repeating: 0, count: roiCount)

    var redInt = [Float](repeating: 0, count: roiCount)
    var greenInt = [Float](repeating: 0, count: roiCount)
    var blueInt = [Float](repeating: 0, count: roiCount)

    for ry in 0..<roiH {
      let cy = roiY + ry
      let bufRow = cy * buffer.width
      let roiRow = ry * roiW
      for rx in 0..<roiW {
        let cx = roiX + rx
        let word = buffer.words[bufRow + cx]
        let a = Float((word >> 24) & 0xFF)
        let r = Float((word >> 16) & 0xFF)
        let g = Float((word >> 8) & 0xFF)
        let b = Float(word & 0xFF)

        alpha[roiRow + rx] = a
        if a > 0 {
          let invA = 255.0 / a
          let unR = r * invA
          let unG = g * invA
          let unB = b * invA
          red[roiRow + rx] = unR
          green[roiRow + rx] = unG
          blue[roiRow + rx] = unB
          if interior[roiRow + rx] > 0 {
            redInt[roiRow + rx] = unR
            greenInt[roiRow + rx] = unG
            blueInt[roiRow + rx] = unB
          }
        }
      }
    }

    let denom = boxBlurPlane(interior, width: roiW, height: roiH, radius: rDec)
    let numR = boxBlurPlane(redInt, width: roiW, height: roiH, radius: rDec)
    let numG = boxBlurPlane(greenInt, width: roiW, height: roiH, radius: rDec)
    let numB = boxBlurPlane(blueInt, width: roiW, height: roiH, radius: rDec)

    let amt = min(max(amount, 0.0), 1.0)

    for ry in 0..<roiH {
      let cy = roiY + ry
      let bufRow = cy * buffer.width
      let roiRow = ry * roiW
      for rx in 0..<roiW {
        let idx = roiRow + rx
        let m = mask[idx]
        if m > 0.01 && m < 0.95 && denom[idx] > 1e-4 {
          let extrapR = numR[idx] / max(denom[idx], 1e-6)
          let extrapG = numG[idx] / max(denom[idx], 1e-6)
          let extrapB = numB[idx] / max(denom[idx], 1e-6)

          let blendFactor = amt * (1.0 - m * 0.5)
          let newR = (1.0 - blendFactor) * red[idx] + blendFactor * extrapR
          let newG = (1.0 - blendFactor) * green[idx] + blendFactor * extrapG
          let newB = (1.0 - blendFactor) * blue[idx] + blendFactor * extrapB

          let a = alpha[idx]
          let pr = UInt32(min(max(newR * a / 255.0 + 0.5, 0.0), a))
          let pg = UInt32(min(max(newG * a / 255.0 + 0.5, 0.0), a))
          let pb = UInt32(min(max(newB * a / 255.0 + 0.5, 0.0), a))
          let pa = UInt32(a)

          buffer.words[bufRow + roiX + rx] = (pa << 24) | (pr << 16) | (pg << 8) | pb
        }
      }
    }
  }

  // MARK: - Main Pipeline (Memory Frugality DD-001)

  static func refineSelection(
    mask: SelectionMask,
    buffer: PixelBuffer?,
    options: RefineSelectionOptions
  ) -> (SelectionMask, PixelBuffer?) {
    guard !mask.isEmpty, let bounds = mask.bounds else {
      return (mask, nil)
    }

    let margin =
      options.radius + options.smooth + options.feather + max(10, abs(options.shiftEdge)) + 8
    let x0 = max(0, bounds.x - margin)
    let y0 = max(0, bounds.y - margin)
    let x1 = min(mask.width, bounds.x + bounds.width + margin)
    let y1 = min(mask.height, bounds.y + bounds.height + margin)

    let roiW = x1 - x0
    let roiH = y1 - y0
    guard roiW > 0, roiH > 0 else { return (mask, nil) }

    var alpha = [Float](repeating: 0, count: roiW * roiH)
    for ry in 0..<roiH {
      let maskRow = (y0 + ry) * mask.width
      let roiRow = ry * roiW
      for rx in 0..<roiW {
        if mask.bits[maskRow + x0 + rx] {
          alpha[roiRow + rx] = 1.0
        }
      }
    }

    // 1. Edge Detection: Guided Image Filter
    if options.radius > 0, let buffer = buffer {
      var red = [Float](repeating: 0, count: roiW * roiH)
      var green = [Float](repeating: 0, count: roiW * roiH)
      var blue = [Float](repeating: 0, count: roiW * roiH)
      for ry in 0..<roiH {
        let bufRow = (y0 + ry) * buffer.width
        let roiRow = ry * roiW
        for rx in 0..<roiW {
          let word = buffer.words[bufRow + x0 + rx]
          let a = Float((word >> 24) & 0xFF)
          let invA: Float = (a > 0) ? (255.0 / a) : 1.0
          red[roiRow + rx] = (Float((word >> 16) & 0xFF) * invA) / 255.0
          green[roiRow + rx] = (Float((word >> 8) & 0xFF) * invA) / 255.0
          blue[roiRow + rx] = (Float(word & 0xFF) * invA) / 255.0
        }
      }
      alpha = guidedFilter(
        red: red, green: green, blue: blue, p: alpha, width: roiW, height: roiH,
        radius: options.radius, eps: 1e-3, smartRadius: options.smartRadius)
    }

    // 2. Global Refinements:
    // a. Smooth: morphological close-then-open
    if options.smooth > 0 {
      let sSteps = max(1, Int((Float(options.smooth) / 2.0).rounded()))
      for _ in 0..<sSteps { alpha = greyDilate(alpha, width: roiW, height: roiH) }
      for _ in 0..<(sSteps * 2) { alpha = greyErode(alpha, width: roiW, height: roiH) }
      for _ in 0..<sSteps { alpha = greyDilate(alpha, width: roiW, height: roiH) }
    }

    // b. Feather: 3-pass box blur
    if options.feather > 0 {
      let rFeather = max(1, options.feather / 2 + 1)
      for _ in 0..<3 {
        alpha = boxBlurPlane(alpha, width: roiW, height: roiH, radius: rFeather)
      }
    }

    // c. Contrast: steepens transition ramp around 50%
    if options.contrast > 0 {
      let cVal = min(100, max(0, options.contrast))
      let slope = 1.0 / max(1.0 - 0.98 * (Float(cVal) / 100.0), 0.01)
      for i in 0..<alpha.count {
        alpha[i] = min(max(0.5 + (alpha[i] - 0.5) * slope, 0.0), 1.0)
      }
    }

    // d. Shift Edge: grey morphological dilation (+) / erosion (-)
    if options.shiftEdge != 0 {
      let steps = abs(options.shiftEdge)
      if options.shiftEdge > 0 {
        for _ in 0..<steps { alpha = greyDilate(alpha, width: roiW, height: roiH) }
      } else {
        for _ in 0..<steps { alpha = greyErode(alpha, width: roiW, height: roiH) }
      }
    }

    // Output: Reconstruct full-size mask
    var newBits = [Bool](repeating: false, count: mask.width * mask.height)
    for ry in 0..<roiH {
      let fullRow = (y0 + ry) * mask.width
      let roiRow = ry * roiW
      for rx in 0..<roiW {
        if alpha[roiRow + rx] >= 0.5 {
          newBits[fullRow + x0 + rx] = true
        }
      }
    }

    var refinedMask = SelectionMask(width: mask.width, height: mask.height, bits: newBits)
    if options.feather > 0 {
      refinedMask = refinedMask.feathered(by: options.feather)
    }

    // Color decontamination
    var decontamBuffer: PixelBuffer? = nil
    if options.decontaminate, var buf = buffer {
      decontaminateColors(
        buffer: &buf,
        mask: alpha,
        roiX: x0,
        roiY: y0,
        roiW: roiW,
        roiH: roiH,
        radius: max(options.radius, 8),
        amount: options.decontaminateAmount
      )
      decontamBuffer = buf
    }

    return (refinedMask, decontamBuffer)
  }
}

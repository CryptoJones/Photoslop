// SPDX-License-Identifier: Apache-2.0
//
// Liquify.swift — Mesh displacement deformation with forward warp, twirl,
// pucker, bloat, and freeze masks (#419).
//

import CoreGraphics
import Foundation
import UIKit

// MARK: - Liquify Tool

public enum LiquifyTool: String, CaseIterable, Identifiable, Sendable {
  case forwardWarp = "forward_warp"
  case reconstruct = "reconstruct"
  case smooth = "smooth"
  case twirlCW = "twirl_cw"
  case twirlCCW = "twirl_ccw"
  case pucker = "pucker"
  case bloat = "bloat"
  case pushLeft = "push_left"
  case freezeMask = "freeze_mask"
  case thawMask = "thaw_mask"

  public var id: String { rawValue }

  public var label: String {
    switch self {
    case .forwardWarp: return "Forward Warp"
    case .reconstruct: return "Reconstruct"
    case .smooth: return "Smooth"
    case .twirlCW: return "Twirl CW"
    case .twirlCCW: return "Twirl CCW"
    case .pucker: return "Pucker"
    case .bloat: return "Bloat"
    case .pushLeft: return "Push Left"
    case .freezeMask: return "Freeze Mask"
    case .thawMask: return "Thaw Mask"
    }
  }

  public var iconName: String {
    switch self {
    case .forwardWarp: return "hand.draw"
    case .reconstruct: return "arrow.counterclockwise"
    case .smooth: return "waveform.path"
    case .twirlCW: return "arrow.clockwise"
    case .twirlCCW: return "arrow.counterclockwise"
    case .pucker: return "arrow.down.right.and.arrow.up.left"
    case .bloat: return "arrow.up.left.and.arrow.down.right"
    case .pushLeft: return "arrow.left.to.line"
    case .freezeMask: return "snowflake"
    case .thawMask: return "sun.max"
    }
  }
}

// MARK: - Liquify Grid

public struct LiquifyGrid: Sendable {
  public let width: Int
  public let height: Int
  public let spacing: Int
  public let cols: Int
  public let rows: Int

  public var dx: [Float]
  public var dy: [Float]
  public var freeze: [Float]

  public init(width: Int, height: Int, spacing: Int = 8) {
    precondition(width > 0 && height > 0, "Dimensions must be positive")
    self.width = width
    self.height = height
    let s = max(2, spacing)
    self.spacing = s
    self.cols = (width + s - 1) / s + 1
    self.rows = (height + s - 1) / s + 1

    let count = self.cols * self.rows
    self.dx = [Float](repeating: 0.0, count: count)
    self.dy = [Float](repeating: 0.0, count: count)
    self.freeze = [Float](repeating: 0.0, count: count)
  }

  @inline(__always)
  public func index(col: Int, row: Int) -> Int {
    row * cols + col
  }

  public mutating func reset() {
    dx = [Float](repeating: 0.0, count: cols * rows)
    dy = [Float](repeating: 0.0, count: cols * rows)
  }

  public mutating func clearFreeze() {
    freeze = [Float](repeating: 0.0, count: cols * rows)
  }

  public mutating func invertFreeze() {
    for i in 0..<freeze.count {
      freeze[i] = 1.0 - freeze[i]
    }
  }

  public mutating func applyBrush(
    tool: LiquifyTool,
    center: CGPoint,
    radius: CGFloat,
    pressure: CGFloat = 0.5,
    density: CGFloat = 0.5,
    delta: CGPoint = .zero,
    stepRate: CGFloat = 1.0
  ) {
    let cx = center.x
    let cy = center.y
    let r = max(1.0, radius)
    let p = max(0.0, min(1.0, pressure))
    let d = max(0.0, min(1.0, density))
    let s = CGFloat(spacing)

    let cMin = max(0, Int(floor((cx - r) / s)))
    let cMax = min(cols - 1, Int(ceil((cx + r) / s)))
    let rMin = max(0, Int(floor((cy - r) / s)))
    let rMax = min(rows - 1, Int(ceil((cy + r) / s)))

    guard cMin <= cMax && rMin <= rMax else { return }

    for row in rMin...rMax {
      let gy = CGFloat(row) * s
      let dyDist = gy - cy
      let dyDist2 = dyDist * dyDist

      for col in cMin...cMax {
        let gx = CGFloat(col) * s
        let dxDist = gx - cx
        let dist2 = dxDist * dxDist + dyDist2

        if dist2 >= r * r { continue }
        let dist = sqrt(dist2)
        let t = dist / r

        let tEff: CGFloat
        if d > 0.0 {
          tEff = max(0.0, min(1.0, (t - d) / max(1e-5, 1.0 - d)))
        } else {
          tEff = max(0.0, min(1.0, t))
        }

        let w = Float((1.0 - tEff * tEff) * (1.0 - tEff * tEff) * p * stepRate)
        let idx = row * cols + col
        let wEff = w * (1.0 - freeze[idx])

        switch tool {
        case .forwardWarp:
          dx[idx] -= Float(delta.x) * wEff
          dy[idx] -= Float(delta.y) * wEff

        case .reconstruct:
          let rate = min(1.0, max(0.0, wEff * 0.4))
          dx[idx] *= (1.0 - rate)
          dy[idx] *= (1.0 - rate)

        case .smooth:
          let leftIdx = row * cols + max(0, col - 1)
          let rightIdx = row * cols + min(cols - 1, col + 1)
          let upIdx = max(0, row - 1) * cols + col
          let downIdx = min(rows - 1, row + 1) * cols + col

          let dxMean = (dx[leftIdx] + dx[rightIdx] + dx[upIdx] + dx[downIdx]) * 0.25
          let dyMean = (dy[leftIdx] + dy[rightIdx] + dy[upIdx] + dy[downIdx]) * 0.25
          let rate = min(1.0, max(0.0, wEff * 0.4))
          dx[idx] += (dxMean - dx[idx]) * rate
          dy[idx] += (dyMean - dy[idx]) * rate

        case .twirlCW, .twirlCCW:
          let direction: CGFloat = (tool == .twirlCW) ? -1.0 : 1.0
          let angle = direction * (CGFloat(wEff) * 0.35)
          let cosA = cos(angle)
          let sinA = sin(angle)

          let rx = gx + CGFloat(dx[idx]) - cx
          let ry = gy + CGFloat(dy[idx]) - cy
          let rxNew = rx * cosA - ry * sinA
          let ryNew = rx * sinA + ry * cosA

          dx[idx] = Float((cx + rxNew) - gx)
          dy[idx] = Float((cy + ryNew) - gy)

        case .pucker:
          let scale = 1.0 + CGFloat(wEff) * 0.3
          let rx = gx + CGFloat(dx[idx]) - cx
          let ry = gy + CGFloat(dy[idx]) - cy
          dx[idx] = Float((cx + rx * scale) - gx)
          dy[idx] = Float((cy + ry * scale) - gy)

        case .bloat:
          let scale = max(0.05, 1.0 - CGFloat(wEff) * 0.3)
          let rx = gx + CGFloat(dx[idx]) - cx
          let ry = gy + CGFloat(dy[idx]) - cy
          dx[idx] = Float((cx + rx * scale) - gx)
          dy[idx] = Float((cy + ry * scale) - gy)

        case .pushLeft:
          let length = hypot(delta.x, delta.y)
          if length > 1e-6 {
            let ux = delta.y
            let uy = -delta.x
            dx[idx] -= Float(ux) * wEff
            dy[idx] -= Float(uy) * wEff
          }

        case .freezeMask:
          freeze[idx] = min(1.0, freeze[idx] + w * 0.5)

        case .thawMask:
          freeze[idx] = max(0.0, freeze[idx] - w * 0.5)
        }
      }
    }
  }

  public mutating func applyStroke(
    tool: LiquifyTool,
    points: [CGPoint],
    size: CGFloat,
    pressure: CGFloat = 0.5,
    density: CGFloat = 0.5
  ) {
    guard !points.isEmpty else { return }
    let radius = size / 2.0

    if points.count == 1 {
      applyBrush(tool: tool, center: points[0], radius: radius, pressure: pressure, density: density)
      return
    }

    let stepDist = max(2.0, radius * 0.25)
    for i in 0..<(points.count - 1) {
      let p0 = points[i]
      let p1 = points[i + 1]
      let stepDx = p1.x - p0.x
      let stepDy = p1.y - p0.y
      let dist = hypot(stepDx, stepDy)
      let steps = max(1, Int(ceil(dist / stepDist)))
      let deltaStep = CGPoint(x: stepDx / CGFloat(steps), y: stepDy / CGFloat(steps))

      for s in 1...steps {
        let frac = CGFloat(s) / CGFloat(steps)
        let cx = p0.x + stepDx * frac
        let cy = p0.y + stepDy * frac
        applyBrush(
          tool: tool,
          center: CGPoint(x: cx, y: cy),
          radius: radius,
          pressure: pressure,
          density: density,
          delta: deltaStep,
          stepRate: 1.0
        )
      }
    }
  }

  @inline(__always)
  public func sampleDisplacement(u: Float, v: Float) -> (dx: Float, dy: Float) {
    let c0 = max(0, min(cols - 1, Int(floor(u))))
    let c1 = max(0, min(cols - 1, c0 + 1))
    let wu1 = u - Float(c0)
    let wu0 = 1.0 - wu1

    let r0 = max(0, min(rows - 1, Int(floor(v))))
    let r1 = max(0, min(rows - 1, r0 + 1))
    let wv1 = v - Float(r0)
    let wv0 = 1.0 - wv1

    let i00 = r0 * cols + c0
    let i01 = r0 * cols + c1
    let i10 = r1 * cols + c0
    let i11 = r1 * cols + c1

    let interpDx = (dx[i00] * wu0 + dx[i01] * wu1) * wv0 + (dx[i10] * wu0 + dx[i11] * wu1) * wv1
    let interpDy = (dy[i00] * wu0 + dy[i01] * wu1) * wv0 + (dy[i10] * wu0 + dy[i11] * wu1) * wv1
    return (interpDx, interpDy)
  }
}

// MARK: - Liquify Rasterizer

public enum LiquifyRasterizer {
  /// Rasterize coarse grid inverse mapping p + d(p) into a UIImage.
  public static func rasterize(image: UIImage, grid: LiquifyGrid) -> UIImage? {
    guard let srcBuffer = PixelBuffer(image: image) else { return nil }
    let w = srcBuffer.width
    let h = srcBuffer.height
    guard w == grid.width && h == grid.height else { return nil }

    var dstBuffer = PixelBuffer(width: w, height: h)
    let spacingF = Float(grid.spacing)
    let maxWF = Float(w - 1)
    let maxHF = Float(h - 1)

    srcBuffer.words.withUnsafeBufferPointer { srcWords in
      dstBuffer.words.withUnsafeMutableBufferPointer { dstWords in
        for y in 0..<h {
          let v = Float(y) / spacingF
          let rowOffset = y * w

          for x in 0..<w {
            let u = Float(x) / spacingF
            let (dispX, dispY) = grid.sampleDisplacement(u: u, v: v)

            let sx = max(0.0, min(maxWF, Float(x) + dispX))
            let sy = max(0.0, min(maxHF, Float(y) + dispY))

            let sx0 = Int(floor(sx))
            let sx1 = min(w - 1, sx0 + 1)
            let wx1 = sx - Float(sx0)
            let wx0 = 1.0 - wx1

            let sy0 = Int(floor(sy))
            let sy1 = min(h - 1, sy0 + 1)
            let wy1 = sy - Float(sy0)
            let wy0 = 1.0 - wy1

            let p00 = srcWords[sy0 * w + sx0]
            let p01 = srcWords[sy0 * w + sx1]
            let p10 = srcWords[sy1 * w + sx0]
            let p11 = srcWords[sy1 * w + sx1]

            // ARGB32 unpacking (premultiplied)
            let a00 = Float((p00 >> 24) & 0xFF)
            let r00 = Float((p00 >> 16) & 0xFF)
            let g00 = Float((p00 >> 8) & 0xFF)
            let b00 = Float(p00 & 0xFF)

            let a01 = Float((p01 >> 24) & 0xFF)
            let r01 = Float((p01 >> 16) & 0xFF)
            let g01 = Float((p01 >> 8) & 0xFF)
            let b01 = Float(p01 & 0xFF)

            let a10 = Float((p10 >> 24) & 0xFF)
            let r10 = Float((p10 >> 16) & 0xFF)
            let g10 = Float((p10 >> 8) & 0xFF)
            let b10 = Float(p10 & 0xFF)

            let a11 = Float((p11 >> 24) & 0xFF)
            let r11 = Float((p11 >> 16) & 0xFF)
            let g11 = Float((p11 >> 8) & 0xFF)
            let b11 = Float(p11 & 0xFF)

            let topA = a00 * wx0 + a01 * wx1
            let topR = r00 * wx0 + r01 * wx1
            let topG = g00 * wx0 + g01 * wx1
            let topB = b00 * wx0 + b01 * wx1

            let botA = a10 * wx0 + a11 * wx1
            let botR = r10 * wx0 + r11 * wx1
            let botG = g10 * wx0 + g11 * wx1
            let botB = b10 * wx0 + b11 * wx1

            let outA = UInt32(max(0.0, min(255.0, topA * wy0 + botA * wy1 + 0.5)))
            let outR = UInt32(max(0.0, min(255.0, topR * wy0 + botR * wy1 + 0.5)))
            let outG = UInt32(max(0.0, min(255.0, topG * wy0 + botG * wy1 + 0.5)))
            let outB = UInt32(max(0.0, min(255.0, topB * wy0 + botB * wy1 + 0.5)))

            dstWords[rowOffset + x] = (outA << 24) | (outR << 16) | (outG << 8) | outB
          }
        }
      }
    }

    return dstBuffer.makeImage()
  }
}

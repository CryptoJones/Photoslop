// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import Foundation
import UIKit

/// Intelligent Scissors / Live-wire edge snapping (Issue #416).
///
/// Minimum-cost 8-connected Dijkstra graph search where link costs combine:
/// 1) Gradient magnitude (central differences, high gradient -> low cost)
/// 2) Edge direction (penalizes steps deviating from edge tangent unit vector)
/// 3) Non-maximum suppression (edge centering: local maximum along gradient normal)
/// 4) Gentle pull toward pointer guide line (distance to straight segment ab)
///
/// Respects Memory Frugality (DD-001) by reading pixels lazily in 128px cached blocks
/// along the pointer corridor.
enum LivewireAlgorithms {

  private struct MinHeap {
    struct Item {
      let cost: Float
      let node: Int
    }

    private var items: [Item] = []

    var isEmpty: Bool { items.isEmpty }

    mutating func push(_ item: Item) {
      items.append(item)
      var child = items.count - 1
      while child > 0 {
        let parent = (child - 1) / 2
        if items[child].cost < items[parent].cost {
          items.swapAt(child, parent)
          child = parent
        } else {
          break
        }
      }
    }

    mutating func pop() -> Item? {
      guard !items.isEmpty else { return nil }
      if items.count == 1 { return items.removeLast() }
      let top = items[0]
      items[0] = items.removeLast()
      var parent = 0
      let count = items.count
      while true {
        let left = 2 * parent + 1
        let right = left + 1
        var smallest = parent
        if left < count && items[left].cost < items[smallest].cost {
          smallest = left
        }
        if right < count && items[right].cost < items[smallest].cost {
          smallest = right
        }
        if smallest != parent {
          items.swapAt(parent, smallest)
          parent = smallest
        } else {
          break
        }
      }
      return top
    }
  }

  /// Minimum-cost 8-connected live-wire path from a to b in image coordinates.
  static func livewirePath(
    image: UIImage?,
    from a: CGPoint,
    to b: CGPoint,
    width: Int = 20,
    contrast: Float = 10.0,
    pull: Float = 0.1,
    maxArea: Int = 60000
  ) -> [CGPoint] {
    guard let image, let cgImage = image.cgImage else {
      return [a, b]
    }

    let imgW = cgImage.width
    let imgH = cgImage.height
    guard imgW > 0, imgH > 0 else { return [a, b] }

    let ax = max(0, min(imgW - 1, Int(a.x.rounded())))
    let ay = max(0, min(imgH - 1, Int(a.y.rounded())))
    let bx = max(0, min(imgW - 1, Int(b.x.rounded())))
    let by = max(0, min(imgH - 1, Int(b.y.rounded())))

    let margin = max(4, width)
    let x0 = max(0, min(ax, bx) - margin)
    let x1 = min(imgW, max(ax, bx) + margin + 1)
    let y0 = max(0, min(ay, by) - margin)
    let y1 = min(imgH, max(ay, by) + margin + 1)

    let cw = x1 - x0
    let ch = y1 - y0
    if cw * ch > maxArea || cw < 2 || ch < 2 {
      return [a, b]
    }

    // 128px cached blocks (DD-001)
    let blockSize = 128
    var gray = [Float](repeating: 0, count: cw * ch)
    let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
    let bitmapInfo =
      CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue

    let bx0 = x0 / blockSize
    let bx1 = (x1 - 1) / blockSize
    let by0 = y0 / blockSize
    let by1 = (y1 - 1) / blockSize

    for byIdx in by0...by1 {
      for bxIdx in bx0...bx1 {
        let tx0 = bxIdx * blockSize
        let ty0 = byIdx * blockSize
        let tx1 = min(imgW, tx0 + blockSize)
        let ty1 = min(imgH, ty0 + blockSize)
        let bw = tx1 - tx0
        let bh = ty1 - ty0
        guard bw > 0, bh > 0 else { continue }

        let ox0 = max(x0, tx0)
        let ox1 = min(x1, tx1)
        let oy0 = max(y0, ty0)
        let oy1 = min(y1, ty1)
        guard ox0 < ox1, oy0 < oy1 else { continue }

        guard
          let cropped = cgImage.cropping(to: CGRect(x: tx0, y: ty0, width: bw, height: bh))
        else { continue }

        var blockWords = [UInt32](repeating: 0, count: bw * bh)
        blockWords.withUnsafeMutableBytes { raw in
          guard
            let ctx = CGContext(
              data: raw.baseAddress,
              width: bw,
              height: bh,
              bitsPerComponent: 8,
              bytesPerRow: bw * 4,
              space: colorSpace,
              bitmapInfo: bitmapInfo
            )
          else { return }
          ctx.interpolationQuality = .none
          ctx.draw(cropped, in: CGRect(x: 0, y: 0, width: bw, height: bh))
        }

        for y in oy0..<oy1 {
          let rowOffset = (y - y0) * cw
          let blockRowOffset = (y - ty0) * bw
          for x in ox0..<ox1 {
            let word = blockWords[blockRowOffset + (x - tx0)]
            let r = Float((word >> 16) & 0xFF)
            let g = Float((word >> 8) & 0xFF)
            let bl = Float(word & 0xFF)
            gray[rowOffset + (x - x0)] = 0.299 * r + 0.587 * g + 0.114 * bl
          }
        }
      }
    }

    // Central difference gradients
    var gx = [Float](repeating: 0, count: cw * ch)
    var gy = [Float](repeating: 0, count: cw * ch)
    var grad = [Float](repeating: 0, count: cw * ch)
    var topGrad: Float = 1.0

    for y in 0..<ch {
      let rOffset = y * cw
      for x in 0..<cw {
        let left = x > 0 ? gray[rOffset + x - 1] : gray[rOffset + x]
        let right = x < cw - 1 ? gray[rOffset + x + 1] : gray[rOffset + x]
        let vx = (right - left) * 0.5
        gx[rOffset + x] = vx

        let up = y > 0 ? gray[(y - 1) * cw + x] : gray[rOffset + x]
        let down = y < ch - 1 ? gray[(y + 1) * cw + x] : gray[rOffset + x]
        let vy = (down - up) * 0.5
        gy[rOffset + x] = vy

        let mag = sqrt(vx * vx + vy * vy)
        grad[rOffset + x] = mag
        if mag > topGrad { topGrad = mag }
      }
    }

    let tContrast = (contrast / 100.0) * max(topGrad, 25.5)

    // 1) Gradient cost f_G, 2) Unit normals, 3) NMS f_Z
    var nx = [Float](repeating: 0, count: cw * ch)
    var ny = [Float](repeating: 0, count: cw * ch)
    var fG = [Float](repeating: 1.0, count: cw * ch)
    var fZ = [Float](repeating: 1.0, count: cw * ch)

    let denom = max(1e-5, topGrad - tContrast)
    for idx in 0..<(cw * ch) {
      let g = grad[idx]
      let effG = max(0, g - tContrast)
      fG[idx] = 1.0 - (effG / denom)

      let safeG = max(1e-5, g)
      nx[idx] = gx[idx] / safeG
      ny[idx] = gy[idx] / safeG
    }

    // Vectorized / fast NMS along gradient normal
    if ch > 2 && cw > 2 {
      for y in 1..<(ch - 1) {
        let rOffset = y * cw
        for x in 1..<(cw - 1) {
          let idx = rOffset + x
          let g = grad[idx]
          guard g >= tContrast else { continue }
          let axVal = abs(gx[idx])
          let ayVal = abs(gy[idx])

          let g1: Float
          let g2: Float
          if axVal > 2.414 * ayVal {
            g1 = grad[rOffset + x - 1]
            g2 = grad[rOffset + x + 1]
          } else if ayVal > 2.414 * axVal {
            g1 = grad[(y - 1) * cw + x]
            g2 = grad[(y + 1) * cw + x]
          } else if gx[idx] * gy[idx] > 0 {
            g1 = grad[(y + 1) * cw + x + 1]
            g2 = grad[(y - 1) * cw + x - 1]
          } else {
            g1 = grad[(y - 1) * cw + x + 1]
            g2 = grad[(y + 1) * cw + x - 1]
          }

          if g >= g1 && g >= g2 {
            fZ[idx] = 0.0
          }
        }
      }
    }

    // 4) Guide pull toward straight segment ab
    let axRel = Float(ax - x0)
    let ayRel = Float(ay - y0)
    let bxRel = Float(bx - x0)
    let byRel = Float(by - y0)
    let segVx = bxRel - axRel
    let segVy = byRel - ayRel
    let segLenSq = segVx * segVx + segVy * segVy
    let marginFloat = max(1.0, Float(margin))

    var nodeCost = [Float](repeating: 0, count: cw * ch)
    for y in 0..<ch {
      let wy = Float(y) - ayRel
      let rOffset = y * cw
      for x in 0..<cw {
        let wx = Float(x) - axRel
        let distLine: Float
        if segLenSq > 0 {
          let t = max(0.0, min(1.0, (wx * segVx + wy * segVy) / segLenSq))
          let projX = axRel + t * segVx
          let projY = ayRel + t * segVy
          let dx = Float(x) - projX
          let dy = Float(y) - projY
          distLine = sqrt(dx * dx + dy * dy)
        } else {
          distLine = sqrt(wx * wx + wy * wy)
        }
        let fP = min(1.0, distLine / marginFloat)
        let idx = rOffset + x
        nodeCost[idx] = 0.45 * fG[idx] + 0.20 * fZ[idx] + pull * fP + 0.02
      }
    }

    // Dijkstra minimum-cost search
    let start = (ay - y0) * cw + (ax - x0)
    let goal = (by - y0) * cw + (bx - x0)

    var dist = [Float](repeating: .infinity, count: cw * ch)
    var parent = [Int](repeating: -1, count: cw * ch)
    dist[start] = 0.0

    var heap = MinHeap()
    heap.push(MinHeap.Item(cost: 0.0, node: start))

    let sqrt2: Float = 1.41421356
    let invSqrt2: Float = 0.70710678
    let steps: [(dx: Int, dy: Int, len: Float, udx: Float, udy: Float)] = [
      (-1, -1, sqrt2, -invSqrt2, -invSqrt2),
      (0, -1, 1.0, 0.0, -1.0),
      (1, -1, sqrt2, invSqrt2, -invSqrt2),
      (-1, 0, 1.0, -1.0, 0.0),
      (1, 0, 1.0, 1.0, 0.0),
      (-1, 1, sqrt2, -invSqrt2, invSqrt2),
      (0, 1, 1.0, 0.0, 1.0),
      (1, 1, sqrt2, invSqrt2, invSqrt2),
    ]

    while let top = heap.pop() {
      let u = top.node
      if u == goal { break }
      if top.cost > dist[u] { continue }

      let ux = u % cw
      let uy = u / cw
      let uNx = nx[u]
      let uNy = ny[u]
      let hasEdgeDir = grad[u] >= tContrast

      for step in steps {
        let vxCoord = ux + step.dx
        let vyCoord = uy + step.dy
        guard vxCoord >= 0, vxCoord < cw, vyCoord >= 0, vyCoord < ch else { continue }
        let v = vyCoord * cw + vxCoord

        let fD: Float = hasEdgeDir ? abs(step.udx * uNx + step.udy * uNy) : 0.5
        let wEdge = step.len * (nodeCost[v] + 0.30 * fD)
        let nd = top.cost + wEdge
        if nd < dist[v] {
          dist[v] = nd
          parent[v] = u
          heap.push(MinHeap.Item(cost: nd, node: v))
        }
      }
    }

    if parent[goal] < 0 && goal != start {
      return [a, b]
    }

    var path: [CGPoint] = []
    var curr = goal
    while curr >= 0 {
      path.append(CGPoint(x: curr % cw + x0, y: curr / cw + y0))
      if curr == start { break }
      curr = parent[curr]
    }
    path.reverse()
    return path
  }
}

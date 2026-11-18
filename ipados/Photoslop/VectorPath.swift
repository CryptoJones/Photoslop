// SPDX-License-Identifier: Apache-2.0
import CoreGraphics
import Foundation
import UIKit

/// Structured vector path command matching photoslop/vector.py schema (#424).
enum VectorPathCommand: Equatable {
  case move(CGPoint, node: String = "smooth")
  case line(CGPoint, node: String = "corner")
  case cubic(control1: CGPoint, control2: CGPoint, point: CGPoint, node: String = "smooth")
  case close

  var point: CGPoint? {
    switch self {
    case .move(let p, _), .line(let p, _), .cubic(_, _, let p, _):
      return p
    case .close:
      return nil
    }
  }

  var op: String {
    switch self {
    case .move: return "M"
    case .line: return "L"
    case .cubic: return "C"
    case .close: return "Z"
    }
  }

  var node: String {
    switch self {
    case .move(_, let node), .line(_, let node), .cubic(_, _, _, let node):
      return node
    case .close:
      return "corner"
    }
  }
}

extension Collection where Element == VectorPathCommand {
  func toCGPath() -> CGPath {
    let path = CGMutablePath()
    for command in self {
      switch command {
      case .move(let p, _):
        path.move(to: p)
      case .line(let p, _):
        path.addLine(to: p)
      case .cubic(let c1, let c2, let p, _):
        path.addCurve(to: p, control1: c1, control2: c2)
      case .close:
        path.closeSubpath()
      }
    }
    return path
  }

  func toSVGPath() -> String {
    var parts: [String] = []
    for command in self {
      switch command {
      case .move(let p, _):
        parts.append("M \(p.x) \(p.y)")
      case .line(let p, _):
        parts.append("L \(p.x) \(p.y)")
      case .cubic(let c1, let c2, let p, _):
        parts.append("C \(c1.x) \(c1.y) \(c2.x) \(c2.y) \(p.x) \(p.y)")
      case .close:
        parts.append("Z")
      }
    }
    return parts.joined(separator: " ")
  }
}

/// Potrace-style contour decomposition and Bézier curve fitting.
enum VectorPathTracer {
  private static let dx = [0, 1, 0, -1]  // 0: N, 1: E, 2: S, 3: W
  private static let dy = [-1, 0, 1, 0]

  private static func nextDir(
    nx: Int, ny: Int, inDir: Int, width: Int, height: Int, bits: [Bool]
  ) -> Int? {
    func getBit(_ x: Int, _ y: Int) -> Bool {
      guard x >= 0, x < width, y >= 0, y < height else { return false }
      return bits[y * width + x]
    }

    let tl = getBit(nx - 1, ny - 1)
    let tr = getBit(nx, ny - 1)
    let bl = getBit(nx - 1, ny)
    let br = getBit(nx, ny)

    // 8-connected diagonal saddle disambiguation
    if tl && br && !tr && !bl {
      if inDir == 2 { return 3 }  // incoming Southbound -> West
      if inDir == 0 { return 1 }  // incoming Northbound -> East
    }
    if tr && bl && !tl && !br {
      if inDir == 1 { return 2 }  // incoming Eastbound -> South
      if inDir == 3 { return 0 }  // incoming Westbound -> North
    }

    if !tl && tr && inDir != 2 { return 0 }
    if !tr && br && inDir != 3 { return 1 }
    if bl && !br && inDir != 0 { return 2 }
    if tl && !bl && inDir != 1 { return 3 }

    for outD in 0...3 {
      if outD == 0 && !tl && tr { return 0 }
      if outD == 1 && !tr && br { return 1 }
      if outD == 2 && bl && !br { return 2 }
      if outD == 3 && tl && !bl { return 3 }
    }
    return nil
  }

  static func traceContours(width: Int, height: Int, bits: [Bool]) -> [[CGPoint]] {
    func getBit(_ x: Int, _ y: Int) -> Bool {
      guard x >= 0, x < width, y >= 0, y < height else { return false }
      return bits[y * width + x]
    }

    struct Edge: Hashable {
      let x: Int
      let y: Int
      let dir: Int
    }

    var allEdges = Set<Edge>()
    for y in 0...height {
      for x in 0...width {
        let tl = getBit(x - 1, y - 1)
        let tr = getBit(x, y - 1)
        let bl = getBit(x - 1, y)
        let br = getBit(x, y)
        if !tl && tr { allEdges.insert(Edge(x: x, y: y, dir: 0)) }
        if !tr && br { allEdges.insert(Edge(x: x, y: y, dir: 1)) }
        if bl && !br { allEdges.insert(Edge(x: x, y: y, dir: 2)) }
        if tl && !bl { allEdges.insert(Edge(x: x, y: y, dir: 3)) }
      }
    }

    var visited = Set<Edge>()
    var loops: [[CGPoint]] = []

    for startEdge in allEdges {
      if visited.contains(startEdge) { continue }
      var curr = startEdge
      var loop: [CGPoint] = []
      while !visited.contains(curr) {
        visited.insert(curr)
        loop.append(CGPoint(x: curr.x, y: curr.y))
        let nx = curr.x + dx[curr.dir]
        let ny = curr.y + dy[curr.dir]
        guard
          let nd = nextDir(
            nx: nx, ny: ny, inDir: curr.dir, width: width, height: height, bits: bits)
        else { break }
        curr = Edge(x: nx, y: ny, dir: nd)
      }
      if loop.count >= 3 {
        let compressed = compressCollinear(loop)
        if compressed.count >= 3 {
          loops.append(compressed)
        }
      }
    }
    return loops
  }

  static func compressCollinear(_ pts: [CGPoint]) -> [CGPoint] {
    let n = pts.count
    guard n > 2 else { return pts }
    var out: [CGPoint] = []
    for i in 0..<n {
      let p0 = pts[(i - 1 + n) % n]
      let p1 = pts[i]
      let p2 = pts[(i + 1) % n]
      let dx1 = p1.x - p0.x
      let dy1 = p1.y - p0.y
      let dx2 = p2.x - p1.x
      let dy2 = p2.y - p1.y
      if dx1 * dy2 != dy1 * dx2 || (dx1 * dx2 + dy1 * dy2 <= 0) {
        out.append(p1)
      }
    }
    return out.count >= 3 ? out : pts
  }

  private static func pointLineDist(_ pt: CGPoint, _ a: CGPoint, _ b: CGPoint) -> CGFloat {
    let dx = b.x - a.x
    let dy = b.y - a.y
    let segSq = dx * dx + dy * dy
    if segSq == 0 {
      return hypot(pt.x - a.x, pt.y - a.y)
    }
    return abs(dy * pt.x - dx * pt.y + b.x * a.y - b.y * a.x) / sqrt(segSq)
  }

  private static func rdpOpen(_ pts: [CGPoint], epsilon: CGFloat) -> [CGPoint] {
    guard pts.count > 2 else { return pts }
    let a = pts[0], b = pts[pts.count - 1]
    var maxD: CGFloat = -1.0
    var idx = -1
    for i in 1..<(pts.count - 1) {
      let d = pointLineDist(pts[i], a, b)
      if d > maxD {
        maxD = d
        idx = i
      }
    }
    if maxD > epsilon {
      let left = rdpOpen(Array(pts[0...idx]), epsilon: epsilon)
      let right = rdpOpen(Array(pts[idx..<pts.count]), epsilon: epsilon)
      return Array(left.dropLast()) + right
    }
    return [a, b]
  }

  static func simplifyPolygon(_ pts: [CGPoint], tolerance: Double) -> [CGPoint] {
    guard pts.count > 3 else { return pts }
    let epsilon = CGFloat(max(0.2, tolerance * 0.5))
    let p0 = pts[0]
    var maxDSq: CGFloat = -1.0
    var split = pts.count / 2
    for i in 1..<pts.count {
      let dx = pts[i].x - p0.x
      let dy = pts[i].y - p0.y
      let dSq = dx * dx + dy * dy
      if dSq > maxDSq {
        maxDSq = dSq
        split = i
      }
    }
    let part1 = rdpOpen(Array(pts[0...split]), epsilon: epsilon)
    let part2 = rdpOpen(Array(pts[split..<pts.count]) + [pts[0]], epsilon: epsilon)
    let res = Array(part1.dropLast()) + Array(part2.dropLast())
    return res.count >= 3 ? res : pts
  }

  static func fitCubicBeziers(
    _ pts: [CGPoint], cornerAngleThresh: Double = 75.0
  ) -> [VectorPathCommand] {
    let n = pts.count
    guard n >= 3 else {
      var cmds: [VectorPathCommand] = [.move(pts[0], node: "corner")]
      for p in pts.dropFirst() { cmds.append(.line(p, node: "corner")) }
      cmds.append(.close)
      return cmds
    }

    let cosThresh = CGFloat(cos(cornerAngleThresh * .pi / 180.0))
    var isCorner = [Bool](repeating: false, count: n)

    for i in 0..<n {
      let prev = pts[(i - 1 + n) % n]
      let curr = pts[i]
      let next = pts[(i + 1) % n]
      let v1x = curr.x - prev.x, v1y = curr.y - prev.y
      let v2x = next.x - curr.x, v2y = next.y - curr.y
      let l1 = hypot(v1x, v1y)
      let l2 = hypot(v2x, v2y)
      if l1 < 1e-6 || l2 < 1e-6 {
        isCorner[i] = true
        continue
      }
      let cosAng = (v1x * v2x + v1y * v2y) / (l1 * l2)
      if cosAng < cosThresh {
        isCorner[i] = true
      }
    }

    let firstNode = isCorner[0] ? "corner" : "smooth"
    var commands: [VectorPathCommand] = [.move(pts[0], node: firstNode)]

    for i in 0..<n {
      let p0 = pts[(i - 1 + n) % n]
      let p1 = pts[i]
      let p2 = pts[(i + 1) % n]
      let p3 = pts[(i + 2) % n]

      let c1Corner = isCorner[i]
      let c2Corner = isCorner[(i + 1) % n]

      let chordVx = p2.x - p1.x
      let chordVy = p2.y - p1.y
      let chord = hypot(chordVx, chordVy)
      if chord < 1e-6 { continue }

      let t1x: CGFloat
      let t1y: CGFloat
      if c1Corner {
        t1x = chordVx / chord
        t1y = chordVy / chord
      } else {
        let vPrevX = p1.x - p0.x, vPrevY = p1.y - p0.y
        let vNextX = p2.x - p1.x, vNextY = p2.y - p1.y
        let lPrev = max(1e-6, hypot(vPrevX, vPrevY))
        let lNext = max(1e-6, hypot(vNextX, vNextY))
        let sx = vPrevX / lPrev + vNextX / lNext
        let sy = vPrevY / lPrev + vNextY / lNext
        let slen = max(1e-6, hypot(sx, sy))
        t1x = sx / slen
        t1y = sy / slen
      }

      let t2x: CGFloat
      let t2y: CGFloat
      if c2Corner {
        t2x = chordVx / chord
        t2y = chordVy / chord
      } else {
        let vCurrX = p2.x - p1.x, vCurrY = p2.y - p1.y
        let vAfterX = p3.x - p2.x, vAfterY = p3.y - p2.y
        let lCurr = max(1e-6, hypot(vCurrX, vCurrY))
        let lAfter = max(1e-6, hypot(vAfterX, vAfterY))
        let sx = vCurrX / lCurr + vAfterX / lAfter
        let sy = vCurrY / lCurr + vAfterY / lAfter
        let slen = max(1e-6, hypot(sx, sy))
        t2x = sx / slen
        t2y = sy / slen
      }

      let c1 = CGPoint(x: p1.x + t1x * (chord / 3.0), y: p1.y + t1y * (chord / 3.0))
      let c2 = CGPoint(x: p2.x - t2x * (chord / 3.0), y: p2.y - t2y * (chord / 3.0))

      let nodeType = c2Corner ? "corner" : "smooth"
      commands.append(
        .cubic(
          control1: CGPoint(x: round(c1.x * 1000) / 1000, y: round(c1.y * 1000) / 1000),
          control2: CGPoint(x: round(c2.x * 1000) / 1000, y: round(c2.y * 1000) / 1000),
          point: CGPoint(x: round(p2.x * 1000) / 1000, y: round(p2.y * 1000) / 1000),
          node: nodeType
        )
      )
    }

    commands.append(.close)
    return commands
  }
}

extension SelectionMask {
  /// Extract vector path commands from the selection mask subject to tolerance.
  func makeVectorPath(tolerance: Double = 2.0) -> [VectorPathCommand] {
    let loops = VectorPathTracer.traceContours(width: width, height: height, bits: bits)
    var commands: [VectorPathCommand] = []
    for loop in loops {
      let simplified = VectorPathTracer.simplifyPolygon(loop, tolerance: tolerance)
      let cmds = VectorPathTracer.fitCubicBeziers(simplified)
      commands.append(contentsOf: cmds)
    }
    return commands
  }

  /// Convert active selection to a CoreGraphics CGPath.
  func vectorCGPath(tolerance: Double = 2.0) -> CGPath {
    makeVectorPath(tolerance: tolerance).toCGPath()
  }
}

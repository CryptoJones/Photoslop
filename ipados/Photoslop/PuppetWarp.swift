// SPDX-License-Identifier: Apache-2.0
//
// PuppetWarp.swift — Mesh pin deformation via As-Rigid-As-Possible (ARAP) solver (#420).
//

import CoreGraphics
import Foundation
import UIKit

// MARK: - Puppet Mode

public enum PuppetMode: String, CaseIterable, Identifiable, Sendable {
  case rigid = "rigid"
  case normal = "normal"
  case distort = "distort"

  public var id: String { rawValue }

  public var label: String {
    switch self {
    case .rigid: return "Rigid"
    case .normal: return "Normal"
    case .distort: return "Distort"
    }
  }
}

// MARK: - Puppet Pin

public struct PuppetPin: Identifiable, Equatable, Sendable {
  public let id: UUID
  public var rest: CGPoint
  public var target: CGPoint
  public var depth: Int
  public var rotation: CGFloat  // degrees
  public var vertexIndex: Int

  public init(
    id: UUID = UUID(),
    rest: CGPoint,
    target: CGPoint,
    depth: Int = 0,
    rotation: CGFloat = 0.0,
    vertexIndex: Int = -1
  ) {
    self.id = id
    self.rest = rest
    self.target = target
    self.depth = depth
    self.rotation = rotation
    self.vertexIndex = vertexIndex
  }
}

// MARK: - Puppet Mesh

public struct PuppetMesh: Sendable {
  public var vertices: [CGPoint]  // Rest positions
  public var deformedVertices: [CGPoint]  // Current deformed positions
  public var triangles: [(Int, Int, Int)]  // Vertex index tuples
  public var adj: [[Int]]  // Adjacency per vertex
  public var components: [[Int]]  // Connected component vertex indices
  public var spacing: Int

  public init(
    vertices: [CGPoint],
    deformedVertices: [CGPoint],
    triangles: [(Int, Int, Int)],
    adj: [[Int]],
    components: [[Int]],
    spacing: Int
  ) {
    self.vertices = vertices
    self.deformedVertices = deformedVertices
    self.triangles = triangles
    self.adj = adj
    self.components = components
    self.spacing = spacing
  }

  /// Generates a uniform 2D triangle mesh covering the non-transparent alpha region.
  public static func generate(from image: UIImage, spacing: Int = 20) -> PuppetMesh {
    guard let cgImage = image.cgImage else {
      let v = [CGPoint(x: 0, y: 0), CGPoint(x: 100, y: 0), CGPoint(x: 100, y: 100), CGPoint(x: 0, y: 100)]
      return PuppetMesh(
        vertices: v, deformedVertices: v, triangles: [(0, 1, 2), (0, 2, 3)],
        adj: [[1, 2, 3], [0, 2], [0, 1, 3], [0, 2]], components: [[0, 1, 2, 3]], spacing: spacing)
    }

    let w = cgImage.width
    let h = cgImage.height
    if w < 2 || h < 2 {
      let v = [CGPoint(x: 0, y: 0), CGPoint(x: w, y: 0), CGPoint(x: w, y: h), CGPoint(x: 0, y: h)]
      return PuppetMesh(
        vertices: v, deformedVertices: v, triangles: [(0, 1, 2), (0, 2, 3)],
        adj: [[1, 2, 3], [0, 2], [0, 1, 3], [0, 2]], components: [[0, 1, 2, 3]], spacing: spacing)
    }

    // Extract alpha channel
    let alphaBytes = extractAlpha(from: cgImage)
    let hasTransparency = alphaBytes.contains(where: { $0 < 255 })
    let anyOpaque = alphaBytes.contains(where: { $0 > 0 })

    if !anyOpaque {
      let v = [CGPoint(x: 0, y: 0), CGPoint(x: w, y: 0), CGPoint(x: w, y: h), CGPoint(x: 0, y: h)]
      return PuppetMesh(
        vertices: v, deformedVertices: v, triangles: [(0, 1, 2), (0, 2, 3)],
        adj: [[1, 2, 3], [0, 2], [0, 1, 3], [0, 2]], components: [[0, 1, 2, 3]], spacing: spacing)
    }

    let step = max(6, spacing)
    var xs: [Int] = Array(stride(from: 0, to: w, by: step))
    if xs.last != w { xs.append(w) }
    var ys: [Int] = Array(stride(from: 0, to: h, by: step))
    if ys.last != h { ys.append(h) }

    let numX = xs.count
    let numY = ys.count

    var activeCells = [[Bool]](repeating: [Bool](repeating: false, count: numX - 1), count: numY - 1)

    if !hasTransparency {
      for r in 0..<(numY - 1) {
        for c in 0..<(numX - 1) {
          activeCells[r][c] = true
        }
      }
    } else {
      for r in 0..<(numY - 1) {
        let y0 = ys[r], y1 = ys[r + 1]
        for c in 0..<(numX - 1) {
          let x0 = xs[c], x1 = xs[c + 1]
          var cellHasAlpha = false
          checkCell: for y in y0..<y1 {
            let rowOff = y * w
            for x in x0..<x1 {
              if alphaBytes[rowOff + x] > 0 {
                cellHasAlpha = true
                break checkCell
              }
            }
          }
          activeCells[r][c] = cellHasAlpha
        }
      }

      // Dilate by 1 cell margin
      var dilated = activeCells
      for r in 0..<(numY - 1) {
        for c in 0..<(numX - 1) {
          if activeCells[r][c] {
            let rMin = max(0, r - 1), rMax = min(numY - 1, r + 2)
            let cMin = max(0, c - 1), cMax = min(numX - 1, c + 2)
            for dr in rMin..<rMax {
              for dc in cMin..<cMax {
                dilated[dr][dc] = true
              }
            }
          }
        }
      }
      activeCells = dilated
    }

    var vertexDict = [Int: Int]()  // (r * numX + c) -> vertex index
    var vertices: [CGPoint] = []

    func getVertexIndex(r: Int, c: Int) -> Int {
      let key = r * numX + c
      if let idx = vertexDict[key] { return idx }
      let newIdx = vertices.count
      vertices.append(CGPoint(x: xs[c], y: ys[r]))
      vertexDict[key] = newIdx
      return newIdx
    }

    var triangles: [(Int, Int, Int)] = []
    for r in 0..<(numY - 1) {
      for c in 0..<(numX - 1) {
        if activeCells[r][c] {
          let v00 = getVertexIndex(r: r, c: c)
          let v10 = getVertexIndex(r: r + 1, c: c)
          let v01 = getVertexIndex(r: r, c: c + 1)
          let v11 = getVertexIndex(r: r + 1, c: c + 1)
          triangles.append((v00, v10, v11))
          triangles.append((v00, v11, v01))
        }
      }
    }

    let n = vertices.count
    var adjSet = [Set<Int>](repeating: Set<Int>(), count: n)
    for (a, b, c) in triangles {
      adjSet[a].insert(b); adjSet[a].insert(c)
      adjSet[b].insert(a); adjSet[b].insert(c)
      adjSet[c].insert(a); adjSet[c].insert(b)
    }
    let adj = adjSet.map { $0.sorted() }

    // Connected components
    var visited = [Bool](repeating: false, count: n)
    var components: [[Int]] = []
    for i in 0..<n {
      if !visited[i] {
        var comp: [Int] = []
        var queue = [i]
        visited[i] = true
        while !queue.isEmpty {
          let curr = queue.removeLast()
          comp.append(curr)
          for nbr in adj[curr] {
            if !visited[nbr] {
              visited[nbr] = true
              queue.append(nbr)
            }
          }
        }
        components.append(comp)
      }
    }

    return PuppetMesh(
      vertices: vertices,
      deformedVertices: vertices,
      triangles: triangles,
      adj: adj,
      components: components,
      spacing: step
    )
  }

  private static func extractAlpha(from cgImage: CGImage) -> [UInt8] {
    let w = cgImage.width
    let h = cgImage.height
    var alpha = [UInt8](repeating: 0, count: w * h)
    let colorSpace = CGColorSpaceCreateDeviceGray()
    guard
      let ctx = CGContext(
        data: &alpha, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w,
        space: colorSpace, bitmapInfo: CGImageAlphaInfo.none.rawValue)
    else {
      return [UInt8](repeating: 255, count: w * h)
    }
    ctx.draw(cgImage, in: CGRect(x: 0, y: 0, width: w, height: h))
    return alpha
  }
}

// MARK: - ARAP Solver

public enum ARAPSolver {
  /// Solves the As-Rigid-As-Possible deformation satisfying pin constraints.
  public static func solve(
    mesh: inout PuppetMesh,
    pins: inout [PuppetPin],
    mode: PuppetMode = .normal,
    iterations: Int = 8
  ) {
    let n = mesh.vertices.count
    guard n > 0 else { return }

    if pins.isEmpty {
      mesh.deformedVertices = mesh.vertices
      return
    }

    // Map pins to nearest vertices
    for i in 0..<pins.count {
      if pins[i].vertexIndex < 0 || pins[i].vertexIndex >= n {
        let p = pins[i].rest
        var bestIdx = 0
        var bestDist = Double.infinity
        for (vIdx, v) in mesh.vertices.enumerated() {
          let d = (Double(v.x - p.x) * Double(v.x - p.x)) + (Double(v.y - p.y) * Double(v.y - p.y))
          if d < bestDist {
            bestDist = d
            bestIdx = vIdx
          }
        }
        pins[i].vertexIndex = bestIdx
      }
    }

    // Single pin case
    if pins.count == 1 {
      let pin = pins[0]
      let dx = pin.target.x - pin.rest.x
      let dy = pin.target.y - pin.rest.y
      if abs(pin.rotation) > 0.001 {
        let rad = Double(pin.rotation) * .pi / 180.0
        let c = cos(rad), s = sin(rad)
        for i in 0..<n {
          let rx = Double(mesh.vertices[i].x - pin.rest.x)
          let ry = Double(mesh.vertices[i].y - pin.rest.y)
          let rotX = rx * c - ry * s + Double(pin.target.x)
          let rotY = rx * s + ry * c + Double(pin.target.y)
          mesh.deformedVertices[i] = CGPoint(x: rotX, y: rotY)
        }
      } else {
        for i in 0..<n {
          mesh.deformedVertices[i] = CGPoint(x: mesh.vertices[i].x + dx, y: mesh.vertices[i].y + dy)
        }
      }
      return
    }

    var vCur = mesh.deformedVertices

    var pinRotations = [Int: (c: Double, s: Double)]()
    for pin in pins where abs(pin.rotation) > 0.001 {
      let rad = Double(pin.rotation) * .pi / 180.0
      pinRotations[pin.vertexIndex] = (cos(rad), sin(rad))
    }

    // Solve component by component
    for comp in mesh.components {
      let compSet = Set(comp)
      let compPins = pins.filter { compSet.contains($0.vertexIndex) }

      if compPins.isEmpty {
        for vIdx in comp { vCur[vIdx] = mesh.vertices[vIdx] }
        continue
      }

      if compPins.count == 1 {
        let p = compPins[0]
        let dx = p.target.x - p.rest.x
        let dy = p.target.y - p.rest.y
        if abs(p.rotation) > 0.001 {
          let rad = Double(p.rotation) * .pi / 180.0
          let c = cos(rad), s = sin(rad)
          for vIdx in comp {
            let rx = Double(mesh.vertices[vIdx].x - p.rest.x)
            let ry = Double(mesh.vertices[vIdx].y - p.rest.y)
            let rotX = rx * c - ry * s + Double(p.target.x)
            let rotY = rx * s + ry * c + Double(p.target.y)
            vCur[vIdx] = CGPoint(x: rotX, y: rotY)
          }
        } else {
          for vIdx in comp {
            vCur[vIdx] = CGPoint(x: mesh.vertices[vIdx].x + dx, y: mesh.vertices[vIdx].y + dy)
          }
        }
        continue
      }

      let compN = comp.count
      var globalToLocal = [Int: Int]()
      for (loc, g) in comp.enumerated() { globalToLocal[g] = loc }

      // Build Laplacian matrix
      var A = [[Double]](repeating: [Double](repeating: 0.0, count: compN), count: compN)
      for (loc, g) in comp.enumerated() {
        for nbr in mesh.adj[g] {
          if let nbrLoc = globalToLocal[nbr] {
            A[loc][loc] += 1.0
            A[loc][nbrLoc] = -1.0
          }
        }
      }

      let wPin = 10000.0
      for p in compPins {
        if let pLoc = globalToLocal[p.vertexIndex] {
          A[pLoc][pLoc] += wPin
        }
      }

      let isRigid = mode == .rigid
      let isDistort = mode == .distort

      var compVCurX = comp.map { Double(vCur[$0].x) }
      var compVCurY = comp.map { Double(vCur[$0].y) }
      let compVX = comp.map { Double(mesh.vertices[$0].x) }
      let compVY = comp.map { Double(mesh.vertices[$0].y) }

      for _ in 0..<iterations {
        // Local step: compute 2D rotation & scale T_i
        var T00 = [Double](repeating: 1.0, count: compN)
        var T01 = [Double](repeating: 0.0, count: compN)
        var T10 = [Double](repeating: 0.0, count: compN)
        var T11 = [Double](repeating: 1.0, count: compN)

        for (loc, g) in comp.enumerated() {
          if let rot = pinRotations[g] {
            T00[loc] = rot.c; T01[loc] = -rot.s
            T10[loc] = rot.s; T11[loc] = rot.c
            continue
          }

          var s00 = 0.0, s01 = 0.0, s10 = 0.0, s11 = 0.0
          var restSqSum = 0.0

          let vix = compVX[loc], viy = compVY[loc]
          let vcx = compVCurX[loc], vcy = compVCurY[loc]

          for nbr in mesh.adj[g] {
            guard let nbrLoc = globalToLocal[nbr] else { continue }
            let ex = vix - compVX[nbrLoc]
            let ey = viy - compVY[nbrLoc]
            let epx = vcx - compVCurX[nbrLoc]
            let epy = vcy - compVCurY[nbrLoc]

            s00 += epx * ex
            s01 += epx * ey
            s10 += epy * ex
            s11 += epy * ey
            restSqSum += ex * ex + ey * ey
          }

          let a = s00 + s11
          let b = s10 - s01
          let r = sqrt(a * a + b * b)

          var c = 1.0, s = 0.0
          if r > 1e-9 {
            c = a / r
            s = b / r
          }

          var scale = 1.0
          if !isRigid && restSqSum > 1e-9 {
            let rawScale = r / restSqSum
            if isDistort {
              scale = max(0.1, min(rawScale, 3.0))
            } else {
              scale = max(0.65, min(1.0 + 0.5 * (rawScale - 1.0), 1.5))
            }
          }

          T00[loc] = scale * c; T01[loc] = -scale * s
          T10[loc] = scale * s; T11[loc] = scale * c
        }

        // Global step: RHS B and linear solve
        var Bx = [Double](repeating: 0.0, count: compN)
        var By = [Double](repeating: 0.0, count: compN)

        for (loc, g) in comp.enumerated() {
          let t00_i = T00[loc], t01_i = T01[loc]
          let t10_i = T10[loc], t11_i = T11[loc]

          for nbr in mesh.adj[g] {
            guard let nbrLoc = globalToLocal[nbr] else { continue }
            let t00_avg = 0.5 * (t00_i + T00[nbrLoc])
            let t01_avg = 0.5 * (t01_i + T01[nbrLoc])
            let t10_avg = 0.5 * (t10_i + T10[nbrLoc])
            let t11_avg = 0.5 * (t11_i + T11[nbrLoc])

            let ex = compVX[loc] - compVX[nbrLoc]
            let ey = compVY[loc] - compVY[nbrLoc]

            Bx[loc] += t00_avg * ex + t01_avg * ey
            By[loc] += t10_avg * ex + t11_avg * ey
          }
        }

        for p in compPins {
          if let pLoc = globalToLocal[p.vertexIndex] {
            Bx[pLoc] += wPin * Double(p.target.x)
            By[pLoc] += wPin * Double(p.target.y)
          }
        }

        compVCurX = solveConjugateGradient(A: A, b: Bx, x0: compVCurX)
        compVCurY = solveConjugateGradient(A: A, b: By, x0: compVCurY)
      }

      for p in compPins {
        if let pLoc = globalToLocal[p.vertexIndex] {
          compVCurX[pLoc] = Double(p.target.x)
          compVCurY[pLoc] = Double(p.target.y)
        }
      }

      for (loc, g) in comp.enumerated() {
        vCur[g] = CGPoint(x: compVCurX[loc], y: compVCurY[loc])
      }
    }

    mesh.deformedVertices = vCur
  }

  /// Fast Conjugate Gradient solver for symmetric positive definite systems A * x = b.
  private static func solveConjugateGradient(
    A: [[Double]],
    b: [Double],
    x0: [Double],
    maxIter: Int = 40,
    tol: Double = 1e-5
  ) -> [Double] {
    let n = b.count
    var x = x0
    var r = [Double](repeating: 0, count: n)
    for i in 0..<n {
      var ax = 0.0
      let row = A[i]
      for j in 0..<n { ax += row[j] * x[j] }
      r[i] = b[i] - ax
    }
    var p = r
    var rsOld = 0.0
    for i in 0..<n { rsOld += r[i] * r[i] }
    if rsOld < tol * tol { return x }

    for _ in 0..<maxIter {
      var Ap = [Double](repeating: 0, count: n)
      for i in 0..<n {
        var sum = 0.0
        let row = A[i]
        for j in 0..<n { sum += row[j] * p[j] }
        Ap[i] = sum
      }
      var pAp = 0.0
      for i in 0..<n { pAp += p[i] * Ap[i] }
      if abs(pAp) < 1e-14 { break }
      let alpha = rsOld / pAp
      for i in 0..<n { x[i] += alpha * p[i] }
      for i in 0..<n { r[i] -= alpha * Ap[i] }
      var rsNew = 0.0
      for i in 0..<n { rsNew += r[i] * r[i] }
      if rsNew < tol * tol { break }
      let beta = rsNew / rsOld
      for i in 0..<n { p[i] = r[i] + beta * p[i] }
      rsOld = rsNew
    }
    return x
  }
}

// MARK: - Puppet Rasterizer

public enum PuppetRasterizer {
  /// Rasterize deformed triangles directly into a tightly-bounded UIImage (DD-001).
  public static func rasterize(
    image: UIImage,
    mesh: PuppetMesh,
    pins: [PuppetPin]
  ) -> (image: UIImage, offset: CGPoint) {
    guard let cgImage = image.cgImage, !mesh.deformedVertices.isEmpty, !mesh.triangles.isEmpty else {
      return (image, .zero)
    }

    var minX = Double.infinity, maxX = -Double.infinity
    var minY = Double.infinity, maxY = -Double.infinity
    for pt in mesh.deformedVertices {
      minX = min(minX, Double(pt.x))
      maxX = max(maxX, Double(pt.x))
      minY = min(minY, Double(pt.y))
      maxY = max(maxY, Double(pt.y))
    }

    let outX0 = Int(floor(minX)) - 1
    let outY0 = Int(floor(minY)) - 1
    let outW = max(1, Int(ceil(maxX)) - outX0 + 2)
    let outH = max(1, Int(ceil(maxY)) - outY0 + 2)

    // Compute triangle depth ordering
    var sortedTriangles = Array(mesh.triangles.enumerated())
    if !pins.isEmpty {
      var triangleDepths = [Int](repeating: 0, count: mesh.triangles.count)
      for (tIdx, tri) in mesh.triangles.enumerated() {
        let u0 = mesh.vertices[tri.0], u1 = mesh.vertices[tri.1], u2 = mesh.vertices[tri.2]
        let cx = (u0.x + u1.x + u2.x) / 3.0
        let cy = (u0.y + u1.y + u2.y) / 3.0
        var bestDist = Double.infinity
        var bestDepth = 0
        for p in pins {
          let d = Double(p.rest.x - cx) * Double(p.rest.x - cx) + Double(p.rest.y - cy) * Double(p.rest.y - cy)
          if d < bestDist {
            bestDist = d
            bestDepth = p.depth
          }
        }
        triangleDepths[tIdx] = bestDepth
      }
      sortedTriangles.sort { triangleDepths[$0.offset] < triangleDepths[$1.offset] }
    }

    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let bitmapInfo = CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue
    guard
      let ctx = CGContext(
        data: nil, width: outW, height: outH, bitsPerComponent: 8, bytesPerRow: outW * 4,
        space: colorSpace, bitmapInfo: bitmapInfo)
    else {
      return (image, .zero)
    }

    ctx.interpolationQuality = .high
    ctx.setShouldAntialias(true)

    let vRest = mesh.vertices
    let vDef = mesh.deformedVertices
    let imgW = cgImage.width
    let imgH = cgImage.height

    for (_, (i0, i1, i2)) in sortedTriangles {
      let u0 = vRest[i0], u1 = vRest[i1], u2 = vRest[i2]
      let v0 = vDef[i0], v1 = vDef[i1], v2 = vDef[i2]

      // Rest area check
      let det = Double(u0.x) * Double(u1.y - u2.y) + Double(u1.x) * Double(u2.y - u0.y) + Double(u2.x) * Double(u0.y - u1.y)
      if abs(det) < 1e-6 { continue }

      // Solve 2D affine mapping: (u) -> (v - (outX0, outY0))
      let dv0 = CGPoint(x: v0.x - CGFloat(outX0), y: v0.y - CGFloat(outY0))
      let dv1 = CGPoint(x: v1.x - CGFloat(outX0), y: v1.y - CGFloat(outY0))
      let dv2 = CGPoint(x: v2.x - CGFloat(outX0), y: v2.y - CGFloat(outY0))

      guard let transform = affineTransform(from: (u0, u1, u2), to: (dv0, dv1, dv2)) else { continue }

      ctx.saveGState()
      ctx.beginPath()
      // In Core Graphics context, y is flipped or standard depending on orientation
      ctx.move(to: dv0)
      ctx.addLine(to: dv1)
      ctx.addLine(to: dv2)
      ctx.closePath()
      ctx.clip()

      ctx.concatenate(transform)
      // Draw image right side up
      ctx.draw(cgImage, in: CGRect(x: 0, y: 0, width: imgW, height: imgH))
      ctx.restoreGState()
    }

    guard let warpedCg = ctx.makeImage() else {
      return (image, .zero)
    }

    return (UIImage(cgImage: warpedCg), CGPoint(x: outX0, y: outY0))
  }

  /// Calculates the CGAffineTransform mapping triangle (u0, u1, u2) to (v0, v1, v2).
  private static func affineTransform(
    from src: (CGPoint, CGPoint, CGPoint),
    to dst: (CGPoint, CGPoint, CGPoint)
  ) -> CGAffineTransform? {
    let x0 = Double(src.0.x), y0 = Double(src.0.y)
    let x1 = Double(src.1.x), y1 = Double(src.1.y)
    let x2 = Double(src.2.x), y2 = Double(src.2.y)

    let det = x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1)
    if abs(det) < 1e-9 { return nil }

    let inv00 = (y1 - y2) / det, inv01 = (y2 - y0) / det, inv02 = (y0 - y1) / det
    let inv10 = (x2 - x1) / det, inv11 = (x0 - x2) / det, inv12 = (x1 - x0) / det
    let inv20 = (x1 * y2 - x2 * y1) / det
    let inv21 = (x2 * y0 - x0 * y2) / det
    let inv22 = (x0 * y1 - x1 * y0) / det

    let dx0 = Double(dst.0.x), dx1 = Double(dst.1.x), dx2 = Double(dst.2.x)
    let dy0 = Double(dst.0.y), dy1 = Double(dst.1.y), dy2 = Double(dst.2.y)

    let a = inv00 * dx0 + inv01 * dx1 + inv02 * dx2
    let b = inv00 * dy0 + inv01 * dy1 + inv02 * dy2
    let c = inv10 * dx0 + inv11 * dx1 + inv12 * dx2
    let d = inv10 * dy0 + inv11 * dy1 + inv12 * dy2
    let tx = inv20 * dx0 + inv21 * dx1 + inv22 * dx2
    let ty = inv20 * dy0 + inv21 * dy1 + inv22 * dy2

    return CGAffineTransform(a: a, b: b, c: c, d: d, tx: tx, ty: ty)
  }
}

// SPDX-License-Identifier: Apache-2.0
//
// PuppetWarpTests.swift — Puppet Warp ARAP deformation unit tests (#420).
//

import CoreGraphics
import UIKit
import XCTest

@testable import PhotoslopIPad

final class PuppetWarpTests: XCTestCase {

  private func makeStripeImage(width: Int = 100, height: Int = 100) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let renderer = UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format)
    return renderer.image { ctx in
      UIColor.white.setFill()
      ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
      UIColor.red.setFill()
      ctx.fill(CGRect(x: 45, y: 0, width: 10, height: height))
    }
  }

  private func makeCenteredAlphaSquare(width: Int = 100, height: Int = 100) -> UIImage {
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = false
    let renderer = UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format)
    return renderer.image { ctx in
      UIColor.blue.setFill()
      ctx.fill(CGRect(x: 30, y: 30, width: 40, height: 40))
    }
  }

  func testMeshGenerationCoversAlpha() {
    let img = makeCenteredAlphaSquare(width: 100, height: 100)
    let mesh = PuppetMesh.generate(from: img, spacing: 10)

    XCTAssertFalse(mesh.vertices.isEmpty)
    XCTAssertFalse(mesh.triangles.isEmpty)

    // Vertices should only exist in the dilated neighbourhood of [30, 70]
    let minX = mesh.vertices.map { $0.x }.min() ?? 0
    let maxX = mesh.vertices.map { $0.x }.max() ?? 0
    let minY = mesh.vertices.map { $0.y }.min() ?? 0
    let maxY = mesh.vertices.map { $0.y }.max() ?? 0

    XCTAssertGreaterThanOrEqual(minX, 20)
    XCTAssertLessThanOrEqual(maxX, 80)
    XCTAssertGreaterThanOrEqual(minY, 20)
    XCTAssertLessThanOrEqual(maxY, 80)
  }

  func testARAPSolverAnchorPreservation() {
    let img = makeStripeImage(width: 100, height: 100)
    var mesh = PuppetMesh.generate(from: img, spacing: 15)

    var pins = [
      PuppetPin(rest: CGPoint(x: 50, y: 10), target: CGPoint(x: 50, y: 10)),   // Top anchor
      PuppetPin(rest: CGPoint(x: 50, y: 90), target: CGPoint(x: 50, y: 90)),   // Bottom anchor
      PuppetPin(rest: CGPoint(x: 50, y: 50), target: CGPoint(x: 75, y: 50)),   // Middle pulled right
    ]

    ARAPSolver.solve(mesh: &mesh, pins: &pins, mode: .normal)

    // Anchors must remain within subpixel tolerance of rest
    let topVertex = mesh.deformedVertices[pins[0].vertexIndex]
    let botVertex = mesh.deformedVertices[pins[1].vertexIndex]
    let midVertex = mesh.deformedVertices[pins[2].vertexIndex]

    XCTAssertEqual(Double(topVertex.x), 50.0, accuracy: 0.1)
    XCTAssertEqual(Double(topVertex.y), 10.0, accuracy: 0.1)
    XCTAssertEqual(Double(botVertex.x), 50.0, accuracy: 0.1)
    XCTAssertEqual(Double(botVertex.y), 90.0, accuracy: 0.1)
    XCTAssertEqual(Double(midVertex.x), 75.0, accuracy: 0.1)
    XCTAssertEqual(Double(midVertex.y), 50.0, accuracy: 0.1)
  }

  func testARAPModesRigidNormalDistort() {
    let img = makeStripeImage(width: 100, height: 100)
    var meshRigid = PuppetMesh.generate(from: img, spacing: 15)
    var meshDistort = PuppetMesh.generate(from: img, spacing: 15)

    var pinsRigid = [
      PuppetPin(rest: CGPoint(x: 20, y: 50), target: CGPoint(x: 20, y: 50)),
      PuppetPin(rest: CGPoint(x: 80, y: 50), target: CGPoint(x: 110, y: 50)),
    ]
    var pinsDistort = [
      PuppetPin(rest: CGPoint(x: 20, y: 50), target: CGPoint(x: 20, y: 50)),
      PuppetPin(rest: CGPoint(x: 80, y: 50), target: CGPoint(x: 110, y: 50)),
    ]

    ARAPSolver.solve(mesh: &meshRigid, pins: &pinsRigid, mode: .rigid)
    ARAPSolver.solve(mesh: &meshDistort, pins: &pinsDistort, mode: .distort)

    let maxRigidX = meshRigid.deformedVertices.map { $0.x }.max() ?? 0
    let maxDistortX = meshDistort.deformedVertices.map { $0.x }.max() ?? 0

    XCTAssertGreaterThan(maxRigidX, 100)
    XCTAssertGreaterThan(maxDistortX, 100)
  }

  func testPinRotationEffect() {
    let img = makeStripeImage(width: 100, height: 100)
    var mesh = PuppetMesh.generate(from: img, spacing: 15)

    var pins = [
      PuppetPin(rest: CGPoint(x: 20, y: 50), target: CGPoint(x: 20, y: 50)),
      PuppetPin(rest: CGPoint(x: 80, y: 50), target: CGPoint(x: 80, y: 50), rotation: 90.0),
    ]

    ARAPSolver.solve(mesh: &mesh, pins: &pins, mode: .normal)

    // Rotating pin 1 by 90 degrees should introduce significant y-displacement in neighbouring vertices
    var maxYShift = 0.0
    for (i, vRest) in mesh.vertices.enumerated() {
      let dx = vRest.x - 80.0
      let dy = vRest.y - 50.0
      let dist = sqrt(dx * dx + dy * dy)
      if dist > 5.0 && dist < 25.0 {
        let vDef = mesh.deformedVertices[i]
        maxYShift = max(maxYShift, Double(abs(vDef.y - vRest.y)))
      }
    }
    XCTAssertGreaterThan(maxYShift, 1.0)
  }

  func testRasterizeDeformedMesh() {
    let img = makeStripeImage(width: 100, height: 100)
    var mesh = PuppetMesh.generate(from: img, spacing: 15)

    var pins = [
      PuppetPin(rest: CGPoint(x: 50, y: 10), target: CGPoint(x: 50, y: 10)),
      PuppetPin(rest: CGPoint(x: 50, y: 90), target: CGPoint(x: 50, y: 90)),
      PuppetPin(rest: CGPoint(x: 50, y: 50), target: CGPoint(x: 75, y: 50)),
    ]

    ARAPSolver.solve(mesh: &mesh, pins: &pins, mode: .normal)
    let outcome = PuppetRasterizer.rasterize(image: img, mesh: mesh, pins: pins)

    XCTAssertGreaterThan(outcome.image.size.width, 0)
    XCTAssertGreaterThan(outcome.image.size.height, 0)
  }
}

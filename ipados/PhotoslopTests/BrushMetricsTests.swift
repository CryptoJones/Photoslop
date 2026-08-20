// SPDX-License-Identifier: Apache-2.0
import UIKit
import XCTest

@testable import PhotoslopIPad

/// Brush width in proportion to the canvas (#314).
final class BrushMetricsTests: XCTestCase {

  private let standard = EditorStore.defaultCanvasSize  // 2048 x 1536
  private let uhd4K = CGSize(width: 3840, height: 2160)
  private let small = CGSize(width: 512, height: 512)

  // MARK: - The old constants must survive

  /// The formula is the old hardcoded 8 generalised, so a default document
  /// behaves exactly as it always did and only other canvases change.
  func testTheDefaultCanvasStillGetsTheWidthItAlwaysHad() {
    XCTAssertEqual(BrushMetrics.defaultWidth(for: standard), 8)
  }

  /// Likewise the old ceiling of 80.
  func testTheDefaultCanvasKeepsItsOldCeiling() {
    XCTAssertEqual(BrushMetrics.maximumWidth(for: standard), 80)
  }

  // MARK: - Scaling

  /// The reported bug: a bigger canvas needs a bigger brush for the same
  /// apparent weight, and used to get the same 8 px hairline.
  func testABiggerCanvasGetsAProportionallyBiggerDefault() {
    let bigger = BrushMetrics.defaultWidth(for: uhd4K)
    XCTAssertGreaterThan(bigger, BrushMetrics.defaultWidth(for: standard))
    XCTAssertEqual(bigger, 11, "2160 * 0.005 = 10.8")
  }

  func testABiggerCanvasAlsoRaisesTheCeiling() {
    XCTAssertGreaterThan(
      BrushMetrics.maximumWidth(for: uhd4K), BrushMetrics.maximumWidth(for: standard))
  }

  /// A small canvas must never be offered a *narrower* range than the app
  /// shipped with, or a fix for large canvases becomes a regression for small.
  func testASmallCanvasNeverLosesRange() {
    XCTAssertEqual(BrushMetrics.maximumWidth(for: small), BrushMetrics.smallestMaximum)
    XCTAssertGreaterThanOrEqual(BrushMetrics.defaultWidth(for: small), BrushMetrics.minimumWidth)
  }

  // MARK: - Carrying a width across a resize

  /// CryptoJones chose scaling over leaving it alone: a resize should keep the
  /// brush looking the same size against the picture.
  func testAWidthScalesWithTheCanvasOnResize() {
    let carried = BrushMetrics.rescaled(20, from: standard, to: uhd4K)
    // 1536 -> 2160 is 1.40625x; 20 * 1.40625 = 28.125
    XCTAssertEqual(carried, 28, accuracy: 1)
  }

  func testScalingDownAlsoWorks() {
    let carried = BrushMetrics.rescaled(80, from: uhd4K, to: standard)
    // 2160 -> 1536 is 0.711x; 80 * 0.711 = 56.9
    XCTAssertEqual(carried, 57, accuracy: 1)
  }

  /// A carried width must land somewhere the slider can actually represent,
  /// or the control and the value disagree.
  func testACarriedWidthStaysInsideTheNewRange() {
    let carried = BrushMetrics.rescaled(4000, from: standard, to: small)
    XCTAssertLessThanOrEqual(carried, BrushMetrics.maximumWidth(for: small))
    XCTAssertGreaterThanOrEqual(carried, BrushMetrics.minimumWidth)
  }

  func testAnUnchangedCanvasLeavesTheWidthAlone() {
    XCTAssertEqual(BrushMetrics.rescaled(37, from: standard, to: standard), 37)
  }

  // MARK: - Degenerate input

  func testAZeroCanvasDoesNotProduceNonsense() {
    XCTAssertEqual(BrushMetrics.defaultWidth(for: .zero), 8)
    XCTAssertEqual(BrushMetrics.maximumWidth(for: .zero), BrushMetrics.smallestMaximum)
    XCTAssertEqual(BrushMetrics.rescaled(12, from: .zero, to: standard), 12)
    XCTAssertEqual(BrushMetrics.rescaled(12, from: standard, to: .zero), 12)
  }

  // MARK: - The symptom, in numbers

  /// What the reporter actually hit: at fit zoom on a phone the old fixed
  /// default was around a pixel and a half wide on screen.
  func testTheOldFixedDefaultWasSubPixelOnAPhoneAtFitZoom() {
    let phoneWidthPoints = 390.0
    let fitZoom = phoneWidthPoints / Double(standard.width)  // ~0.19
    XCTAssertLessThan(8 * fitZoom, 2, "8 px really was about a pixel and a half")

    // The canvas-derived default is no wider here — that is the point, the
    // default canvas is unchanged — so the fix for this size is the ceiling
    // and the resize behaviour, not the starting value.
    XCTAssertEqual(BrushMetrics.defaultWidth(for: standard), 8)
  }
}

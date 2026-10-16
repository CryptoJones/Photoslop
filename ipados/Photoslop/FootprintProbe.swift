// SPDX-License-Identifier: Apache-2.0
import Darwin
import Foundation
import os

/// Prints the process's memory footprint every two seconds when launched with
/// `-PhotoslopLogFootprint`.
///
/// For measuring on a physical device from the command line, where Instruments
/// cannot always attach:
///
///     xcrun devicectl device process launch --console --device <udid> \
///       io.ronin48.photoslop.ipad -- -PhotoslopLogFootprint
///
/// The `--` matters: without it `devicectl` reads the flag as its own.
///
/// `phys_footprint` is the number jetsam judges the process by — the same one
/// Xcode's memory gauge shows — so the lines read `footprint=312MB` and can be
/// compared directly against the warning threshold. `available` is what
/// `EditorStore.availableMemoryBytes()` consults before it allows another
/// canvas-sized layer. Off unless asked for; nothing here runs in a normal
/// launch.
enum FootprintProbe {
  private static let log = Logger(subsystem: "io.ronin48.photoslop", category: "footprint")
  private static var timer: Timer?
  private static var peak = 0

  static func startIfAskedTo() {
    guard ProcessInfo.processInfo.arguments.contains("-PhotoslopLogFootprint") else { return }
    timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in sample() }
    sample()
  }

  static func footprintBytes() -> Int {
    var info = task_vm_info_data_t()
    var count = mach_msg_type_number_t(
      MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
    let result = withUnsafeMutablePointer(to: &info) {
      $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
        task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
      }
    }
    return result == KERN_SUCCESS ? Int(info.phys_footprint) : -1
  }

  private static func sample() {
    let footprint = footprintBytes()
    peak = max(peak, footprint)
    let available = Int(os_proc_available_memory())
    let mb = 1_048_576
    let line =
      "footprint=\(footprint / mb)MB peak=\(peak / mb)MB available=\(available / mb)MB"
    print("[footprint] \(line)")
    log.notice("\(line, privacy: .public)")
  }
}

// SPDX-License-Identifier: Apache-2.0
import Photos
import UIKit

/// Writes an exported image into the Photos library.
///
/// Export used to reach only the Files hierarchy, because `fileExporter`
/// presents a document picker. On a phone that is the wrong destination for a
/// finished picture: Photos is what the camera roll, the share sheet and every
/// other app mean by "my photos", and getting there meant saving to Files and
/// importing by hand.
///
/// Add-only authorisation, deliberately. Saving an export needs permission to
/// *add* an asset and nothing else, and asking for the full library would be
/// asking to read every photo the user owns to accomplish a write.
enum PhotoLibrarySaver {
  enum SaveError: LocalizedError {
    case notAuthorised
    case failed(String)

    var errorDescription: String? {
      switch self {
      case .notAuthorised:
        "Photoslop is not allowed to add to your photo library. "
          + "Turn on Settings › Privacy & Security › Photos › Photoslop › Add Photos Only."
      case .failed(let reason):
        reason
      }
    }
  }

  /// Ask for add-only access, requesting it the first time and reporting the
  /// answer thereafter.
  ///
  /// `.limited` counts as permission here: it restricts what the app may *read*,
  /// and adding is unaffected.
  private static func authorise() async -> Bool {
    let current = PHPhotoLibrary.authorizationStatus(for: .addOnly)
    switch current {
    case .authorized, .limited:
      return true
    case .notDetermined:
      let granted = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
      return granted == .authorized || granted == .limited
    case .denied, .restricted:
      return false
    @unknown default:
      return false
    }
  }

  /// Save already-encoded image bytes as a new asset.
  ///
  /// The bytes are the same ones the Files exporter writes — `exportImage` has
  /// already rendered and encoded them — so the two destinations cannot drift
  /// into producing different pictures.
  static func save(_ data: Data, format: ExportFormat) async throws {
    guard await authorise() else { throw SaveError.notAuthorised }

    do {
      try await PHPhotoLibrary.shared().performChanges {
        let request = PHAssetCreationRequest.forAsset()
        let options = PHAssetResourceCreationOptions()
        options.uniformTypeIdentifier = format.utType.identifier
        request.addResource(with: .photo, data: data, options: options)
      }
    } catch {
      throw SaveError.failed(
        "The picture could not be added to your photo library: \(error.localizedDescription)")
    }
  }
}

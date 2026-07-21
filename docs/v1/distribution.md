# Distribution and release checklist

Portable macOS and Windows builds sync `uv.lock` with the exact `build` extra,
generate dependency notices, a CycloneDX SBOM, and a build-identity inventory,
then exercise the packaged Qt application with a PNG export/import round trip.
Each archive has a SHA-256 manifest. Pull requests affecting runtime or build
inputs and a weekly schedule execute both builders.

Tagged portable jobs are normally fail-closed: macOS requires Developer ID
signing plus Apple notarization credentials; Windows requires an Authenticode
certificate. Version 1.30.0 has two narrow, maintainer-approved exceptions. Its
macOS archive is Developer ID signed but not notarized and includes
`SIGNED-NOT-NOTARIZED` in its filename. Its Windows archive is not Authenticode
signed and includes `UNSIGNED` in its filename. Operating-system security
warnings may therefore still appear. Checksums, SBOMs, build identities, and
GitHub provenance attestations remain present, but none substitutes for missing
notarization or a platform signature. Later tagged releases remain fail-closed.
The unsigned iPad device bundle is validation-only and is not uploaded publicly.

The repository `THIRD_PARTY_NOTICES.md` records source-distributed assets. Each
portable build generates an expanded notice file from the exact locked build
environment and includes every discovered package license file; that generated
file, not the source-only seed, is the artifact compliance inventory.

## Release candidate record

Before creating a tag, the release owner records:

- matching package/runtime/iPad/docs/tag version and iPad build number;
- green Python 3.10/latest, Windows, macOS, Linux, wheel/sdist install, portable
  package smoke, security, critical coverage, and full-scale performance jobs;
- SHA-256 manifests, SBOMs, build identities, dependency inventory hashes, and
  GitHub provenance attestations;
- verified codesign/notarization and Authenticode output, or for the documented
  v1.30.0 exceptions, verified macOS `SIGNED-NOT-NOTARIZED` and Windows
  `UNSIGNED` filenames plus release warnings;
- a compliance-owner review of generated third-party notices and every bundled
  native codec/backend;
- the manual accessibility/platform matrix, with unexecuted rows marked
  unverified rather than inferred from offscreen CI;
- all warnings, dependency vulnerabilities, and Bandit medium/high findings at
  zero or linked to a narrow reviewed suppression.

Signing credentials stay in the repository secret store. They are never
written to source artifacts; the Windows temporary certificate is removed by a
`finally` block after signing.

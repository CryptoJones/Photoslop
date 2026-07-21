# Distribution and release checklist

Portable macOS and Windows builds sync `uv.lock` with the exact `build` extra,
generate dependency notices, a CycloneDX SBOM, and a build-identity inventory,
then exercise the packaged Qt application with a PNG export/import round trip.
Each archive has a SHA-256 manifest. Pull requests affecting runtime or build
inputs and a weekly schedule execute both builders.

Tagged portable jobs are normally fail-closed: macOS requires Developer ID
signing plus Apple notarization credentials; Windows requires an Authenticode
certificate. Version 1.30.0 is a narrow, maintainer-approved exception that
publishes desktop archives with `UNSIGNED` in each filename. Those archives are
not code-signed, the macOS app is not notarized, and operating-system security
warnings are expected. Checksums, SBOMs, build identities, and GitHub provenance
attestations remain present, but none is a substitute for a platform signature.
Later tagged releases remain fail-closed. The unsigned iPad device bundle is
validation-only and is not uploaded to a public release.

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
  v1.30.0 exception, verified `UNSIGNED` filenames and release warnings;
- a compliance-owner review of generated third-party notices and every bundled
  native codec/backend;
- the manual accessibility/platform matrix, with unexecuted rows marked
  unverified rather than inferred from offscreen CI;
- all warnings, dependency vulnerabilities, and Bandit medium/high findings at
  zero or linked to a narrow reviewed suppression.

Signing credentials stay in the repository secret store. They are never
written to source artifacts; the Windows temporary certificate is removed by a
`finally` block after signing.

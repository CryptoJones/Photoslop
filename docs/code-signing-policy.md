# Code signing policy

Free code signing on Windows is provided by [SignPath.io](https://signpath.io),
with a certificate by the [SignPath Foundation](https://signpath.org).

## What gets signed

Code signing is strictly limited to **official Photoslop releases**: the
Windows portable bundle built by the
[`portable` GitHub Actions workflow](../.github/workflows/portable.yml) from a
version tag (`v*`) on the
[CryptoJones/Photoslop](https://github.com/CryptoJones/Photoslop) repository.
Builds from forks, pull requests, or local machines are never signed.

## Who can trigger a signed build

Only the project maintainer, [@CryptoJones](https://github.com/CryptoJones),
can push the version tags that produce signed release artifacts. Reviewers and
approvers of the signing request are the same maintainer team.

## Integrity

Every release artifact ships with a `.sha256` checksum and a
`BUILD-IDENTITY.json` manifest recording the exact commit, dependency set, and
build platform, plus a CycloneDX SBOM (`.cdx.json`). The signed binary is built
from the public source at the tagged commit — nothing proprietary is added.

## Privacy

Photoslop does not collect telemetry and does not transfer any information to
third parties. The application makes no network connections at all except to an
AI model backend endpoint the user explicitly configures (off by default).

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*

#!/usr/bin/env bash
# Import the release-only Apple Distribution identity into an ephemeral CI keychain.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP must be set by GitHub Actions}"
: "${GITHUB_ENV:?GITHUB_ENV must be set by GitHub Actions}"
: "${IOS_DISTRIBUTION_CERTIFICATE_P12:?IOS_DISTRIBUTION_CERTIFICATE_P12 secret is required}"
: "${IOS_DISTRIBUTION_CERTIFICATE_PASSWORD:?IOS_DISTRIBUTION_CERTIFICATE_PASSWORD secret is required}"
: "${PHOTOSLOP_IOS_TEAM_ID:?PHOTOSLOP_IOS_TEAM_ID must be set}"

KEYCHAIN_PATH="$RUNNER_TEMP/photoslop-ios-signing.keychain-db"
CERTIFICATE_PATH="$RUNNER_TEMP/photoslop-ios-signing.p12"
KEYCHAIN_PASSWORD="$(uuidgen)-$(uuidgen)"

trap 'rm -f "$CERTIFICATE_PATH"' EXIT
printf '%s' "$IOS_DISTRIBUTION_CERTIFICATE_P12" \
  | openssl base64 -d -A -out "$CERTIFICATE_PATH"

security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security import "$CERTIFICATE_PATH" -k "$KEYCHAIN_PATH" \
  -P "$IOS_DISTRIBUTION_CERTIFICATE_PASSWORD" -A -t cert -f pkcs12
security set-key-partition-list -S apple-tool:,apple: -s \
  -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security list-keychains -d user -s "$KEYCHAIN_PATH"
security default-keychain -d user -s "$KEYCHAIN_PATH"

IDENTITY="$(security find-identity -v -p codesigning "$KEYCHAIN_PATH" \
  | sed -n 's/.*"\(Apple Distribution:[^"]*\)".*/\1/p')"
if [[ -z "$IDENTITY" || "$IDENTITY" != *"($PHOTOSLOP_IOS_TEAM_ID)" ]]; then
  echo "Expected Apple Distribution identity for team $PHOTOSLOP_IOS_TEAM_ID was not imported" >&2
  exit 1
fi

echo "PHOTOSLOP_IOS_SIGN_IDENTITY=$IDENTITY" >> "$GITHUB_ENV"
echo "Imported the expected Apple Distribution identity."

#!/usr/bin/env bash
# Archive, export, and upload the iPad app to App Store Connect for TestFlight.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

ROOT="$(cd -L "$(dirname "$0")/.." && pwd -L)"
IPADOS_DIR="$ROOT/ipados"
BUILD_DIR="$IPADOS_DIR/build"
DERIVED_DATA="$BUILD_DIR/TestFlightDerivedData"
ARCHIVE_PATH="$BUILD_DIR/Photoslop.xcarchive"
EXPORT_DIR="$BUILD_DIR/TestFlightExport"
EXPORT_OPTIONS="$BUILD_DIR/ExportOptions.plist"
DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
export DEVELOPER_DIR

# xcodebuild packages the .ipa with `/usr/bin/rsync -8aPhhE`, where -E means
# --extended-attributes. rsync starts its server half by resolving `rsync` on
# PATH, so a newer rsync earlier in PATH (Homebrew ships 3.x, where -E is
# --executability) answers instead and aborts with "unknown option", which
# xcodebuild surfaces only as "Copy failed". Keep the system openrsync first so
# both halves agree.
PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PATH

: "${PHOTOSLOP_IOS_TEAM_ID:?PHOTOSLOP_IOS_TEAM_ID must be set}"
: "${APP_STORE_CONNECT_KEY_ID:?APP_STORE_CONNECT_KEY_ID secret is required}"
: "${APP_STORE_CONNECT_ISSUER_ID:?APP_STORE_CONNECT_ISSUER_ID secret is required}"
: "${APP_STORE_CONNECT_PRIVATE_KEY:?APP_STORE_CONNECT_PRIVATE_KEY secret is required}"

XCODEGEN_BIN="${XCODEGEN:-}"
if [[ -z "$XCODEGEN_BIN" ]]; then
  XCODEGEN_BIN="$(command -v xcodegen || true)"
fi
if [[ -z "$XCODEGEN_BIN" || ! -x "$XCODEGEN_BIN" ]]; then
  echo "xcodegen is required (brew install xcodegen)." >&2
  exit 1
fi

if [[ ! -d "$DEVELOPER_DIR" ]]; then
  echo "Xcode is required. DEVELOPER_DIR does not exist: $DEVELOPER_DIR" >&2
  exit 1
fi

# altool and xcodebuild both locate the signing key by well-known path.
KEY_DIR="$HOME/.appstoreconnect/private_keys"
KEY_PATH="$KEY_DIR/AuthKey_${APP_STORE_CONNECT_KEY_ID}.p8"
mkdir -p "$KEY_DIR"
trap 'rm -f "$KEY_PATH"' EXIT
printf '%s' "$APP_STORE_CONNECT_PRIVATE_KEY" \
  | openssl base64 -d -A -out "$KEY_PATH"
chmod 600 "$KEY_PATH"

cd "$IPADOS_DIR"
"$XCODEGEN_BIN" generate
rm -rf "$DERIVED_DATA" "$ARCHIVE_PATH" "$EXPORT_DIR"

# Deliberately NO CODE_SIGN_IDENTITY override here. Pinning the archive to
# the imported Apple Distribution identity was tried for #255 and Xcode
# refused to archive at all: an explicit identity under
# CODE_SIGN_STYLE=Automatic is "conflicting provisioning settings" (v2.10.0,
# exit 65, both the app and the thumbnail extension). So automatic signing
# is left alone — it mints a throwaway "Created via API" development
# certificate per release, and the workflow's post-upload step revokes them,
# which is the half of #255 that actually holds the account under its
# 15-certificate limit.
xcodebuild \
  -project Photoslop-iPadOS.xcodeproj \
  -scheme PhotoslopIPad \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "$DERIVED_DATA" \
  -archivePath "$ARCHIVE_PATH" \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$KEY_PATH" \
  -authenticationKeyID "$APP_STORE_CONNECT_KEY_ID" \
  -authenticationKeyIssuerID "$APP_STORE_CONNECT_ISSUER_ID" \
  DEVELOPMENT_TEAM="$PHOTOSLOP_IOS_TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  archive

cat > "$EXPORT_OPTIONS" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key>
  <string>app-store-connect</string>
  <key>teamID</key>
  <string>$PHOTOSLOP_IOS_TEAM_ID</string>
  <key>signingStyle</key>
  <string>automatic</string>
  <key>uploadSymbols</key>
  <true/>
  <key>destination</key>
  <string>export</string>
</dict>
</plist>
PLIST

xcodebuild \
  -exportArchive \
  -archivePath "$ARCHIVE_PATH" \
  -exportPath "$EXPORT_DIR" \
  -exportOptionsPlist "$EXPORT_OPTIONS" \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$KEY_PATH" \
  -authenticationKeyID "$APP_STORE_CONNECT_KEY_ID" \
  -authenticationKeyIssuerID "$APP_STORE_CONNECT_ISSUER_ID"

IPA="$(find "$EXPORT_DIR" -maxdepth 1 -name '*.ipa' -print -quit)"
if [[ -z "$IPA" ]]; then
  echo "Expected a signed .ipa in $EXPORT_DIR" >&2
  exit 1
fi

xcrun altool --validate-app \
  --file "$IPA" \
  --type ios \
  --apiKey "$APP_STORE_CONNECT_KEY_ID" \
  --apiIssuer "$APP_STORE_CONNECT_ISSUER_ID"

xcrun altool --upload-app \
  --file "$IPA" \
  --type ios \
  --apiKey "$APP_STORE_CONNECT_KEY_ID" \
  --apiIssuer "$APP_STORE_CONNECT_ISSUER_ID"

echo "$IPA"

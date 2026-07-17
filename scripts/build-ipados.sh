#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -L "$(dirname "$0")/.." && pwd -L)"
IPADOS_DIR="$ROOT/ipados"
DERIVED_DATA="$IPADOS_DIR/build/DerivedData"
DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
export DEVELOPER_DIR

if ! command -v xcodegen >/dev/null 2>&1; then
  echo "xcodegen is required (brew install xcodegen)." >&2
  exit 1
fi

if [[ ! -d "$DEVELOPER_DIR" ]]; then
  echo "Xcode is required. DEVELOPER_DIR does not exist: $DEVELOPER_DIR" >&2
  exit 1
fi

cd "$IPADOS_DIR"
xcodegen generate
rm -rf "$DERIVED_DATA"
xcodebuild \
  -project Photoslop-iPadOS.xcodeproj \
  -scheme PhotoslopIPad \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "$DERIVED_DATA" \
  CODE_SIGNING_ALLOWED=NO \
  build

APP="$DERIVED_DATA/Build/Products/Release-iphoneos/Photoslop.app"
if [[ ! -d "$APP" ]]; then
  echo "Expected app bundle was not produced: $APP" >&2
  exit 1
fi

mkdir -p "$IPADOS_DIR/dist"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$IPADOS_DIR/dist/Photoslop-iPadOS-unsigned.zip"
echo "$IPADOS_DIR/dist/Photoslop-iPadOS-unsigned.zip"

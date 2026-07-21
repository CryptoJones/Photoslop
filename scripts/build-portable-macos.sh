#!/usr/bin/env bash
# Photoslop — portable macOS build.
#
# Produces a self-contained "Photoslop.app" via PyInstaller: bundled Python
# interpreter + PySide6/Qt runtime + all dependencies. Unlike
# install-macos.sh (a thin launcher shortcut), this bundle runs standalone —
# copy it anywhere (a thumbdrive, another Mac) with no repo, no `uv`, no
# network required.
#
# Usage:
#   ./scripts/build-portable-macos.sh
#
# Output: dist/portable-macos/Photoslop.app (+ a zip alongside it)
#
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' photoslop/__about__.py | head -1)"
VERSION="${VERSION:-0.0.0}"

OUT_DIR="$ROOT/dist/portable-macos"
rm -rf "$OUT_DIR" "$ROOT/build/portable-macos"

if ! command -v uv >/dev/null 2>&1; then
  echo "build-portable-macos.sh: 'uv' not found — install it from https://astral.sh/uv" >&2
  exit 1
fi

echo "Syncing locked dependencies (core + formats/raw/build)..."
uv sync --extra formats --extra raw --extra build --locked

METADATA_DIR="$ROOT/build/portable-macos-metadata"
uv run python scripts/generate-bundle-metadata.py --output-dir "$METADATA_DIR"

echo "Building Photoslop.app (v$VERSION) with PyInstaller..."
uv run pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name Photoslop \
  --distpath "$OUT_DIR" \
  --workpath "$ROOT/build/portable-macos" \
  --specpath "$ROOT/build/portable-macos" \
  --osx-bundle-identifier net.thenetwerk.photoslop \
  --add-data "$ROOT/LICENSE:." \
  --add-data "$METADATA_DIR/THIRD_PARTY_NOTICES.md:." \
  --add-data "$METADATA_DIR/photoslop.cdx.json:." \
  --add-data "$METADATA_DIR/BUILD-IDENTITY.json:." \
  photoslop/app.py

APP="$OUT_DIR/Photoslop.app"
if [[ ! -d "$APP" ]]; then
  echo "build-portable-macos.sh: expected app bundle was not produced: $APP" >&2
  exit 1
fi

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist" || true
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$APP/Contents/Info.plist" || true

echo "Running packaged Qt/codec/import/export smoke test..."
QT_QPA_PLATFORM=offscreen "$APP/Contents/MacOS/Photoslop" --portable-smoke

if [[ -n "${PHOTOSLOP_MACOS_SIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp \
    --sign "$PHOTOSLOP_MACOS_SIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
elif [[ "${PHOTOSLOP_REQUIRE_SIGNING:-0}" == "1" ]]; then
  echo "Tagged portable release requires PHOTOSLOP_MACOS_SIGN_IDENTITY" >&2
  exit 1
else
  echo "Signing identity absent; producing an explicitly unsigned validation artifact."
fi

ZIP="$OUT_DIR/Photoslop-macOS-portable-v$VERSION.zip"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

if [[ -n "${PHOTOSLOP_APPLE_ID:-}" && -n "${PHOTOSLOP_APPLE_TEAM_ID:-}" \
      && -n "${PHOTOSLOP_APPLE_APP_PASSWORD:-}" ]]; then
  xcrun notarytool submit "$ZIP" --wait \
    --apple-id "$PHOTOSLOP_APPLE_ID" \
    --team-id "$PHOTOSLOP_APPLE_TEAM_ID" \
    --password "$PHOTOSLOP_APPLE_APP_PASSWORD"
  xcrun stapler staple "$APP"
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
elif [[ "${PHOTOSLOP_REQUIRE_SIGNING:-0}" == "1" ]]; then
  echo "Tagged portable release requires Apple notarization credentials" >&2
  exit 1
fi

shasum -a 256 "$ZIP" > "$ZIP.sha256"
cp "$METADATA_DIR/photoslop.cdx.json" "$OUT_DIR/"
cp "$METADATA_DIR/BUILD-IDENTITY.json" "$OUT_DIR/"
cp "$METADATA_DIR/THIRD_PARTY_NOTICES.md" "$OUT_DIR/"

echo "Portable macOS build ready:"
echo "  App: $APP"
echo "  Zip: $ZIP"
echo "  Checksum: $ZIP.sha256"

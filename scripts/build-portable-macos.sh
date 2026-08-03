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
QUALIFIER="${PHOTOSLOP_ARTIFACT_QUALIFIER:-}"
if [[ -n "$QUALIFIER" && ! "$QUALIFIER" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "build-portable-macos.sh: invalid artifact qualifier: $QUALIFIER" >&2
  exit 1
fi
QUALIFIER_SUFFIX="${QUALIFIER:+-$QUALIFIER}"

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

# The bundle ships one executable, so the console entry points pyproject.toml
# declares (photoslop-cli, photoslop-mcp) reach it through app.py's --cli/--mcp
# selector. They live under Resources rather than MacOS on purpose: a
# non-Mach-O file in Contents/MacOS is nested code as far as codesign is
# concerned, while Resources is sealed without special handling.
BIN_DIR="$APP/Contents/Resources/bin"
mkdir -p "$BIN_DIR"
for entry in cli mcp; do
  cat > "$BIN_DIR/photoslop-$entry" <<EOF
#!/bin/sh
# Photoslop portable — $entry entry point.
exec "\$(cd "\$(dirname "\$0")/../../MacOS" && pwd)/Photoslop" --$entry "\$@"
EOF
  chmod +x "$BIN_DIR/photoslop-$entry"
done

echo "Running packaged Qt/codec/import/export smoke test..."
QT_QPA_PLATFORM=offscreen "$APP/Contents/MacOS/Photoslop" --portable-smoke

echo "Verifying the packaged CLI and MCP entry points..."
SMOKE_DIR="$(mktemp -d)"
NOTARY_DIR=""
trap 'rm -rf "$SMOKE_DIR" ${NOTARY_DIR:+"$NOTARY_DIR"}' EXIT
QT_QPA_PLATFORM=offscreen "$BIN_DIR/photoslop-cli" \
  --new 8x8 --output "$SMOKE_DIR/cli.png"
if [[ ! -s "$SMOKE_DIR/cli.png" ]]; then
  echo "build-portable-macos.sh: packaged photoslop-cli produced no output" >&2
  exit 1
fi
QT_QPA_PLATFORM=offscreen "$BIN_DIR/photoslop-mcp" --help >/dev/null

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

ZIP="$OUT_DIR/Photoslop-macOS-portable${QUALIFIER_SUFFIX}-v$VERSION.zip"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

# Notarization accepts either an App Store Connect API key or an Apple ID with
# an app-specific password. The API key is preferred: it carries no interactive
# account, and the same key already drives the iPadOS TestFlight upload. Either
# way the credential must belong to the team that owns the Developer ID
# certificate, or the notary service rejects the submission.
NOTARIZED=0
if [[ -n "${NOTARY_KEY_ID:-}" && -n "${NOTARY_ISSUER_ID:-}" \
      && -n "${NOTARY_PRIVATE_KEY:-}" ]]; then
  NOTARY_DIR="$(mktemp -d)"
  NOTARY_KEY_PATH="$NOTARY_DIR/AuthKey_${NOTARY_KEY_ID}.p8"
  printf '%s' "$NOTARY_PRIVATE_KEY" \
    | openssl base64 -d -A -out "$NOTARY_KEY_PATH"
  chmod 600 "$NOTARY_KEY_PATH"
  xcrun notarytool submit "$ZIP" --wait \
    --key "$NOTARY_KEY_PATH" \
    --key-id "$NOTARY_KEY_ID" \
    --issuer "$NOTARY_ISSUER_ID"
  NOTARIZED=1
elif [[ -n "${PHOTOSLOP_APPLE_ID:-}" && -n "${PHOTOSLOP_APPLE_TEAM_ID:-}" \
        && -n "${PHOTOSLOP_APPLE_APP_PASSWORD:-}" ]]; then
  xcrun notarytool submit "$ZIP" --wait \
    --apple-id "$PHOTOSLOP_APPLE_ID" \
    --team-id "$PHOTOSLOP_APPLE_TEAM_ID" \
    --password "$PHOTOSLOP_APPLE_APP_PASSWORD"
  NOTARIZED=1
fi

if [[ "$NOTARIZED" == "1" ]]; then
  # Staple the ticket into the bundle so first launch works offline, then
  # rebuild the archive so the shipped zip contains the stapled app.
  xcrun stapler staple "$APP"
  xcrun stapler validate "$APP"
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
elif [[ "${PHOTOSLOP_REQUIRE_NOTARIZATION:-${PHOTOSLOP_REQUIRE_SIGNING:-0}}" == "1" ]]; then
  echo "Tagged portable release requires Apple notarization credentials" >&2
  exit 1
else
  echo "Notarization credentials absent; archive will not be notarized."
fi

(
  cd "$OUT_DIR"
  shasum -a 256 "$(basename "$ZIP")" > "$(basename "$ZIP").sha256"
)
cp "$METADATA_DIR/photoslop.cdx.json" "$OUT_DIR/"
cp "$METADATA_DIR/BUILD-IDENTITY.json" "$OUT_DIR/"
cp "$METADATA_DIR/THIRD_PARTY_NOTICES.md" "$OUT_DIR/"

echo "Portable macOS build ready:"
echo "  App: $APP"
echo "  CLI: $BIN_DIR/photoslop-cli"
echo "  MCP: $BIN_DIR/photoslop-mcp"
echo "  Zip: $ZIP"
echo "  Checksum: $ZIP.sha256"

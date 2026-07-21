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

echo "Syncing dependencies (core + formats/raw)..."
uv sync --extra formats --extra raw
echo "Installing PyInstaller..."
uv pip install "pyinstaller>=6.10"

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
  photoslop/app.py

APP="$OUT_DIR/Photoslop.app"
if [[ ! -d "$APP" ]]; then
  echo "build-portable-macos.sh: expected app bundle was not produced: $APP" >&2
  exit 1
fi

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist" || true
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$APP/Contents/Info.plist" || true

ZIP="$OUT_DIR/Photoslop-macOS-portable-v$VERSION.zip"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

echo "Portable macOS build ready:"
echo "  App: $APP"
echo "  Zip: $ZIP"

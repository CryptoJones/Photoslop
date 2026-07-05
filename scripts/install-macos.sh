#!/usr/bin/env bash
# Photoslop — macOS installer.
#
# Builds a lightweight "Photoslop.app" launcher bundle and installs it into
# /Applications so Photoslop is clickable from Finder, Launchpad and Spotlight.
#
# The bundle is a thin wrapper: its executable execs this repo's run.sh, which
# boots the app via `uv run photoslop`. That means the app depends on this repo
# staying where it is — it is a convenience shortcut, not a portable, self-
# contained distributable.
#
# Usage:
#   ./scripts/install-macos.sh                   # install to /Applications
#   ./scripts/install-macos.sh ~/Applications    # install somewhere else
#   PHOTOSLOP_DEST=/some/dir ./scripts/install-macos.sh
#
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

APP_NAME="Photoslop"
BUNDLE_ID="net.thenetwerk.photoslop"

# --- locate the repo root (this script lives in <repo>/scripts) -------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

# Read the version straight out of pyproject.toml so the bundle never drifts.
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO/pyproject.toml" | head -1)"
VERSION="${VERSION:-0.0.0}"

# --- where to install -------------------------------------------------------
DEST_DIR="${1:-${PHOTOSLOP_DEST:-/Applications}}"
DEST="$DEST_DIR/$APP_NAME.app"

if [ ! -x "$REPO/run.sh" ]; then
  echo "install-macos.sh: cannot find an executable run.sh at $REPO/run.sh" >&2
  exit 1
fi

echo "Building $APP_NAME.app (v$VERSION) -> $DEST"

# --- build the bundle in a temp dir, then swap it in atomically -------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
APP="$WORK/$APP_NAME.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Info.plist
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>$APP_NAME</string>
  <key>CFBundleIconFile</key><string>$APP_NAME</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# Launcher executable — execs the repo's run.sh, passing through any args.
cat > "$APP/Contents/MacOS/$APP_NAME" <<LAUNCHER
#!/usr/bin/env bash
# Photoslop launcher — execs the repo's run.sh so double-clicking opens the app.
set -euo pipefail
exec "$REPO/run.sh" "\$@"
LAUNCHER
chmod +x "$APP/Contents/MacOS/$APP_NAME"

# Icon — convert docs/icon.png into a proper .icns when the tools are present.
SRC_ICON="$REPO/docs/icon.png"
if [ -f "$SRC_ICON" ] && command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
  ICONSET="$WORK/$APP_NAME.iconset"
  mkdir -p "$ICONSET"
  for sz in 16 32 64 128 256 512; do
    sips -z "$sz" "$sz" "$SRC_ICON" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null 2>&1 || true
    d=$((sz * 2))
    sips -z "$d" "$d" "$SRC_ICON" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1 || true
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/$APP_NAME.icns" || \
    echo "install-macos.sh: icon build failed; installing without a custom icon" >&2
else
  echo "install-macos.sh: skipping icon (need $SRC_ICON + sips + iconutil)" >&2
fi

# --- install ----------------------------------------------------------------
mkdir -p "$DEST_DIR"
if [ -e "$DEST" ]; then
  echo "Replacing existing $DEST"
  rm -rf "$DEST"
fi
cp -R "$APP" "$DEST"

# Register with Launch Services so Finder/Launchpad/Spotlight pick it up.
LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREG" ] && "$LSREG" -f "$DEST" >/dev/null 2>&1 || true
command -v mdimport >/dev/null 2>&1 && mdimport "$DEST" >/dev/null 2>&1 || true

echo "Installed $APP_NAME.app to $DEST_DIR"
echo "Launch it from Launchpad/Spotlight, or run: open -a \"$APP_NAME\""

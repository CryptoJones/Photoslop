#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Retake the App Store screenshots (#257) on the two device classes Apple
# requires, from the project's own artwork rather than a scribble.
#
# The screenshots this replaces were drawn by the staging test itself, and the
# canvas renders zoom-to-fit: on a phone a 1024-wide document is a couple of
# hundred points across, so a default stroke lands sub-pixel and the listing
# showed a hairline scratch on a postage stamp in the middle of a grey screen.
# That reads as an empty app — a listing problem, and one App Review looks for.
#
# Usage, from the repository root:
#
#     scripts/stage-store-screenshots.sh
#
# Simulators are shut down on any exit, including an interrupt: this machine is
# shared, and two stranded devices have cost 5.88 GB before (see AGENTS.md).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUNTIME="18.5"
ARTWORK="docs/appstore/artwork/staging-artwork.png"
OUT="docs/appstore/screenshots"
WORK="$(mktemp -d)"

trap 'xcrun simctl shutdown all >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT

# (device name, output prefix)
DEVICES=(
  "iPhone 16 Pro Max|iphone-69"
  "iPad Pro 13-inch (M4)|ipad-13"
)

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

[ -f "$ARTWORK" ] || { echo "missing $ARTWORK" >&2; exit 1; }
(cd ipados && xcodegen generate >/dev/null)

for entry in "${DEVICES[@]}"; do
  name="${entry%%|*}"
  prefix="${entry##*|}"
  udid="$(xcrun simctl list devices available \
    | sed -n "/iOS ${RUNTIME}/,/^--/p" \
    | grep -F "$name (" | head -1 | grep -oE '[0-9A-F-]{36}')"
  [ -n "$udid" ] || { echo "no $name on iOS $RUNTIME" >&2; exit 1; }

  say "$name"
  xcrun simctl shutdown all >/dev/null 2>&1 || true
  # Erased so the photo library holds only this artwork and the picker's first
  # thumbnail is deterministic, and so no earlier document is restored.
  xcrun simctl erase "$udid" >/dev/null 2>&1 || true
  xcrun simctl boot "$udid" >/dev/null
  sleep 12
  # Upscaled to the default canvas before it goes into the library. A new
  # document is 2048x1536 and the artwork is 800x600 — the same 4:3, so this
  # is a clean 2.56x with no distortion — and imported at its own size it
  # lands a third of the way across the canvas, which is how the previous
  # screenshots ended up showing a stamp inside a stamp.
  cp "$ARTWORK" "$WORK/artwork.png"
  sips --resampleHeightWidth 1536 2048 "$WORK/artwork.png" >/dev/null
  xcrun simctl addmedia "$udid" "$WORK/artwork.png"

  say "staging a document"
  ( cd ipados
    TEST_RUNNER_PHOTOSLOP_STAGE_SCREENSHOTS=1 xcodebuild \
      -project Photoslop-iPadOS.xcodeproj -scheme PhotoslopIPad -configuration Debug \
      -destination "platform=iOS Simulator,id=${udid}" \
      -only-testing:PhotoslopIPadUITests/StoreScreenshotStagingUITests \
      -resultBundlePath "$WORK/${prefix}.xcresult" CODE_SIGNING_ALLOWED=NO test \
      | grep -E "Test Case.*(passed|failed)|error:|\*\* TEST" || true )

  say "exporting the editor shot"
  rm -rf "$WORK/${prefix}-attach"
  xcrun xcresulttool export attachments \
    --path "$WORK/${prefix}.xcresult" --output-path "$WORK/${prefix}-attach" >/dev/null
  editor="$(find "$WORK/${prefix}-attach" -name '*.png' | head -1)"
  [ -n "$editor" ] || { echo "no screenshot attachment for $name" >&2; exit 1; }
  cp "$editor" "$OUT/${prefix}-editor.png"

  say "launch scene"
  # The launch scene is photographed from outside: it is what the app shows
  # before a document exists, and no test is on screen to attach it.
  xcrun simctl launch "$udid" io.ronin48.photoslop.ipad >/dev/null
  sleep 8
  xcrun simctl io "$udid" screenshot "$OUT/${prefix}-launch.png" >/dev/null
  xcrun simctl shutdown "$udid" >/dev/null 2>&1 || true
done

say "sizes"
for f in "$OUT"/*.png; do
  printf '%s: %s\n' "$(basename "$f")" \
    "$(sips -g pixelWidth -g pixelHeight "$f" | tail -2 | tr -d ' \n' | sed 's/pixelWidth:/w=/;s/pixelHeight:/ h=/')"
done

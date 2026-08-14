#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Run what CI runs, here, before pushing.
#
# Dev testing before beta testing. The iOS suite has failed on CI four times
# while passing locally, every time for the same reason: **the local simulators
# were not the ones CI uses.** GitHub's macOS runner tests an iPad Pro 11-inch
# and an iPhone 16 Pro on **iOS 18.5**; a development machine on current Xcode
# has iOS 26.x and nothing else unless it is told otherwise. Gesture arbitration,
# hit-testing and scroll-view touch delivery all differ between those two, so
# "green locally" on 26 says nothing about 18.
#
# This script pins the same devices and the same runtime as
# `.github/workflows/ipados.yml`, and runs the same legs in the same order —
# one simulator at a time, because two booted simulators starve the machine and
# unrelated tests start failing on "the editor never came up" (L-002).
#
# Usage:
#   scripts/ci-local.sh            # everything: Python gates, desktop, both iOS legs
#   scripts/ci-local.sh ios        # iOS only
#   scripts/ci-local.sh python     # Python only
#   scripts/ci-local.sh desktop    # the desktop app as a user actually gets it
#
# First run downloads the iOS runtime if it is missing (~9 GB, once).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Keep in step with .github/workflows/ipados.yml.
RUNTIME_VERSION="18.5"
RUNTIME_ID="com.apple.CoreSimulator.SimRuntime.iOS-18-5"
IPAD_MODEL="iPad Pro 11-inch (M4)"
IPHONE_MODEL="iPhone 16 Pro"
IPAD_NAME="CI-iPad-${RUNTIME_VERSION}"
IPHONE_NAME="CI-iPhone-${RUNTIME_VERSION}"
BUNDLE_ID="io.ronin48.photoslop.ipad"

WHAT="${1:-all}"
FAILED_LEGS=""

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

run_python() {
  say "Version gate"
  uv run python scripts/check-version.py
  say "Lint"
  uv run ruff check .
  uv run ruff format --check .
  say "Mascot asset matches the code that draws it"
  uv run python scripts/render-ios-mascot.py --check
  say "Python tests"
  QT_QPA_PLATFORM=offscreen uv run pytest -q
}

ensure_runtime() {
  if ! xcrun simctl list runtimes | grep -q "iOS ${RUNTIME_VERSION}"; then
    say "Downloading the iOS ${RUNTIME_VERSION} runtime (once, ~9 GB)"
    xcodebuild -downloadPlatform iOS -buildVersion "${RUNTIME_VERSION}"
  fi
}

# Echoes the udid, creating the simulator the first time.
ensure_device() {
  local name="$1" model="$2" udid
  udid="$(xcrun simctl list devices -j |
    /usr/bin/python3 -c "
import json,sys
name = sys.argv[1]
devices = json.load(sys.stdin)['devices']
print(next((d['udid'] for runtime in devices.values() for d in runtime
            if d['name'] == name), ''))
" "$name")"
  if [ -z "$udid" ]; then
    udid="$(xcrun simctl create "$name" "$model" "$RUNTIME_ID")"
  fi
  echo "$udid"
}

# One simulator at a time. Booting both up front starves the machine, which is
# how a photo-permission fix once took down three unrelated tests (L-002).
# A leg's exit status is the leg's verdict, and it must survive the pipe.
#
# The first version of this piped xcodebuild into grep and ended `|| true`, so a
# failing leg exited 0 and the script printed "Done". A whole iPad leg failed
# that way and was reported as green — the exact failure this script exists to
# prevent, committed by the script itself. `PIPESTATUS` is what makes the
# filtered output honest.
run_leg() {
  local label="$1" udid="$2" status
  say "iOS leg: ${label} (iOS ${RUNTIME_VERSION})"
  xcrun simctl shutdown all >/dev/null 2>&1 || true
  xcrun simctl boot "$udid" >/dev/null 2>&1 || true
  sleep 10
  # The export-to-Photos test asserts the save, not the consent dialog.
  xcrun simctl privacy "$udid" grant photos-add "$BUNDLE_ID" >/dev/null 2>&1 || true
  set +e
  xcodebuild test \
    -project ipados/Photoslop-iPadOS.xcodeproj \
    -scheme PhotoslopIPad \
    -destination "platform=iOS Simulator,id=${udid}" \
    -derivedDataPath ipados/build/ci-local \
    | grep -E "error:|Test Case.*failed|Executed .* tests, with|\*\* TEST"
  status="${PIPESTATUS[0]}"
  set -e
  xcrun simctl shutdown "$udid" >/dev/null 2>&1 || true
  if [ "$status" -ne 0 ]; then
    FAILED_LEGS="${FAILED_LEGS}${label} "
    printf '\n\033[1;31m==> FAILED: %s\033[0m\n' "$label"
  else
    printf '\n\033[1;32m==> passed: %s\033[0m\n' "$label"
  fi
  return 0
}

run_ios() {
  ensure_runtime
  say "Generating the Xcode project"
  (cd ipados && xcodegen generate >/dev/null)
  local ipad iphone
  ipad="$(ensure_device "$IPAD_NAME" "$IPAD_MODEL")"
  iphone="$(ensure_device "$IPHONE_NAME" "$IPHONE_MODEL")"
  # Same order as CI: iPad first, then iPhone.
  run_leg "$IPAD_MODEL" "$ipad"
  run_leg "$IPHONE_MODEL" "$iphone"
}

# The desktop app the way a user receives it, rather than the way we develop it.
#
# `uv run photoslop` from the checkout exercises the source tree with every dev
# dependency present and the repo on the path. A user gets a wheel, or a
# clickable app bundle, and neither of those is what the test suite runs. A
# packaging fault — a missing runtime dependency, a broken entry point, an asset
# that lives in the repo but not in the distribution — is invisible to 3261
# passing tests and immediately visible to whoever installed it.
run_desktop() {
  local work; work="$(mktemp -d)"
  trap 'rm -rf "$work"' RETURN

  say "Building the wheel and sdist"
  uv build

  say "Installing the wheel into a clean environment"
  local wheel; wheel="$(ls -t dist/*.whl | head -1)"
  uv venv --python 3.12 "$work/venv" >/dev/null
  uv pip install --python "$work/venv/bin/python" "$wheel" >/dev/null

  say "The installed package reports the version it was built as"
  local built installed
  built="$(uv run python scripts/check-version.py)"
  installed="$("$work/venv/bin/python" -c 'import photoslop; print(photoslop.__version__)')"
  test "$built" = "$installed" || {
    echo "installed $installed but built $built" >&2
    return 1
  }
  echo "$installed"

  say "The GUI starts, opens Qt, and round-trips an image"
  # The same smoke the portable bundle runs, against the installed entry point:
  # it boots Qt offscreen, then imports and exports through the real codecs.
  QT_QPA_PLATFORM=offscreen "$work/venv/bin/photoslop" --portable-smoke

  say "The CLI renders a real file"
  "$work/venv/bin/photoslop-cli" --new 64x64 --fill 255,0,0 -o "$work/out.png"
  test -s "$work/out.png" || { echo "the CLI produced no output" >&2; return 1; }
  echo "wrote $(wc -c <"$work/out.png" | tr -d ' ') bytes"

  say "The clickable app bundle builds and launches"
  # `install-macos.sh` builds a thin .app that execs this repo. It is the route
  # most people take on a Mac, and nothing else tests that it even starts.
  PHOTOSLOP_DEST="$work/Applications" ./scripts/install-macos.sh "$work/Applications" >/dev/null
  local binary="$work/Applications/Photoslop.app/Contents/MacOS/Photoslop"
  test -x "$binary" || { echo "the app bundle has no executable" >&2; return 1; }
  QT_QPA_PLATFORM=offscreen "$binary" --portable-smoke
  echo "the bundle launched and passed its smoke"
}

case "$WHAT" in
  python) run_python ;;
  ios) run_ios ;;
  desktop) run_desktop ;;
  all) run_python; run_desktop; run_ios ;;
  *) echo "usage: $0 [all|python|desktop|ios]" >&2; exit 2 ;;
esac

if [ -n "$FAILED_LEGS" ]; then
  printf '\n\033[1;31m==> FAILED: %s\033[0m\n' "$FAILED_LEGS"
  echo "Do not push. This is the configuration CI runs." >&2
  exit 1
fi

say "Done. A green run here is the same configuration CI runs."

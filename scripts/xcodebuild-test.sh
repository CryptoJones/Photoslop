#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Run `xcodebuild … test` once, and again only if the XCTest daemon never
# brought up a UI-testing session (#238):
#
#   Failed to initialize for UI testing: XCTDaemonErrorDomain Code=19
#   "Failed call to AXDisableAccessibilityOnTermination"
#
# When that happens zero tests execute and no app is involved, so there is
# nothing for test code to wait on and re-running the invocation is the only
# remedy. Everything else — an assertion, a timeout, a crash — fails on the
# first run. This replaces `-retry-tests-on-failure -test-iterations 2`, which
# retried *any* failing test and so gave a real defect a second chance to look
# intermittent; that is how #227 hid for months.
#
# Usage: scripts/xcodebuild-test.sh <xcodebuild arguments…>
set -uo pipefail

DAEMON_FAILURE='XCTDaemonErrorDomain Code=19|Failed to initialize for UI testing'
log="$(mktemp -t xcodebuild-test)"
trap 'rm -f "$log"' EXIT

for attempt in 1 2; do
  xcodebuild "$@" 2>&1 | tee "$log"
  status="${PIPESTATUS[0]}"
  if [ "$status" -eq 0 ]; then
    exit 0
  fi
  if [ "$attempt" -eq 1 ] && grep -Eq "$DAEMON_FAILURE" "$log"; then
    echo "::warning::XCTest daemon could not start a UI-testing session; re-running once (#238)"
    continue
  fi
  exit "$status"
done

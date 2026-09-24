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

DAEMON_FAILURE='XCTDaemonErrorDomain Code=19'

# Retry only when the daemon error is present AND it is the only failure: every
# test-failure line (`… error: -[Class test] : message`) must be the daemon's.
# A real assertion anywhere in the log — even one followed later by a daemon
# error — must not get a second run that could come back green and hide it.
only_daemon_failed() {
  grep -q "$DAEMON_FAILURE" "$1" || return 1
  ! grep -E 'error: -\[' "$1" | grep -vq "$DAEMON_FAILURE"
}

log="$(mktemp -t xcodebuild-test)"
trap 'rm -f "$log"' EXIT

for attempt in 1 2; do
  xcodebuild "$@" 2>&1 | tee "$log"
  status="${PIPESTATUS[0]}"
  if [ "$status" -eq 0 ]; then
    exit 0
  fi
  if [ "$attempt" -eq 1 ] && only_daemon_failed "$log"; then
    echo "::warning::XCTest daemon could not start a UI-testing session; re-running once (#238)"
    continue
  fi
  exit "$status"
done

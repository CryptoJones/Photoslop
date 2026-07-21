#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  exit 0
fi

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  libegl1 libgl1 libglib2.0-0 libxkbcommon0 libdbus-1-3 libfontconfig1

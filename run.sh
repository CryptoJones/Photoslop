#!/usr/bin/env bash
# Photoslop launcher for humans (Linux/macOS).
#
# Bootstraps `uv` if it's missing, then starts the app. Any arguments are
# passed straight through to `photoslop` — e.g. `./run.sh path/to/image.png`.
#
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

# Run from the repo root no matter where this was invoked from.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "run.sh: 'uv' not found — installing it from https://astral.sh/uv ..." >&2
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv installs to ~/.local/bin (or ~/.cargo/bin on older installers); make it
  # visible for the rest of this script without needing a new shell.
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

# `uv run` creates/syncs the project venv on demand, so no separate `uv sync`
# step is needed. exec replaces this shell with the app.
exec uv run photoslop "$@"

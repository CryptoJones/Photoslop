#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Enforce the measured branch-coverage floor for failure-prone modules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Floors were set just below the 2026-07-21 measured baseline documented in
# docs/v1/coverage.md. They are intentionally module-specific, not an invented
# repository-wide percentage.
MINIMUM = {
    "photoslop/atomicio.py": 88,
    "photoslop/commands.py": 46,
    "photoslop/document.py": 48,
    "photoslop/io_ora.py": 63,
    "photoslop/io_svg.py": 51,
    "photoslop/modeladapter.py": 70,
    "photoslop/recovery.py": 84,
    "photoslop/resources.py": 76,
    "photoslop/server.py": 77,
    "photoslop/services.py": 53,
    "photoslop/tasks.py": 84,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    failures = []
    for filename, minimum in MINIMUM.items():
        entry = report.get("files", {}).get(filename)
        if entry is None:
            failures.append(f"{filename}: missing from coverage report")
            continue
        actual = float(entry["summary"]["percent_covered"])
        if actual < minimum:
            failures.append(f"{filename}: {actual:.2f}% < measured floor {minimum}%")
    if failures:
        raise SystemExit("critical coverage regression:\n" + "\n".join(failures))
    print(f"critical coverage floors passed for {len(MINIMUM)} modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

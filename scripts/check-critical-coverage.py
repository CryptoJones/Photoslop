#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Enforce the measured branch-coverage floor for failure-prone modules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Floors sit two points under what each module measured on 2026-09-24 (#406),
# with the job measuring the whole suite. The July floors were calibrated to a
# hand-picked test list that under-measured and left most of them 30-50 points
# below reality, so a module could lose half its tests without failing the
# gate. Raise a floor when coverage rises; never lower one to make a PR pass.
MINIMUM = {
    "photoslop/atomicio.py": 93,
    "photoslop/commands.py": 91,
    "photoslop/document.py": 95,
    "photoslop/io_ora.py": 90,
    "photoslop/io_svg.py": 82,
    "photoslop/modeladapter.py": 83,
    "photoslop/recovery.py": 96,
    "photoslop/resources.py": 98,
    "photoslop/server.py": 79,
    "photoslop/services.py": 96,
    "photoslop/tasks.py": 89,
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

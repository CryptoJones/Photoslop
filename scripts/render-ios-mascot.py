#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render the mascot into the iOS asset catalogue.

The desktop draws Le Basilisk in code (`photoslop/appicon.py`), so there is no
asset file to copy and the iOS app icon is a flattened render on white — wrong
for a grouped list, and wrong in dark mode. This exports the QPainter original,
which is transparent by construction, at the three scales an asset catalogue
wants.

Run it after changing `draw_mascot`; CI checks the output is current.

    QT_QPA_PLATFORM=offscreen uv run python scripts/render-ios-mascot.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGESET = ROOT / "ipados/Photoslop/Assets.xcassets/Mascot.imageset"
# The About header draws it at 96 pt, so @1x/@2x/@3x are 96/192/288 px.
POINT_SIZE = 96
SCALES = (1, 2, 3)

CONTENTS = {
    "images": [
        {"filename": f"mascot-{scale}x.png", "idiom": "universal", "scale": f"{scale}x"}
        for scale in SCALES
    ],
    "info": {"author": "xcode", "version": 1},
}


def render() -> dict[Path, bytes]:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication

    # QPixmap needs a QGuiApplication even offscreen.
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    from photoslop.appicon import mascot_pixmap

    written: dict[Path, bytes] = {}
    for scale in SCALES:
        pixmap = mascot_pixmap(POINT_SIZE * scale)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not pixmap.save(buffer, "PNG"):
            raise SystemExit(f"could not encode the mascot at {scale}x")
        written[IMAGESET / f"mascot-{scale}x.png"] = bytes(buffer.data())
    del app
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed asset is stale instead of rewriting it",
    )
    args = parser.parse_args()

    rendered = render()
    contents = json.dumps(CONTENTS, indent=2) + "\n"

    if args.check:
        stale = [
            path.name
            for path, data in rendered.items()
            if not path.exists() or path.read_bytes() != data
        ]
        index = IMAGESET / "Contents.json"
        if not index.exists() or index.read_text(encoding="utf-8") != contents:
            stale.append(index.name)
        if stale:
            raise SystemExit(
                f"{IMAGESET.relative_to(ROOT)} is stale: {', '.join(stale)}. "
                "Re-run scripts/render-ios-mascot.py."
            )
        print("mascot asset is current")
        return 0

    IMAGESET.mkdir(parents=True, exist_ok=True)
    for path, data in rendered.items():
        path.write_bytes(data)
    (IMAGESET / "Contents.json").write_text(contents, encoding="utf-8")
    print(f"wrote {len(rendered)} renders to {IMAGESET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

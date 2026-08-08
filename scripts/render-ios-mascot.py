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


# Byte equality is the wrong test across platforms: Qt's rasteriser antialiases and
# its PNG encoder packs slightly differently on Linux than on macOS, so an asset
# committed from a Mac never matches one rendered on a Linux CI runner byte for
# byte. Comparing decoded pixels with a tolerance still catches the thing worth
# catching — the artwork itself changing — without failing on the encoder.
CHANNEL_TOLERANCE = 16
MAX_DIFFERING_FRACTION = 0.02


def _differs(committed: bytes, rendered: bytes) -> str | None:
    """Describe how two renders differ, or None when they match closely enough."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QImage

    left, right = QImage(), QImage()
    left.loadFromData(QByteArray(committed), "PNG")
    right.loadFromData(QByteArray(rendered), "PNG")
    if left.isNull():
        return "the committed file is not a readable PNG"
    if left.size() != right.size():
        return (
            f"size {left.width()}x{left.height()} "
            f"but the code draws {right.width()}x{right.height()}"
        )

    fmt = QImage.Format.Format_ARGB32
    left, right = left.convertToFormat(fmt), right.convertToFormat(fmt)
    differing = 0
    for y in range(left.height()):
        for x in range(left.width()):
            a, b = left.pixelColor(x, y), right.pixelColor(x, y)
            spread = max(
                abs(a.red() - b.red()),
                abs(a.green() - b.green()),
                abs(a.blue() - b.blue()),
                abs(a.alpha() - b.alpha()),
            )
            if spread > CHANNEL_TOLERANCE:
                differing += 1
    fraction = differing / (left.width() * left.height())
    if fraction > MAX_DIFFERING_FRACTION:
        return f"{fraction:.1%} of pixels differ from what the code draws"
    return None


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
        stale = []
        for path, data in rendered.items():
            if not path.exists():
                stale.append(f"{path.name} is missing")
                continue
            reason = _differs(path.read_bytes(), data)
            if reason is not None:
                stale.append(f"{path.name}: {reason}")
        index = IMAGESET / "Contents.json"
        if not index.exists() or index.read_text(encoding="utf-8") != contents:
            stale.append(f"{index.name} does not list the expected scales")
        if stale:
            raise SystemExit(
                f"{IMAGESET.relative_to(ROOT)} is stale — "
                + "; ".join(stale)
                + ". Re-run scripts/render-ios-mascot.py."
            )
        print("mascot asset matches the code that draws it")
        return 0

    IMAGESET.mkdir(parents=True, exist_ok=True)
    for path, data in rendered.items():
        path.write_bytes(data)
    (IMAGESET / "Contents.json").write_text(contents, encoding="utf-8")
    print(f"wrote {len(rendered)} renders to {IMAGESET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

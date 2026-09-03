# SPDX-License-Identifier: Apache-2.0
"""Regenerate the iOS appearance-effects parity fixture from the desktop
renderer.

``ipados/Photoslop/AppearanceRenderer.swift`` (#316) claims to be a port of
``photoslop.appearance.render`` — the same three-pass box blur over the same
float32 cumulative sums, the same morphology, the same truncating colourise —
not a re-derivation. This script is the proof: it draws a small text-shaped
alpha mask, runs the *desktop* renderer over it once per effect kind, and
writes the resulting planes (premultiplied ARGB32 words, offsets, stacking
order, blend mode) as a Swift source file that ``AppearanceParityTests``
compares against word for word. The blur is also written raw, as float32 hex
literals, so the blur itself is proven bit-exact and not merely close enough
to survive quantisation.

Run from the repository root::

    QT_QPA_PLATFORM=offscreen uv run python scripts/gen-appearance-fixture.py
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

from photoslop import appearance, npimage
from photoslop.layer import FORMAT

OUT = (
    Path(__file__).resolve().parent.parent
    / "ipados/PhotoslopTests/Fixtures/AppearanceFixture.swift"
)

W, H = 14, 10

# A "T" with a dot beside it, the way antialiased type lands: full coverage in
# the stem and bar, half coverage along their edges, a lone dot at the right.
# Values are alpha 0..255.
ALPHA = np.zeros((H, W), np.uint8)
ALPHA[1, 2:9] = 128  # the bar's soft top edge
ALPHA[2:4, 2:9] = 255  # the bar
ALPHA[4, 2:9] = 128  # the bar's soft bottom edge
ALPHA[4:8, 4:7] = 255  # the stem
ALPHA[4:8, 3] = 96  # the stem's soft left edge
ALPHA[4:8, 7] = 96  # the stem's soft right edge
ALPHA[8, 4:7] = 128  # the stem's soft foot
ALPHA[6:8, 10:12] = 255  # the dot
ALPHA[5, 10:12] = 200


def build_source() -> QImage:
    """The mask as a white, premultiplied layer image: alpha is all the
    renderer reads, and the colour keeps the words honest."""
    img = QImage(W, H, FORMAT)
    a = ALPHA.astype(np.uint32)
    npimage.view_u32(img)[:] = (a << 24) | (a << 16) | (a << 8) | a
    return img


class _Layer:
    """Just enough of `photoslop.layer.Layer` for `appearance.render`."""

    def __init__(self, image: QImage, effects: list[dict]) -> None:
        self.image = image
        self.effects = effects
        self.mask = None


# (name, effect, what the scenario proves)
SCENARIOS = [
    (
        "dropShadow",
        appearance.new_effect(
            "drop-shadow", offset_x=2, offset_y=3, blur=4, spread=1, color=[200, 30, 30, 153]
        ),
        "a coloured shadow: spread grows the mask, blur softens it, the plane sits under",
    ),
    (
        "dropShadowDefaults",
        appearance.new_effect("drop-shadow"),
        "the desktop defaults, untouched",
    ),
    (
        "bevelEmboss",
        appearance.new_effect(
            "bevel-emboss",
            depth=120,
            angle=135,
            altitude=40,
            highlight_color=[255, 240, 200, 190],
            shadow_color=[40, 0, 60, 160],
        ),
        "two planes over the fill: a screened highlight and a multiplied shadow",
    ),
    (
        "outerGlow",
        appearance.new_effect("outer-glow", size=3, spread=1, color=[0, 220, 255, 230]),
        "the blurred, grown mask minus the original, under the fill",
    ),
    (
        "innerShadow",
        appearance.new_effect("inner-shadow", offset_x=1, offset_y=1, blur=2, spread=1),
        "the inverse-shifted mask blurred, kept inside the alpha, over the fill",
    ),
    (
        "outlineOutside",
        appearance.new_effect("outline", width=1, color=[255, 255, 255, 255]),
        "a one-pixel ring outside the mask, under the fill",
    ),
    (
        "outlineCenter",
        appearance.new_effect("outline", width=3, position="center"),
        "half outside and half inside, over the fill",
    ),
    (
        "outlineInside",
        appearance.new_effect("outline", width=1, position="inside"),
        "the eroded rim, over the fill",
    ),
    (
        "innerGlowEdge",
        appearance.new_effect("inner-glow", size=2, color=[255, 255, 0, 180]),
        "the edge glow, masked by the alpha",
    ),
    (
        "innerGlowCenter",
        appearance.new_effect("inner-glow", size=2, choke=1, source="center"),
        "the choked centre glow",
    ),
    (
        "colorOverlay",
        appearance.new_effect("color-overlay", color=[10, 200, 30, 255]),
        "the alpha in one colour, over the fill",
    ),
    (
        "gradientOverlay",
        appearance.new_effect(
            "gradient-overlay", color1=[245, 250, 255, 255], color2=[45, 65, 90, 255], angle=45
        ),
        "a diagonal gradient through the alpha, over the fill",
    ),
    (
        "disabled",
        {**appearance.new_effect("drop-shadow"), "enabled": False},
        "a disabled effect renders no plane at all",
    ),
    (
        "halfOpacityScreen",
        {**appearance.new_effect("outer-glow", size=2), "opacity": 0.5, "blend_mode": "screen"},
        "opacity and blend mode ride on the plane rather than the pixels",
    ),
]

BLUR_RADIUS = 4


def words(arr, width) -> str:
    rows = []
    for row in arr:
        rows.append("        " + ", ".join(f"0x{int(v):08X}" for v in row) + ",")
    return "\n".join(rows)


def floats(arr) -> str:
    rows = []
    for row in arr:
        rows.append("      " + ", ".join(float(np.float32(v)).hex() for v in row) + ",")
    return "\n".join(rows)


def main() -> int:
    source = build_source()
    blurred = appearance._blur_plane(appearance._alpha(source), BLUR_RADIUS)
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// GENERATED by scripts/gen-appearance-fixture.py from the desktop",
        "// photoslop.appearance.render — do not edit by hand. Regenerate with:",
        "//   QT_QPA_PLATFORM=offscreen uv run python scripts/gen-appearance-fixture.py",
        "",
        "/// Desktop-produced expected effect planes for the iOS appearance renderer",
        "/// (#316). `alpha` is the source mask; each scenario is one normalised effect",
        "/// as JSON and the planes the desktop rendered from it, as little-endian",
        "/// ARGB32 premultiplied words (`PixelBuffer.words`). `blurred` is",
        "/// `_blur_plane(alpha, blurRadius)` raw, as float32 hex literals.",
        "enum AppearanceFixture {",
        f"  static let width = {W}",
        f"  static let height = {H}",
        "",
        "  static let alpha: [Float] = [",
        "\n".join("      " + ", ".join(str(int(v)) for v in row) + "," for row in ALPHA),
        "  ]",
        "",
        f"  static let blurRadius = {BLUR_RADIUS}",
        "  static let blurred: [Float] = [",
        floats(blurred),
        "  ]",
        "",
        "  struct Plane {",
        "    let offsetX: Int",
        "    let offsetY: Int",
        "    let under: Bool",
        "    let blendMode: String",
        "    let opacity: Double",
        "    let width: Int",
        "    let height: Int",
        "    let words: [UInt32]",
        "  }",
        "",
        "  struct Scenario {",
        "    let name: String",
        "    /// The effect exactly as the desktop normalised it.",
        "    let effect: String",
        "    let planes: [Plane]",
        "  }",
        "",
        "  static let scenarios: [Scenario] = [",
    ]
    for name, effect, doc in SCENARIOS:
        # A content-derived id, so regenerating writes the same file.
        effect["id"] = uuid.uuid5(uuid.NAMESPACE_URL, "photoslop-fixture:" + name).hex
        normalized = appearance.normalize_effect(effect)
        rendered = appearance.render(_Layer(source, [normalized]))
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        out += [
            f"    // {doc}",
            f'    Scenario(name: "{name}",',
            f"      effect: {json.dumps(payload)},",
            "      planes: [",
        ]
        for plane in rendered.planes:
            arr = npimage.view_u32(plane.image)
            out += [
                f"        Plane(offsetX: {plane.offset.x()}, offsetY: {plane.offset.y()},"
                f" under: {'true' if plane.under else 'false'},",
                f'          blendMode: "{plane.blend_mode}", opacity: {plane.opacity},',
                f"          width: {plane.image.width()}, height: {plane.image.height()}, words: [",
                words(arr, plane.image.width()),
                "        ]),",
            ]
        out += ["      ]),"]
    out += ["  ]", "}", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

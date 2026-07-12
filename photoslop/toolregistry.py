# SPDX-License-Identifier: Apache-2.0
"""Declarative toolbox metadata shared by actions and grouped flyouts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    label: str
    shortcut: str
    group: str
    icon: str


TOOL_SPECS = (
    ToolSpec("move", "Move", "V", "move", "arrows-move"),
    ToolSpec("rect-select", "Rectangle Select", "M", "marquee", "transform"),
    ToolSpec("ellipse-select", "Ellipse Select", "Shift+M", "marquee", "transform"),
    ToolSpec("lasso", "Lasso Select", "L", "lasso", "lasso"),
    ToolSpec("poly-lasso", "Polygonal Lasso", "Shift+L", "lasso", "lasso"),
    ToolSpec("magnetic-lasso", "Magnetic Lasso", "Alt+L", "lasso", "lasso"),
    ToolSpec("wand", "Magic Wand", "W", "automatic", "wand"),
    ToolSpec("quick-select", "Quick Selection", "Shift+W", "automatic", "brush"),
    ToolSpec("crop", "Crop", "C", "warp", "crop"),
    ToolSpec("perspective", "Perspective Warp", "Shift+P", "warp", "transform"),
    ToolSpec("puppet", "Puppet Warp", "Shift+Y", "warp", "transform"),
    ToolSpec("brush", "Brush", "B", "paint", "brush"),
    ToolSpec("pencil", "Pencil", "Shift+B", "paint", "pencil"),
    ToolSpec("eraser", "Eraser", "E", "paint", "eraser"),
    ToolSpec("clone-stamp", "Clone Stamp", "S", "heal", "bandage"),
    ToolSpec("spot-heal", "Spot Healing", "J", "heal", "bandage"),
    ToolSpec("heal", "Healing Brush", "Shift+J", "heal", "bandage"),
    ToolSpec("patch", "Patch", "Alt+Shift+J", "heal", "bandage"),
    ToolSpec("smudge", "Smudge / Mixer", "Shift+S", "retouch", "brush"),
    ToolSpec("dodge", "Dodge", "O", "retouch", "brush"),
    ToolSpec("burn", "Burn", "Shift+O", "retouch", "brush"),
    ToolSpec("liquify", "Liquify", "Y", "retouch", "transform"),
    ToolSpec("bucket", "Paint Bucket", "G", "fill", "bucket-droplet"),
    ToolSpec("gradient", "Gradient", "Shift+G", "fill", "bucket-droplet"),
    ToolSpec("pen", "Pen", "P", "pen", "vector-bezier"),
    ToolSpec("shape", "Shape", "U", "shape", "transform"),
    ToolSpec("text", "Text", "T", "text", "text-size"),
    ToolSpec("eyedropper", "Eyedropper", "I", "eyedropper", "color-picker"),
    ToolSpec("hand", "Hand", "H", "navigation", "arrows-move"),
    ToolSpec("zoom", "Zoom", "Z", "navigation", "zoom-in"),
)

TOOL_SPEC_BY_ID = {spec.tool_id: spec for spec in TOOL_SPECS}
TOOL_GROUPS = tuple(dict.fromkeys(spec.group for spec in TOOL_SPECS))

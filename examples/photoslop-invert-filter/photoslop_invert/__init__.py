# SPDX-License-Identifier: Apache-2.0
"""Reference Photoslop filter plugin: install with `pip install .` and
"Invert" appears in the Filter menu, `--filter invert` works in the CLI,
and smart-filter replay picks it up — all from the entry point alone."""

import numpy as np
from PySide6.QtGui import QImage

from photoslop.filters import Filter, ParamSpec
from photoslop.npimage import view_u32


class InvertFilter(Filter):
    name = "invert"
    label = "Invert"
    params = (ParamSpec("amount", "Amount", "int", 0, 100, 100),)

    def apply(self, image: QImage, params: dict) -> None:
        k = float(params.get("amount", 100)) / 100.0
        arr = view_u32(image)
        a = (arr >> np.uint32(24)).astype(np.float32)
        # premultiplied buffers invert against alpha, not 255
        for shift in (16, 8, 0):
            c = ((arr >> np.uint32(shift)) & 0xFF).astype(np.float32)
            inv = c + (a - 2.0 * c) * k
            arr &= ~np.uint32(0xFF << shift)
            arr |= np.clip(inv, 0, 255).astype(np.uint32) << np.uint32(shift)

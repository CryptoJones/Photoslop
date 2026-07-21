# SPDX-License-Identifier: Apache-2.0
"""Extra raster formats (AVIF, JPEG XL) via the optional `photoslop[formats]`
extra — Pillow >= 11 carries AVIF; pillow-jxl-plugin adds JPEG XL. Everything
is feature-detected: without the extra, these helpers simply report the
formats as unavailable and the rest of the app behaves exactly as before.

Decode/encode goes QImage <-> Pillow through raw RGBA bytes — a transient
per-image copy, within the DD-001 allowance."""

from __future__ import annotations

from PySide6.QtGui import QImage

from photoslop.atomicio import atomic_bytes

EXTRA_EXTS = (".avif", ".jxl")

_checked: dict[str, bool] = {}


def _detect() -> dict[str, bool]:
    if _checked:
        return _checked
    avif = jxl = False
    try:
        from PIL import features

        avif = bool(features.check("avif"))
    except ImportError:
        pass
    try:
        import pillow_jxl  # noqa: F401 — importing registers the codec

        jxl = True
    except ImportError:
        pass
    _checked[".avif"] = avif
    _checked[".jxl"] = jxl
    return _checked


def is_extra_path(path: str) -> bool:
    return path.lower().endswith(EXTRA_EXTS)


def available(path: str) -> bool:
    """True when the codec for this path's extension is installed."""
    for ext, ok in _detect().items():
        if path.lower().endswith(ext):
            return ok
    return False


def missing_hint(path: str) -> str:
    return (
        f"{path}: this format needs the optional extra — "
        'install with `pip install "photoslop[formats]"`'
    )


def load_extra(path: str, *, allow_large: bool = False) -> QImage | None:
    """Decode an AVIF/JXL file to a premultiplied ARGB32 QImage."""
    if not available(path):
        return None
    from PIL import Image

    from photoslop.resources import validate_dimensions

    with Image.open(path) as im:
        validate_dimensions(*im.size, operation="image decode", buffers=2, allow_large=allow_large)
        rgba = im.convert("RGBA")
        img = QImage(
            rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888
        )
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def encode_extra(image: QImage, ext: str, quality: int = 90) -> bytes | None:
    """Encode a QImage to AVIF/JXL bytes (alpha preserved); None on failure."""
    if not available("x" + ext):
        return None
    import io

    from PIL import Image

    src = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = src.constBits().tobytes()
    im = Image.frombytes("RGBA", (src.width(), src.height()), data)
    buf = io.BytesIO()
    try:
        im.save(buf, format={".avif": "AVIF", ".jxl": "JXL"}[ext], quality=quality)
    except (OSError, ValueError, KeyError):
        return None
    return buf.getvalue()


def save_extra(image: QImage, path: str, quality: int = 90) -> bool:
    """Encode a QImage to an AVIF/JXL file. Alpha is preserved."""
    ext = "." + path.lower().rsplit(".", 1)[-1]
    data = encode_extra(image, ext, quality)
    if data is None:
        return False
    try:
        atomic_bytes(path, data)
    except OSError:
        return False
    return True

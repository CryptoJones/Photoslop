# SPDX-License-Identifier: Apache-2.0
"""ICC color management (#108) — accepted by DD-004 precisely because it is
viewport-only work: a document profile is metadata, the display transform
touches only the composited viewport region, soft-proofing is a viewport
round-trip, and export conversion is a one-shot transient. No layer buffer
changes anywhere (deep bit depth stays rejected per DD-002).

The engine is Qt's own QColorSpace (zero new dependencies): named presets,
.icc files, image conversion, and profile embedding on PNG/JPEG export.
CMYK export is the one Pillow-assisted path (littlecms), feature-detected,
and needs a user-supplied CMYK .icc — Photoslop bundles no profiles."""

from __future__ import annotations

import os

from PySide6.QtGui import QColorSpace, QImage


def pathlib_read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()

PRESETS = {
    "srgb": QColorSpace.NamedColorSpace.SRgb,
    "srgb-linear": QColorSpace.NamedColorSpace.SRgbLinear,
    "adobe-rgb": QColorSpace.NamedColorSpace.AdobeRgb,
    "display-p3": QColorSpace.NamedColorSpace.DisplayP3,
    "prophoto-rgb": QColorSpace.NamedColorSpace.ProPhotoRgb,
}

# session-wide view settings (persisted by the dialog, read by the canvas)
settings: dict = {"display": None, "proof": None, "proof_on": False}


def load_space(spec: str) -> QColorSpace:
    """A QColorSpace from a preset name or an .icc file path."""
    key = spec.strip().lower()
    if key in PRESETS:
        return QColorSpace(PRESETS[key])
    if os.path.exists(spec):
        with open(spec, "rb") as fh:
            space = QColorSpace.fromIccProfile(fh.read())
        if space.isValid():
            return space
        raise ValueError(f"not a usable ICC profile: {spec}")
    raise ValueError(
        f"unknown profile {spec!r}: use a preset ({', '.join(PRESETS)}) "
        "or a path to an .icc file")


def describe(space: QColorSpace | None) -> str:
    if space is None or not space.isValid():
        return "untagged (sRGB assumed)"
    return space.description() or "custom profile"


def doc_space(doc) -> QColorSpace:
    space = getattr(doc, "icc_space", None)
    return space if space is not None and space.isValid() \
        else QColorSpace(QColorSpace.NamedColorSpace.SRgb)


def assign_profile(doc, space: QColorSpace) -> None:
    """Reinterpret: metadata only, pixels untouched."""
    doc.icc_space = QColorSpace(space)


def convert_profile(doc, space: QColorSpace) -> None:
    """Convert every layer's pixels to `space` (one transient per layer)."""
    src = doc_space(doc)
    for layer in doc.layers:
        if layer.image.isNull():
            continue
        img = layer.image.convertToFormat(QImage.Format.Format_ARGB32)
        img.setColorSpace(src)
        img = img.convertedToColorSpace(space)
        layer.image = img.convertToFormat(
            QImage.Format.Format_ARGB32_Premultiplied)
        layer.fx_cache = None
    doc.icc_space = QColorSpace(space)
    doc.notify_pixels(doc.canvas_rect())


def viewport_active() -> bool:
    return (settings.get("display") is not None
            or (settings.get("proof_on") and settings.get("proof") is not None))


def apply_viewport(image: QImage, doc) -> QImage:
    """Transform ONE composited viewport region for display — the entire
    resident cost of color management (DD-004)."""
    src = doc_space(doc)
    out = image.convertToFormat(QImage.Format.Format_ARGB32)
    out.setColorSpace(src)
    if settings.get("proof_on") and settings.get("proof") is not None:
        # round-trip through the proof space simulates its gamut
        out = out.convertedToColorSpace(settings["proof"])
        out.setColorSpace(settings["proof"])
    target = settings.get("display") or src
    out = out.convertedToColorSpace(target)
    return out.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def tag_for_export(image: QImage, doc) -> QImage:
    """Stamp the document profile so Qt embeds it in PNG/JPEG output."""
    space = getattr(doc, "icc_space", None)
    if space is not None and space.isValid():
        image.setColorSpace(space)
    return image


def proof_simulate(image: QImage, doc, proof: QColorSpace) -> QImage:
    """Headless soft-proof: doc space -> proof space -> back (gamut clip)."""
    src = doc_space(doc)
    out = image.convertToFormat(QImage.Format.Format_ARGB32)
    out.setColorSpace(src)
    out = out.convertedToColorSpace(proof)
    out.setColorSpace(proof)
    out = out.convertedToColorSpace(src)
    return out.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def cmyk_export(image: QImage, path: str, cmyk_icc: str,
                quality: int = 90) -> None:
    """Write a CMYK JPEG/TIFF via Pillow + littlecms (DD-005: transient
    conversion only — no CMYK working mode)."""
    try:
        from PIL import Image, ImageCms
    except ImportError as exc:
        raise ValueError(
            "CMYK export needs Pillow — install photoslop[formats]") from exc
    if not path.lower().endswith((".jpg", ".jpeg", ".tif", ".tiff")):
        raise ValueError("CMYK export writes JPEG or TIFF")
    src = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = src.constBits().tobytes()
    im = Image.frombytes("RGBA", (src.width(), src.height()), data)
    im = im.convert("RGB")
    srgb = ImageCms.createProfile("sRGB")
    try:
        cmyk = ImageCms.getOpenProfile(cmyk_icc)
        transform = ImageCms.buildTransform(srgb, cmyk, "RGB", "CMYK",
                                            renderingIntent=0)
    except (OSError, ImageCms.PyCMSError) as exc:
        raise ValueError(f"CMYK profile: {exc}") from exc
    out = ImageCms.applyTransform(im, transform)
    save_kwargs = {"quality": quality} if path.lower().endswith(
        (".jpg", ".jpeg")) else {}
    icc_bytes = pathlib_read(cmyk_icc)
    from photoslop.atomicio import atomic_write

    atomic_write(
        path,
        lambda temporary: out.save(
            temporary, icc_profile=icc_bytes, **save_kwargs),
    )

# SPDX-License-Identifier: Apache-2.0
"""Model-agnostic backend adapters for model-assisted features.

Photoslop never hardwires a model. Features like Select Subject and
Generative Fill route through a ModelAdapter, and users connect whatever
backend they run — a local ONNX server, ComfyUI behind a shim, a cloud
API — via the built-in generic HTTP adapter or a pip-installed plugin
registered under the ``photoslop.model_adapters`` entry-point group."""

from __future__ import annotations

import base64
import json
import urllib.request

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

SELECT_SUBJECT = "select-subject"
GENERATIVE_FILL = "generative-fill"
DENOISE = "denoise"


class ModelAdapter:
    """Base adapter. Subclasses set name/label and implement what they can."""

    name = "abstract"
    label = "Abstract adapter"

    def capabilities(self) -> frozenset[str]:
        return frozenset()

    def select_subject(self, image: QImage) -> QImage:
        """Return a Grayscale8 mask (white = subject) sized like image."""
        raise NotImplementedError

    def generative_fill(self, image: QImage, mask: QImage,
                        prompt: str) -> QImage:
        """Return a full replacement image; white mask marks the fill area."""
        raise NotImplementedError

    def denoise(self, image: QImage, strength: int) -> QImage:
        """Return a denoised replacement image (strength 1..100)."""
        raise NotImplementedError


def image_to_png_b64(img: QImage) -> str:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(bytes(buf.data())).decode("ascii")


def png_b64_to_image(data: str) -> QImage:
    img = QImage.fromData(base64.b64decode(data))
    if img.isNull():
        raise ValueError("backend returned data that is not a decodable PNG")
    return img


class HttpModelAdapter(ModelAdapter):
    """Generic JSON-over-HTTP adapter: point it at any server.

    POST {base}/select-subject   {"image": <b64 png>}                -> {"mask": <b64 png>}
    POST {base}/generative-fill  {"image":…, "mask":…, "prompt": ""} -> {"image": <b64 png>}
    POST {base}/denoise          {"image":…, "strength": 1..100}    -> {"image": <b64 png>}
    """

    name = "http"
    label = "Generic HTTP backend (JSON / base64 PNG)"

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def capabilities(self) -> frozenset[str]:
        return frozenset({SELECT_SUBJECT, GENERATIVE_FILL, DENOISE})

    def _post(self, op: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/{op}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())

    def select_subject(self, image: QImage) -> QImage:
        out = self._post(SELECT_SUBJECT, {"image": image_to_png_b64(image)})
        return png_b64_to_image(out["mask"])

    def generative_fill(self, image: QImage, mask: QImage,
                        prompt: str) -> QImage:
        out = self._post(GENERATIVE_FILL, {
            "image": image_to_png_b64(image),
            "mask": image_to_png_b64(mask),
            "prompt": prompt,
        })
        return png_b64_to_image(out["image"])

    def denoise(self, image: QImage, strength: int) -> QImage:
        out = self._post(DENOISE, {"image": image_to_png_b64(image),
                                   "strength": int(strength)})
        return png_b64_to_image(out["image"])


_REGISTRY: dict[str, type[ModelAdapter]] = {HttpModelAdapter.name: HttpModelAdapter}
_plugins_loaded = False


def register_adapter(cls: type[ModelAdapter]) -> None:
    _REGISTRY[cls.name] = cls


def available_adapters() -> dict[str, type[ModelAdapter]]:
    """Built-ins plus pip-installed plugins (photoslop.model_adapters)."""
    global _plugins_loaded
    if not _plugins_loaded:
        _plugins_loaded = True
        from importlib.metadata import entry_points

        for ep in entry_points(group="photoslop.model_adapters"):
            try:
                register_adapter(ep.load())
            except Exception:  # a broken plugin must not break the app
                continue
    return dict(_REGISTRY)


def create_adapter(name: str, settings: dict) -> ModelAdapter | None:
    cls = available_adapters().get(name)
    if cls is None:
        return None
    if cls is HttpModelAdapter:
        url = settings.get("url", "")
        return HttpModelAdapter(url) if url else None
    return cls()

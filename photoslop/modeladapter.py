# SPDX-License-Identifier: Apache-2.0
"""Model-agnostic backend adapters for model-assisted features.

Photoslop never hardwires a model. Features like Select Subject and
Generative Fill route through a ModelAdapter, and users connect whatever
backend they run — a local ONNX server, ComfyUI behind a shim, a cloud
API — via the built-in generic HTTP adapter or a pip-installed plugin
registered under the ``photoslop.model_adapters`` entry-point group."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import math
import traceback
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

from photoslop.resources import validate_dimensions

SELECT_SUBJECT = "select-subject"
GENERATIVE_FILL = "generative-fill"
DENOISE = "denoise"
MAX_MODEL_RESPONSE = 128 << 20


class ModelAdapter:
    """Base adapter. Subclasses set name/label and implement what they can."""

    name = "abstract"
    label = "Abstract adapter"
    unsafe = False

    def capabilities(self) -> frozenset[str]:
        return frozenset()

    def select_subject(self, image: QImage) -> QImage:
        """Return a Grayscale8 mask (white = subject) sized like image."""
        raise NotImplementedError

    def generative_fill(self, image: QImage, mask: QImage, prompt: str) -> QImage:
        """Return a full replacement image; white mask marks the fill area."""
        raise NotImplementedError

    def denoise(self, image: QImage, strength: int) -> QImage:
        """Return a denoised replacement image (strength 1..100)."""
        raise NotImplementedError


def image_to_png_b64(img: QImage) -> str:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not img.save(buf, "PNG"):
        raise ValueError("could not encode model input as PNG")
    return base64.b64encode(bytes(buf.data())).decode("ascii")


def png_b64_to_image(data: str) -> QImage:
    if not isinstance(data, str):
        raise ValueError("backend image payload must be base64 text")
    if len(data) > ((MAX_MODEL_RESPONSE + 2) // 3) * 4:
        raise ValueError("backend image payload is too large")
    try:
        decoded = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("backend returned invalid base64 image data") from exc
    if len(decoded) > MAX_MODEL_RESPONSE:
        raise ValueError("backend image payload is too large")
    img = QImage.fromData(decoded)
    if img.isNull():
        raise ValueError("backend returned data that is not a decodable PNG")
    validate_dimensions(img.width(), img.height(), operation="model response", buffers=2)
    return img


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_endpoint(url: str, *, allow_insecure_http: bool) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("model URL must use http:// or https:// with a host")
    if parsed.username or parsed.password:
        raise ValueError("model URL must not contain credentials")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname) and not allow_insecure_http:
        raise ValueError(
            "unencrypted HTTP model URLs are limited to loopback; "
            "explicitly allow insecure HTTP for a trusted local network"
        )


class HttpModelAdapter(ModelAdapter):
    """Generic JSON-over-HTTP adapter: point it at any server.

    POST {base}/select-subject   {"image": <b64 png>}                -> {"mask": <b64 png>}
    POST {base}/generative-fill  {"image":…, "mask":…, "prompt": ""} -> {"image": <b64 png>}
    POST {base}/denoise          {"image":…, "strength": 1..100}    -> {"image": <b64 png>}
    """

    name = "http"
    label = "Generic HTTP backend (JSON / base64 PNG)"

    def __init__(
        self, base_url: str, timeout: float = 120.0, *, allow_insecure_http: bool = False
    ) -> None:
        _validate_endpoint(base_url, allow_insecure_http=allow_insecure_http)
        if not math.isfinite(float(timeout)) or not 0 < float(timeout) <= 600:
            raise ValueError("model timeout must be in 0..600 seconds")
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.allow_insecure_http = allow_insecure_http

    def capabilities(self) -> frozenset[str]:
        return frozenset({SELECT_SUBJECT, GENERATIVE_FILL, DENOISE})

    def _post(self, op: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/{op}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Endpoint construction and every redirect target are scheme/host
        # validated by __init__ and below before response data is accepted.
        with urllib.request.urlopen(  # nosec B310
            req, timeout=self.timeout
        ) as resp:
            final_url = getattr(resp, "geturl", lambda: self.base_url)()
            _validate_endpoint(
                final_url,
                allow_insecure_http=self.allow_insecure_http,
            )
            content_type = resp.headers.get_content_type()
            if content_type != "application/json" and not content_type.endswith("+json"):
                raise ValueError("model backend response must be application/json")
            length = resp.headers.get("Content-Length")
            if length is not None and int(length) > MAX_MODEL_RESPONSE:
                raise ValueError("model backend response is too large")
            raw = resp.read(MAX_MODEL_RESPONSE + 1)
            if len(raw) > MAX_MODEL_RESPONSE:
                raise ValueError("model backend response is too large")
            try:
                result = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("model backend returned invalid JSON") from exc
            if not isinstance(result, dict):
                raise ValueError("model backend response must be a JSON object")
            return result

    @staticmethod
    def _image_field(result: dict, key: str) -> QImage:
        if key not in result:
            raise ValueError(f"model backend response is missing {key!r}")
        return png_b64_to_image(result[key])

    def select_subject(self, image: QImage) -> QImage:
        out = self._post(SELECT_SUBJECT, {"image": image_to_png_b64(image)})
        return self._image_field(out, "mask")

    def generative_fill(self, image: QImage, mask: QImage, prompt: str) -> QImage:
        out = self._post(
            GENERATIVE_FILL,
            {
                "image": image_to_png_b64(image),
                "mask": image_to_png_b64(mask),
                "prompt": prompt,
            },
        )
        return self._image_field(out, "image")

    def denoise(self, image: QImage, strength: int) -> QImage:
        out = self._post(DENOISE, {"image": image_to_png_b64(image), "strength": int(strength)})
        return self._image_field(out, "image")


_REGISTRY: dict[str, type[ModelAdapter]] = {HttpModelAdapter.name: HttpModelAdapter}
_plugins_loaded = False


@dataclass(frozen=True)
class PluginFailure:
    group: str
    name: str
    details: str


_PLUGIN_FAILURES: dict[tuple[str, str], PluginFailure] = {}


def register_adapter(cls: type[ModelAdapter]) -> None:
    _REGISTRY[cls.name] = cls


def available_adapters(*, allow_unsafe: bool = False) -> dict[str, type[ModelAdapter]]:
    """Built-ins plus explicitly enabled third-party adapter plugins."""
    global _plugins_loaded
    if allow_unsafe and not _plugins_loaded:
        _plugins_loaded = True
        from importlib.metadata import entry_points

        for ep in entry_points(group="photoslop.model_adapters"):
            try:
                cls = ep.load()
                cls.unsafe = True
                register_adapter(cls)
            except Exception:  # a broken plugin must not break the app
                key = ("photoslop.model_adapters", ep.name)
                _PLUGIN_FAILURES[key] = PluginFailure(key[0], key[1], traceback.format_exc())
                continue
    return {
        name: cls
        for name, cls in _REGISTRY.items()
        if allow_unsafe or not getattr(cls, "unsafe", False)
    }


def plugin_failures() -> tuple[PluginFailure, ...]:
    return tuple(_PLUGIN_FAILURES.values())


def create_adapter(name: str, settings: dict) -> ModelAdapter | None:
    cls = available_adapters(allow_unsafe=bool(settings.get("allow_unsafe_plugins", False))).get(
        name
    )
    if cls is None:
        return None
    if cls is HttpModelAdapter:
        url = settings.get("url", "")
        return (
            HttpModelAdapter(
                url,
                allow_insecure_http=bool(settings.get("allow_insecure_http", False)),
            )
            if url
            else None
        )
    return cls()

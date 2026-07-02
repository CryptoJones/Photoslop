# SPDX-License-Identifier: Apache-2.0
"""OpenRaster (.ora) save/load — the layered project format, interoperable
with GIMP and Krita. An .ora is a zip: mimetype, stack.xml, layer PNGs."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage

from photoslop.document import Document
from photoslop.layer import FORMAT, ORA_OPS, ORA_OPS_REVERSE, Layer

MIMETYPE = "image/openraster"


def _png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(buf.data())


def save_ora(doc: Document, path: str) -> None:
    image = ET.Element(
        "image",
        w=str(doc.size.width()),
        h=str(doc.size.height()),
        xres=str(int(round(doc.dpi))),
        yres=str(int(round(doc.dpi))),
        version="0.0.3",
    )
    if doc.artboards:
        import json

        image.set("photoslop-artboards", json.dumps(
            [[n, r.x(), r.y(), r.width(), r.height()]
             for n, r in doc.artboards]))
    stack = ET.SubElement(image, "stack")

    entries: list[tuple[str, bytes]] = []
    # ORA stores layers top-first; our list is bottom-first.
    for i, layer in enumerate(reversed(doc.layers)):
        src = f"data/layer{i}.png"
        attrib = {"composite-op": ORA_OPS.get(layer.blend_mode, "svg:src-over")}
        if layer.mask is not None:
            # Photoslop extension: ORA has no standard layer-mask entry.
            # GIMP/Krita ignore the attribute; Photoslop round-trips it.
            mask_src = f"data/layer{i}_mask.png"
            attrib["photoslop-mask"] = mask_src
            entries.append((mask_src, _png_bytes(layer.mask)))
        if layer.clipped:
            attrib["photoslop-clipped"] = "1"
        if layer.group:
            attrib["photoslop-group"] = layer.group
        if layer.adjustment is not None:
            adj_src = f"data/layer{i}_adj.bin"
            attrib["photoslop-adjustment"] = adj_src
            entries.append((adj_src, layer.adjustment.tobytes()))
        if layer.source is not None:
            source_src = f"data/layer{i}_source.png"
            attrib["photoslop-source"] = source_src
            entries.append((source_src, _png_bytes(layer.source)))
        if layer.smart_filters:
            import json

            attrib["photoslop-smart-filters"] = json.dumps(
                [list(f) for f in layer.smart_filters])
        ET.SubElement(
            stack,
            "layer",
            name=layer.name,
            src=src,
            x=str(layer.offset.x()),
            y=str(layer.offset.y()),
            opacity=f"{layer.opacity:.4f}",
            visibility="visible" if layer.visible else "hidden",
            attrib=attrib,
        )
        entries.append((src, _png_bytes(layer.image)))

    merged = doc.flatten()
    thumb = merged.scaled(
        QSize(256, 256), Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ) if max(merged.width(), merged.height()) > 256 else merged

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("mimetype")
        zf.writestr(info, MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("stack.xml", ET.tostring(image, encoding="utf-8", xml_declaration=True))
        for src, data in entries:
            zf.writestr(src, data)
        zf.writestr("mergedimage.png", _png_bytes(merged))
        zf.writestr("Thumbnails/thumbnail.png", _png_bytes(thumb))


def _walk_layers(zf: zipfile.ZipFile, node: ET.Element, base: QPoint, out: list[Layer]) -> None:
    """Collect layers depth-first, flattening nested stacks (groups) with
    accumulated offsets. XML order is top-first, so append order is too."""
    for child in node:
        if child.tag == "stack":
            off = base + QPoint(int(float(child.get("x", "0"))), int(float(child.get("y", "0"))))
            _walk_layers(zf, child, off, out)
        elif child.tag == "layer":
            src = child.get("src", "")
            img = QImage.fromData(zf.read(src)).convertToFormat(FORMAT)
            layer = Layer(
                child.get("name") or "Layer",
                img,
                base + QPoint(int(float(child.get("x", "0"))), int(float(child.get("y", "0")))),
                child.get("visibility", "visible") != "hidden",
                float(child.get("opacity", "1.0")),
                ORA_OPS_REVERSE.get(child.get("composite-op", "svg:src-over"), "normal"),
            )
            mask_src = child.get("photoslop-mask")
            if mask_src and mask_src in zf.namelist():
                layer.mask = QImage.fromData(zf.read(mask_src)).convertToFormat(
                    QImage.Format.Format_Grayscale8)
            layer.clipped = child.get("photoslop-clipped") == "1"
            layer.group = child.get("photoslop-group") or None
            source_src = child.get("photoslop-source")
            filters_json = child.get("photoslop-smart-filters")
            if source_src and source_src in zf.namelist():
                layer.source = QImage.fromData(
                    zf.read(source_src)).convertToFormat(FORMAT)
            if filters_json:
                import json

                layer.smart_filters = [tuple(f) for f in json.loads(filters_json)]
            adj_src = child.get("photoslop-adjustment")
            if adj_src and adj_src in zf.namelist():
                import numpy as np

                layer.adjustment = np.frombuffer(
                    zf.read(adj_src), dtype=np.uint8).reshape(3, 256).copy()
            out.append(layer)


def load_ora(path: str) -> Document:
    with zipfile.ZipFile(path, "r") as zf:
        root = ET.fromstring(zf.read("stack.xml"))
        w = int(root.get("w", "0"))
        h = int(root.get("h", "0"))
        dpi = float(root.get("xres", "72") or 72)

        top_first: list[Layer] = []
        _walk_layers(zf, root.find("stack"), QPoint(0, 0), top_first)

    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    doc = Document(QSize(w, h), dpi, name)
    doc.layers = list(reversed(top_first))  # internal order is bottom-first
    boards_json = root.get("photoslop-artboards")
    if boards_json:
        import json

        doc.artboards = [(n, QRect(x, y, w2, h2))
                         for n, x, y, w2, h2 in json.loads(boards_json)]
    doc.active_index = len(doc.layers) - 1
    doc.path = path
    return doc

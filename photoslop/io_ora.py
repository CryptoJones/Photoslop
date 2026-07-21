# SPDX-License-Identifier: Apache-2.0
"""OpenRaster (.ora) save/load — the layered project format, interoperable
with GIMP and Krita. An .ora is a zip: mimetype, stack.xml, layer PNGs."""

from __future__ import annotations

import os

# The stdlib module is used only to construct output; input parsing is defused.
import xml.etree.ElementTree as ET  # nosec B405
import zipfile

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage

from photoslop.atomicio import WriteTicket, atomic_write
from photoslop.document import Document
from photoslop.layer import FORMAT, ORA_OPS, ORA_OPS_REVERSE, Layer
from photoslop.resources import (
    DESKTOP_BUDGET,
    ResourceLimitError,
    parse_xml_limited,
    read_archive_member,
    validate_archive_members,
    validate_dimensions,
    validate_dpi,
)

MIMETYPE = "image/openraster"


def _png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(buf.data())


def save_ora(
    doc: Document, path: str, *, ticket: WriteTicket | None = None, before_commit=None
) -> None:
    def writer(temporary: str) -> None:
        _write_ora(doc, temporary)

    if ticket is None:
        atomic_write(path, writer, before_commit=before_commit, durable=True)
    else:
        ticket.write(writer, before_commit=before_commit, durable=True)


def _write_ora(doc: Document, path: str) -> None:
    image = ET.Element(
        "image",
        w=str(doc.size.width()),
        h=str(doc.size.height()),
        xres=str(int(round(doc.dpi))),
        yres=str(int(round(doc.dpi))),
        version="0.0.3",
        attrib={
            "photoslop-document-id": doc.document_id,
            "photoslop-name": doc.name,
        },
    )
    if doc.artboards:
        import json

        image.set(
            "photoslop-artboards",
            json.dumps([[n, r.x(), r.y(), r.width(), r.height()] for n, r in doc.artboards]),
        )
    if doc.icc_space is not None and doc.icc_space.isValid():
        import base64

        image.set(
            "photoslop-icc", base64.b64encode(bytes(doc.icc_space.iccProfile())).decode("ascii")
        )
    stack = ET.SubElement(image, "stack")

    entries: list[tuple[str, bytes]] = []
    # ORA stores layers top-first; our list is bottom-first.
    for i, layer in enumerate(reversed(doc.layers)):
        src = f"data/layer{i}.png"
        attrib = {
            "composite-op": ORA_OPS.get(layer.blend_mode, "svg:src-over"),
            "photoslop-id": layer.id,
        }
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

            attrib["photoslop-smart-filters"] = json.dumps([list(f) for f in layer.smart_filters])
        if layer.effects:
            import json

            from photoslop.appearance import normalize_effects

            attrib["photoslop-effects"] = json.dumps(
                normalize_effects(layer.effects), separators=(",", ":")
            )
        if layer.fill_opacity != 1.0:
            attrib["photoslop-fill-opacity"] = f"{layer.fill_opacity:.4f}"
        if layer.text_data:
            import json

            attrib["photoslop-text"] = json.dumps(layer.text_data)
        if layer.vector_data is not None:
            import json

            from photoslop.vector import migrate_vector

            attrib["photoslop-vector"] = json.dumps(migrate_vector(layer.vector_data))
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
    thumb = (
        merged.scaled(
            QSize(256, 256),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if max(merged.width(), merged.height()) > 256
        else merged
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("mimetype")
        zf.writestr(info, MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("stack.xml", ET.tostring(image, encoding="utf-8", xml_declaration=True))
        for src, data in entries:
            zf.writestr(src, data)
        zf.writestr("mergedimage.png", _png_bytes(merged))
        zf.writestr("Thumbnails/thumbnail.png", _png_bytes(thumb))


def _walk_layers(
    zf: zipfile.ZipFile,
    members: dict,
    node: ET.Element,
    base: QPoint,
    out: list[Layer],
    *,
    allow_large: bool,
) -> None:
    """Collect layers depth-first, flattening nested stacks (groups) with
    accumulated offsets. XML order is top-first, so append order is too."""
    if node is None:
        raise ValueError("OpenRaster: stack.xml has no stack")
    for child in node:
        if child.tag == "stack":
            off = base + QPoint(int(float(child.get("x", "0"))), int(float(child.get("y", "0"))))
            _walk_layers(zf, members, child, off, out, allow_large=allow_large)
        elif child.tag == "layer":
            if len(out) >= DESKTOP_BUDGET.max_layers:
                raise ResourceLimitError(
                    f"OpenRaster: maximum layer count is {DESKTOP_BUDGET.max_layers}"
                )
            src = child.get("src", "")
            if src not in members:
                raise ValueError(f"OpenRaster: missing layer member {src!r}")
            img = QImage.fromData(
                read_archive_member(zf, members[src], operation="OpenRaster layer")
            )
            if img.isNull():
                raise ValueError(f"OpenRaster: undecodable layer {src!r}")
            validate_dimensions(
                img.width(),
                img.height(),
                operation="OpenRaster layer",
                buffers=2,
                allow_large=allow_large,
            )
            img = img.convertToFormat(FORMAT)
            layer = Layer(
                child.get("name") or "Layer",
                img,
                base + QPoint(int(float(child.get("x", "0"))), int(float(child.get("y", "0")))),
                child.get("visibility", "visible") != "hidden",
                float(child.get("opacity", "1.0")),
                ORA_OPS_REVERSE.get(child.get("composite-op", "svg:src-over"), "normal"),
                child.get("photoslop-id"),
            )
            mask_src = child.get("photoslop-mask")
            if mask_src and mask_src in members:
                mask = QImage.fromData(
                    read_archive_member(zf, members[mask_src], operation="OpenRaster mask")
                )
                if mask.isNull() or mask.size() != img.size():
                    raise ValueError("OpenRaster: invalid layer mask")
                layer.mask = mask.convertToFormat(QImage.Format.Format_Grayscale8)
            layer.clipped = child.get("photoslop-clipped") == "1"
            layer.group = child.get("photoslop-group") or None
            source_src = child.get("photoslop-source")
            filters_json = child.get("photoslop-smart-filters")
            if source_src and source_src in members:
                source = QImage.fromData(
                    read_archive_member(
                        zf, members[source_src], operation="OpenRaster smart source"
                    )
                )
                if source.isNull():
                    raise ValueError("OpenRaster: invalid smart-object source")
                validate_dimensions(
                    source.width(),
                    source.height(),
                    operation="OpenRaster smart source",
                    buffers=2,
                    allow_large=allow_large,
                )
                layer.source = source.convertToFormat(FORMAT)
            if filters_json:
                import json

                layer.smart_filters = [tuple(f) for f in json.loads(filters_json)]
                layer.smart_filters_trusted = False
            effects_json = child.get("photoslop-effects")
            if effects_json:
                import json

                from photoslop.appearance import normalize_effects

                layer.effects = normalize_effects(json.loads(effects_json))
            fill = child.get("photoslop-fill-opacity")
            if fill:
                layer.fill_opacity = float(fill)
            text_json = child.get("photoslop-text")
            if text_json:
                import json

                layer.text_data = json.loads(text_json)
            vector_json = child.get("photoslop-vector")
            if vector_json:
                import json

                from photoslop.vector import migrate_vector

                layer.vector_data = migrate_vector(json.loads(vector_json))
            adj_src = child.get("photoslop-adjustment")
            if adj_src and adj_src in members:
                import numpy as np

                adjustment = read_archive_member(
                    zf, members[adj_src], operation="OpenRaster adjustment"
                )
                if len(adjustment) != 3 * 256:
                    raise ValueError("OpenRaster: invalid adjustment payload")
                layer.adjustment = np.frombuffer(adjustment, dtype=np.uint8).reshape(3, 256).copy()
            out.append(layer)


def load_ora(path: str, *, allow_large: bool = False) -> Document:
    if os.path.getsize(path) > DESKTOP_BUDGET.max_file_bytes:
        raise ResourceLimitError("OpenRaster: archive exceeds 1 GiB")
    with zipfile.ZipFile(path, "r") as zf:
        members = validate_archive_members(zf.infolist(), operation="OpenRaster")
        if "stack.xml" not in members:
            raise ValueError("OpenRaster: missing stack.xml")
        root = parse_xml_limited(
            read_archive_member(zf, members["stack.xml"], operation="OpenRaster stack.xml"),
            operation="OpenRaster",
        )
        w = int(root.get("w", "0"))
        h = int(root.get("h", "0"))
        dpi = float(root.get("xres", "72") or 72)
        validate_dimensions(w, h, operation="OpenRaster canvas", buffers=2, allow_large=allow_large)
        validate_dpi(dpi, operation="OpenRaster")

        top_first: list[Layer] = []
        _walk_layers(
            zf, members, root.find("stack"), QPoint(0, 0), top_first, allow_large=allow_large
        )

    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    doc = Document(QSize(w, h), dpi, name)
    doc.embedded_name = root.get("photoslop-name") or name
    document_id = root.get("photoslop-document-id", "")
    if len(document_id) == 32 and all(char in "0123456789abcdef" for char in document_id):
        doc.document_id = document_id
    doc.layers = list(reversed(top_first))  # internal order is bottom-first
    icc_b64 = root.get("photoslop-icc")
    if icc_b64:
        import base64

        from PySide6.QtGui import QColorSpace

        space = QColorSpace.fromIccProfile(base64.b64decode(icc_b64))
        if space.isValid():
            doc.icc_space = space
    boards_json = root.get("photoslop-artboards")
    if boards_json:
        import json

        doc.artboards = [(n, QRect(x, y, w2, h2)) for n, x, y, w2, h2 in json.loads(boards_json)]
    doc.active_index = len(doc.layers) - 1
    doc.path = path
    return doc

# SPDX-License-Identifier: Apache-2.0
"""Central resource limits for documents and untrusted input.

Hard geometry and parser limits are never bypassed.  The desktop-only
``allow_large`` switch relaxes the estimated working-set guard so a user can
open a legitimate large local document deliberately; MCP callers never expose
that switch.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import PurePosixPath

from defusedxml import ElementTree as SafeET


class ResourceLimitError(ValueError):
    """Input would exceed a documented Photoslop resource boundary."""


@dataclass(frozen=True)
class ResourceBudget:
    max_dimension: int = 32_768
    max_pixels: int = 268_435_456
    max_working_bytes: int = 0
    max_file_bytes: int = 1 << 30
    max_archive_bytes: int = 4 << 30
    max_entry_bytes: int = 1 << 30
    max_archive_entries: int = 4096
    max_compression_ratio: float = 100.0
    max_layers: int = 2048
    max_xml_bytes: int = 16 << 20
    max_xml_nodes: int = 250_000
    max_xml_depth: int = 64


def _physical_memory() -> int:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return pages * page_size
    except (AttributeError, OSError, TypeError, ValueError):
        return 4 << 30


DESKTOP_BUDGET = ResourceBudget(
    max_working_bytes=min(4 << 30, int(_physical_memory() * 0.60)),
)
IPAD_BUDGET = ResourceBudget(
    max_dimension=16_384,
    max_pixels=100_000_000,
    max_working_bytes=min(1 << 30, int(_physical_memory() * 0.35)),
)


def validate_dimensions(
    width: int,
    height: int,
    *,
    operation: str = "document",
    buffers: int = 1,
    allow_large: bool = False,
    budget: ResourceBudget = DESKTOP_BUDGET,
) -> None:
    """Validate canvas geometry before allocating pixel buffers."""
    if isinstance(width, bool) or isinstance(height, bool):
        raise ResourceLimitError(f"{operation}: invalid dimensions")
    width, height = int(width), int(height)
    if width < 1 or height < 1:
        raise ResourceLimitError(f"{operation}: dimensions must be positive")
    if width > budget.max_dimension or height > budget.max_dimension:
        raise ResourceLimitError(
            f"{operation}: maximum dimension is {budget.max_dimension:,} px")
    pixels = width * height
    if pixels > budget.max_pixels:
        raise ResourceLimitError(
            f"{operation}: maximum canvas area is {budget.max_pixels:,} pixels")
    projected = pixels * 4 * max(1, int(buffers))
    if not allow_large and projected > budget.max_working_bytes:
        raise ResourceLimitError(
            f"{operation}: estimated working set {projected / (1 << 30):.1f} GiB "
            f"exceeds the {budget.max_working_bytes / (1 << 30):.1f} GiB limit; "
            "use the local --allow-large-document override if this file is trusted")


def validate_dpi(dpi: float, *, operation: str = "document") -> None:
    if not math.isfinite(float(dpi)) or not 1 <= float(dpi) <= 2400:
        raise ResourceLimitError(f"{operation}: DPI must be in 1..2400")


def read_limited(path: str, maximum: int, *, operation: str) -> bytes:
    size = os.path.getsize(path)
    if size > maximum:
        raise ResourceLimitError(
            f"{operation}: file is {size:,} bytes; maximum is {maximum:,}")
    with open(path, "rb") as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ResourceLimitError(f"{operation}: input exceeds {maximum:,} bytes")
    return data


def parse_xml_limited(
    source: bytes,
    *,
    operation: str,
    budget: ResourceBudget = DESKTOP_BUDGET,
):
    """Parse XML with entity/DTD protection plus node/depth limits."""
    if len(source) > budget.max_xml_bytes:
        raise ResourceLimitError(
            f"{operation}: XML exceeds {budget.max_xml_bytes:,} bytes")
    try:
        root = SafeET.fromstring(source)
    except Exception as exc:
        raise ValueError(f"{operation}: invalid or unsafe XML: {exc}") from exc
    count = 0
    stack = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > budget.max_xml_nodes:
            raise ResourceLimitError(
                f"{operation}: XML exceeds {budget.max_xml_nodes:,} nodes")
        if depth > budget.max_xml_depth:
            raise ResourceLimitError(
                f"{operation}: XML nesting exceeds {budget.max_xml_depth}")
        stack.extend((child, depth + 1) for child in node)
    return root


def validate_archive_members(infos, *, operation: str = "archive",
                             budget: ResourceBudget = DESKTOP_BUDGET) -> dict:
    """Validate ZIP metadata before reading any member bytes."""
    infos = list(infos)
    if len(infos) > budget.max_archive_entries:
        raise ResourceLimitError(
            f"{operation}: archive has too many entries ({len(infos)})")
    total = 0
    by_name = {}
    for info in infos:
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if (not name or name.startswith("/") or ".." in path.parts
                or path.is_absolute()):
            raise ResourceLimitError(f"{operation}: unsafe member path {name!r}")
        if name in by_name:
            raise ResourceLimitError(f"{operation}: duplicate member {name!r}")
        if info.flag_bits & 0x1:
            raise ResourceLimitError(f"{operation}: encrypted entries are unsupported")
        if info.file_size > budget.max_entry_bytes:
            raise ResourceLimitError(f"{operation}: member {name!r} is too large")
        ratio = info.file_size / max(1, info.compress_size)
        if ratio > budget.max_compression_ratio:
            raise ResourceLimitError(
                f"{operation}: suspicious compression ratio for {name!r}")
        total += info.file_size
        if total > budget.max_archive_bytes:
            raise ResourceLimitError(f"{operation}: expanded archive is too large")
        by_name[name] = info
    return by_name


def read_archive_member(zf, info, *, operation: str,
                        budget: ResourceBudget = DESKTOP_BUDGET) -> bytes:
    maximum = min(info.file_size, budget.max_entry_bytes)
    with zf.open(info, "r") as handle:
        data = handle.read(maximum + 1)
    if len(data) != info.file_size or len(data) > budget.max_entry_bytes:
        raise ResourceLimitError(f"{operation}: member size changed while reading")
    return data

# SPDX-License-Identifier: Apache-2.0
"""Model Context Protocol (MCP) server — Photoslop's engine as agent tools.

The same headless engine as ``photoslop-cli``, exposed over MCP so an LLM/agent
can drive the editor: load an image (or start blank), run an ordered pipeline of
operations, and write the result. Safe operations are derived from the CLI's
``OPS`` table; network-model operations and unsafe plugins stay local-only.

Run it (stdio transport, the MCP default)::

    photoslop-mcp            # console script
    python -m photoslop.server

The tool functions below are plain Python and unit-testable on their own; the
``mcp`` package is only needed to actually serve them (``build_server``/``main``),
so it is an optional dependency (``photoslop[mcp]``).
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from photoslop import __version__, cli

# A tool value the model can pass for a flag-style op (e.g. auto-levels),
# which take no argument.
_FLAG = ""
_BLOCKED_OPS = frozenset({
    "model-url", "select-subject", "generative-fill", "denoise-model",
})
_PATH_VALUE_OPS = frozenset({
    "assign-profile", "convert-profile", "proof", "cmyk-out",
})


@dataclass(frozen=True)
class PathPolicy:
    root: Path
    allow_overwrite: bool = False

    @classmethod
    def create(cls, root: str | os.PathLike[str],
               *, allow_overwrite: bool = False) -> PathPolicy:
        resolved = Path(root).expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError(f"MCP root is not a directory: {resolved}")
        return cls(resolved, allow_overwrite)

    def _resolve(self, value: str, *, purpose: str) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                f"{purpose} must stay under MCP root {self.root}") from exc
        return resolved

    def input(self, value: str, *, purpose: str = "input") -> str:
        resolved = self._resolve(value, purpose=purpose)
        if not resolved.is_file():
            raise ValueError(f"{purpose} is not a file: {resolved}")
        return str(resolved)

    def output(self, value: str, *, purpose: str = "output") -> str:
        resolved = self._resolve(value, purpose=purpose)
        parent = resolved.parent.resolve(strict=False)
        try:
            parent.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                f"{purpose} must stay under MCP root {self.root}") from exc
        if resolved.exists() and not self.allow_overwrite:
            raise ValueError(
                f"{purpose} already exists; MCP overwrite is disabled: {resolved}")
        return str(resolved)

    def directory(self, value: str, *, purpose: str) -> str:
        resolved = self._resolve(value, purpose=purpose)
        if resolved.exists() and not resolved.is_dir():
            raise ValueError(f"{purpose} is not a directory: {resolved}")
        if (resolved.exists() and any(resolved.iterdir())
                and not self.allow_overwrite):
            raise ValueError(
                f"{purpose} is not empty; MCP overwrite is disabled: {resolved}")
        return str(resolved)


_POLICY = PathPolicy.create(os.getcwd())


def configure(*, root: str | os.PathLike[str],
              allow_overwrite: bool = False) -> PathPolicy:
    """Set the filesystem sandbox used by the exposed MCP tool functions."""
    global _POLICY
    _POLICY = PathPolicy.create(root, allow_overwrite=allow_overwrite)
    return _POLICY


def list_operations() -> dict:
    """Every editing operation the pipeline understands.

    Returns ``{"count": N, "operations": [...]}`` where each entry has ``name``
    (pass as an operation's ``op``), ``args`` (the value format, or ``null`` for
    a no-argument flag op), and ``help``. Mirrors ``photoslop-cli --help``
    from the same ``OPS`` table, minus local-only network model operations.
    """
    operations = [
        {"name": name, "args": metavar, "help": help_text}
        for name, (metavar, help_text, _fn) in cli.OPS.items()
        if name not in _BLOCKED_OPS
    ]
    return {"count": len(operations), "operations": operations}


def _normalise_ops(operations: list[dict] | None) -> list[tuple[str, str]]:
    """Turn ``[{"op": "resize", "value": "800x600"}, ...]`` into the
    ``(name, value)`` pairs ``apply_pipeline`` wants."""
    pairs: list[tuple[str, str]] = []
    for i, entry in enumerate(operations or []):
        if not isinstance(entry, dict) or "op" not in entry:
            raise ValueError(
                f"operations[{i}] must be an object with an 'op' key, e.g. "
                '{"op": "resize", "value": "800x600"}')
        name = str(entry["op"])
        if name in _BLOCKED_OPS:
            raise ValueError(f"operation {name!r} is not exposed through MCP")
        value = str(entry.get("value", _FLAG))
        if name in _PATH_VALUE_OPS and value.lower().endswith(".icc"):
            value = _POLICY.input(value, purpose=f"{name} profile")
        pairs.append((name, value))
    return pairs


def edit_image(
    operations: list[dict],
    input: str | None = None,
    new: str | None = None,
    dpi: int = 72,
    output: str | None = None,
    info: bool = False,
    export_artboards: str | None = None,
) -> dict:
    """Load an image (or start blank), apply an ordered pipeline, write output.

    Operations compose left to right, exactly like ``photoslop-cli``. Provide
    either ``input`` (a PNG/JPG/ORA/camera-raw path) or ``new`` (``"WxH"`` or a
    paper preset like ``"A4"`` at ``dpi``) — not both. Ask for a result with at
    least one of ``output`` (``.ora`` keeps layers; raster extensions flatten),
    ``info`` (document JSON), or ``export_artboards`` (a directory).

    ``operations`` is a list of ``{"op": NAME, "value": STR}`` objects; call
    ``list_operations`` for the catalog. Flag ops take ``"value": ""``.

    Example — resize then auto-level a photo and save a PNG::

        edit_image(input="shot.jpg", output="out.png", operations=[
            {"op": "resize", "value": "1600x1067"},
            {"op": "auto-levels", "value": ""},
        ])
    """
    if input and new:
        raise ValueError("give an input file or new, not both")
    confined_input = _POLICY.input(input) if input else None
    confined_output = _POLICY.output(output) if output else None
    confined_artboards = (_POLICY.directory(
        export_artboards, purpose="artboard export directory")
        if export_artboards else None)
    return cli.apply_pipeline(
        input_path=confined_input,
        new=new,
        dpi=dpi,
        operations=_normalise_ops(operations),
        output=confined_output,
        info=info,
        export_artboards=confined_artboards,
    )


def document_info(input: str) -> dict:
    """Inspect an image without editing it: size, dpi, and per-layer metadata
    (name, visibility, opacity, blend mode, offset, effects, smart-object,
    native vector ID/type) plus
    any artboards. Read-only — nothing is written."""
    return cli.apply_pipeline(
        input_path=_POLICY.input(input), info=True)["info"]


def build_server(*, root: str | os.PathLike[str] | None = None,
                 allow_overwrite: bool = False):
    """Construct the FastMCP server with the three tools registered.

    Needs the optional ``mcp`` dependency (``pip install 'photoslop[mcp]'``)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "photoslop-mcp needs the MCP SDK: install with "
            "'pip install \"photoslop[mcp]\"' (or 'uv sync --extra mcp')."
        ) from exc

    configure(root=root or os.getcwd(), allow_overwrite=allow_overwrite)
    server = FastMCP(
        "photoslop",
        instructions=(
            "Photoslop image editor as tools. Call list_operations to discover "
            "the pipeline op catalog, then edit_image to load/create an image, "
            "apply an ordered safe pipeline, and write output. All paths are "
            f"confined to {_POLICY.root}; existing outputs are "
            f"{'allowed' if _POLICY.allow_overwrite else 'protected'}. "
            "Network model operations and unsafe plugins are unavailable. "
            f"document_info inspects a file read-only. Engine version {__version__}."
        ),
    )
    server.tool()(list_operations)
    server.tool()(edit_image)
    server.tool()(document_info)
    return server


def main() -> None:
    """Console entry point: serve over stdio (the MCP default transport)."""
    parser = argparse.ArgumentParser(prog="photoslop-mcp")
    parser.add_argument(
        "--root", default=os.getcwd(),
        help="filesystem root visible to tools (default: current directory)")
    parser.add_argument(
        "--allow-overwrite", action="store_true",
        help="permit tools to replace existing outputs under --root")
    args = parser.parse_args()
    build_server(root=args.root, allow_overwrite=args.allow_overwrite).run()


if __name__ == "__main__":
    main()

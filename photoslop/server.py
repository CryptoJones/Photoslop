# SPDX-License-Identifier: Apache-2.0
"""Model Context Protocol (MCP) server — Photoslop's engine as agent tools.

The same headless engine as ``photoslop-cli``, exposed over MCP so an LLM/agent
can drive the editor: load an image (or start blank), run an ordered pipeline of
operations, and write the result. Every operation is the CLI's ``OPS`` table
verbatim, so the MCP surface has exactly the CLI's feature parity — nothing to
keep in sync by hand.

Run it (stdio transport, the MCP default)::

    photoslop-mcp            # console script
    python -m photoslop.server

The tool functions below are plain Python and unit-testable on their own; the
``mcp`` package is only needed to actually serve them (``build_server``/``main``),
so it is an optional dependency (``photoslop[mcp]``).
"""

from __future__ import annotations

from photoslop import __version__, cli

# A tool value the model can pass for a flag-style op (e.g. auto-levels),
# which take no argument.
_FLAG = ""


def list_operations() -> dict:
    """Every editing operation the pipeline understands.

    Returns ``{"count": N, "operations": [...]}`` where each entry has ``name``
    (pass as an operation's ``op``), ``args`` (the value format, or ``null`` for
    a no-argument flag op), and ``help``. Mirrors ``photoslop-cli --help``
    exactly (same ``OPS`` table).
    """
    operations = [
        {"name": name, "args": metavar, "help": help_text}
        for name, (metavar, help_text, _fn) in cli.OPS.items()
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
        pairs.append((str(entry["op"]), str(entry.get("value", _FLAG))))
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
    return cli.apply_pipeline(
        input_path=input,
        new=new,
        dpi=dpi,
        operations=_normalise_ops(operations),
        output=output,
        info=info,
        export_artboards=export_artboards,
    )


def document_info(input: str) -> dict:
    """Inspect an image without editing it: size, dpi, and per-layer metadata
    (name, visibility, opacity, blend mode, offset, effects, smart-object) plus
    any artboards. Read-only — nothing is written."""
    return cli.apply_pipeline(input_path=input, info=True)["info"]


def build_server():
    """Construct the FastMCP server with the three tools registered.

    Needs the optional ``mcp`` dependency (``pip install 'photoslop[mcp]'``)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "photoslop-mcp needs the MCP SDK: install with "
            "'pip install \"photoslop[mcp]\"' (or 'uv sync --extra mcp')."
        ) from exc

    server = FastMCP(
        "photoslop",
        instructions=(
            "Photoslop image editor as tools. Call list_operations to discover "
            "the pipeline op catalog, then edit_image to load/create an image, "
            "apply an ordered pipeline, and write output. document_info inspects "
            f"a file read-only. Engine version {__version__}."
        ),
    )
    server.tool()(list_operations)
    server.tool()(edit_image)
    server.tool()(document_info)
    return server


def main() -> None:
    """Console entry point: serve over stdio (the MCP default transport)."""
    build_server().run()


if __name__ == "__main__":
    main()

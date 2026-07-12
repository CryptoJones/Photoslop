# MCP Server — `photoslop-mcp`

Photoslop's headless engine exposed over the **[Model Context Protocol](https://modelcontextprotocol.io)**,
so an LLM/agent (Claude Desktop, Claude Code, any MCP client) can drive the
editor: load an image, apply an ordered pipeline of operations, and write the
result — the same engine as [`photoslop-cli`](cli.md), same operations, same
parity promise.

## Install & run

The server needs the optional `mcp` extra:

```bash
pip install "photoslop[mcp]"     # or: uv sync --extra mcp
photoslop-mcp                    # serves over stdio (the MCP default)
```

Equivalently `python -m photoslop.server`. It is headless-safe (forces Qt's
offscreen platform), so it runs over SSH and in CI.

## Register with a client

Point any MCP client at the `photoslop-mcp` command. For Claude Desktop /
Claude Code, add it to the MCP servers config:

```json
{
  "mcpServers": {
    "photoslop": {
      "command": "photoslop-mcp"
    }
  }
}
```

(Use an absolute path to the console script, or `uv run --with "photoslop[mcp]"
photoslop-mcp`, if it is not on the client's `PATH`.)

## Tools

| Tool | What it does |
|---|---|
| `list_operations` | The full operation catalog — `{count, operations:[{name, args, help}]}`. Same table as `photoslop-cli --help`; call it first to discover ops. |
| `edit_image` | Load an image (or start blank), apply an ordered pipeline, write output and/or return document info. |
| `document_info` | Read-only inspect: size, dpi, per-layer/vector metadata, ordered artboards. Nothing is written. |

### `edit_image`

| Param | Type | Notes |
|---|---|---|
| `operations` | list of `{op, value}` | ordered pipeline; composes left to right. `value: ""` for flag ops. |
| `input` | string | source path (PNG/JPG/ORA/camera-raw). Mutually exclusive with `new`. |
| `new` | string | `"WxH"` (e.g. `800x600`) or a paper preset (`A5`/`A4`/`A3`/`Letter`/`Legal`). |
| `dpi` | int | resolution for `new` presets (default 72). `A4` @ 300 → 2480×3508. |
| `output` | string | write path — `.ora` keeps layers; raster extensions flatten. |
| `info` | bool | also return the document JSON. |
| `export_artboards` | string | directory; writes each artboard as `<name>.png`. |

Give at least one of `output`, `info`, or `export_artboards` — otherwise there
is nothing to return and the call errors (mirrors the CLI).

Operations are the CLI's `OPS` table verbatim — `resize`, `crop`, `levels`,
`curves`, `gaussian-blur`, `filter`, `select`/`feather`, `generative-fill`,
`text`, `shape`, and the rest. See [Command Line](cli.md) for the full list and
each op's value format, or call `list_operations`.

### Example (client call)

Resize a photo, auto-level it, then save a PNG:

```json
{
  "name": "edit_image",
  "arguments": {
    "input": "shot.jpg",
    "output": "out.png",
    "operations": [
      {"op": "resize", "value": "1600x1067"},
      {"op": "auto-levels", "value": ""}
    ]
  }
}
```

Model-backed ops (`generative-fill`, `select-subject`, `denoise-model`) route
through the same bring-your-own-model adapter as the app and CLI — set the
backend with a `{"op": "model-url", "value": "http://…"}` step first. See
[Model Backends](model-backends.md).

## Parity

The MCP server is a thin surface over `photoslop.cli.apply_pipeline`, which
reuses the exact `OPS` table the CLI exposes. There is nothing to keep in sync
by hand: a new CLI operation is automatically an MCP operation. This is the same
"every GUI engine feature is exposed headless" promise the CLI makes.

Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>

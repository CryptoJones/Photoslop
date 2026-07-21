# MCP Server — `photoslop-mcp`

Photoslop's headless engine exposed over the **[Model Context Protocol](https://modelcontextprotocol.io)**,
so an LLM/agent (Claude Desktop, Claude Code, any MCP client) can drive the
editor: load an image, apply an ordered pipeline of operations, and write the
result — the same engine as [`photoslop-cli`](cli.md), with local-only unsafe
plugins and network-model operations deliberately removed from the agent surface.

## Install & run

The server needs the optional `mcp` extra:

```bash
pip install "photoslop[mcp]"     # or: uv sync --extra mcp
photoslop-mcp --root /path/to/images   # serves over stdio
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
      "command": "photoslop-mcp",
      "args": ["--root", "/path/to/images"]
    }
  }
}
```

(Use an absolute path to the console script, or `uv run --with "photoslop[mcp]"
photoslop-mcp`, if it is not on the client's `PATH`.)

## Tools

| Tool | What it does |
|---|---|
| `list_operations` | The safe operation catalog — `{count, operations:[{name, args, help}]}`; call it first to discover ops. |
| `edit_image` | Load an image (or start blank), apply an ordered pipeline, write output and/or return document info. |
| `document_info` | Read-only inspect: size, dpi, per-layer/vector metadata, ordered artboards. Nothing is written. |

### `edit_image`

| Param | Type | Notes |
|---|---|---|
| `operations` | list of `{op, value}` | ordered pipeline; composes left to right. `value: ""` for flag ops. |
| `input` | string | source path under the configured server root. Mutually exclusive with `new`. |
| `new` | string | `"WxH"` (e.g. `800x600`) or a paper preset (`A5`/`A4`/`A3`/`Letter`/`Legal`). |
| `dpi` | int | resolution for `new` presets (default 72). `A4` @ 300 → 2480×3508. |
| `output` | string | write path under the server root — `.ora` keeps layers; raster extensions flatten. Existing files are protected by default. |
| `info` | bool | also return the document JSON. |
| `export_artboards` | string | directory; writes each artboard as `<name>.png`. |

Give at least one of `output`, `info`, or `export_artboards` — otherwise there
is nothing to return and the call errors (mirrors the CLI).

Operations are derived from the CLI's `OPS` table — `resize`, `crop`, `levels`,
`curves`, `gaussian-blur`, safe built-in `filter` values, `select`/`feather`,
`text`, `shape`, and the rest. Call `list_operations` for the authoritative
surface.

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

The server confines resolved paths (including symlink targets) to `--root`,
rejects existing outputs and non-empty export directories, and never exposes
network model operations or native/third-party plugins. A trusted operator can
add `--allow-overwrite`; hard resource and parser limits still apply.

## Parity

The MCP server is a policy layer over `photoslop.cli.apply_pipeline`. It derives
its catalog from the CLI table, then denies local-only capabilities before any
document is opened.

Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>

# MCP Server — `photoslop-mcp`

Photoslop's headless engine exposed over the **[Model Context Protocol](https://modelcontextprotocol.io)**,
so an LLM/agent (Claude Desktop, Claude Code, any MCP client) can drive the
editor: load an image, apply an ordered pipeline of operations, and write the
result — the same engine as [`photoslop-cli`](cli.md), with local-only unsafe
plugins and network-model operations deliberately removed from the agent surface.

## Install & run

The server needs the optional `mcp` extra, which pulls the MCP SDK 2.x:

```bash
pip install "photoslop[mcp]"     # or: uv sync --extra mcp
photoslop-mcp --root /path/to/images   # serves over stdio
```

Equivalently `python -m photoslop.server`. It is headless-safe (forces Qt's
offscreen platform), so it runs over SSH and in CI.

## Transports

`--transport` selects how the server is reached. stdio is the default because it
needs no listener at all — the client spawns the process and talks over its
pipes, so nothing is exposed to the network.

| Transport | Use it for |
| --- | --- |
| `stdio` *(default)* | A client that launches the server itself, such as Claude Desktop |
| `streamable-http` | A long-running server several clients connect to |
| `sse` | Older clients predating Streamable HTTP |

```bash
photoslop-mcp --transport streamable-http --port 8000 --root /path/to/images
```

`--host` defaults to `127.0.0.1`, so an HTTP server is reachable only from the
same machine until that is deliberately widened. Host and port are transport
arguments in the 2.x SDK rather than server settings; passing them to the server
itself is accepted and quietly ignored, which would bind the default port while
the flags looked honoured. Bear in mind what widening it
means: `--root` is the only thing confining tool calls to a directory, and over
HTTP that boundary becomes reachable by anything that can open a socket to the
port. The server prints the transport, address, and active root on startup so
the exposure is stated rather than assumed.

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

From a portable build there is no install step — point `command` at the wrapper
inside the archive:

- macOS: `Photoslop.app/Contents/Resources/bin/photoslop-mcp`
- Windows: `Photoslop\photoslop-mcp.cmd`

See [distribution.md](distribution.md) for why the wrappers sit where they do.

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

Tool failures begin with a stable bracketed code and also expose that code on
the Python exception used by direct integrations: `invalid_input`,
`unsupported_capability`, `unsafe_operation`, `cancelled`, `io_failure`, or
`internal_error`. Clients should branch on the code and treat the following
message as human guidance.

## Parity

The MCP server is a policy layer over `photoslop.cli.apply_pipeline`. It derives
its catalog from the CLI table, then denies local-only capabilities before any
document is opened.

Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>

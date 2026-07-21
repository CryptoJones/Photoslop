# Security and Resource Boundaries

Photoslop treats image files, XML, archives, model responses, plugin code, and
agent requests as separate trust boundaries.

## Documents and parsers

- Desktop canvases are capped at 32,768 px per side and 268,435,456 pixels.
- The adaptive desktop working-set estimate is the smaller of 4 GiB and 60% of
  physical memory. A local user may bypass that estimate for a trusted file;
  hard caps are never bypassed.
- ORA archives are checked before extraction for traversal, duplicate/encrypted
  entries, entry count, compressed/uncompressed size, compression ratio, layer
  count, and decoded image geometry.
- ORA and SVG XML reject DTD/entity expansion and are limited to 16 MiB,
  250,000 nodes, and 64 levels of nesting.
- SVG external file/network resources are rejected. Embedded PNGs and recursively
  validated data-SVGs are allowed; unsupported path syntax is never silently
  discarded.

## Code and network execution

Built-in filters are safe by default. Native G'MIC/GEGL/GIMP packs, third-party
filter entry points, and third-party model adapters require the local unsafe
plugin opt-in. Imported smart-filter recipes require a separate trust prompt
before replay.

The generic model adapter accepts HTTPS, plus plain HTTP on loopback. Remote
plain HTTP requires an explicit local opt-in. Redirect destinations, response
content type and schema, response/body size, base64, decoded image validity, and
output dimensions are validated.

## MCP

`photoslop-mcp --root DIR` resolves all input, output, ICC-profile, and artboard
paths beneath `DIR`, including symlink targets. Existing outputs and non-empty
export directories are protected unless the server operator starts it with
`--allow-overwrite`. MCP never exposes network-model operations, unsafe plugins,
large-document overrides, or insecure-HTTP overrides.


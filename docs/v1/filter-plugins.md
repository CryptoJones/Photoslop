# Filter Plugins

Photoslop discovers filters from the **`photoslop.filters` entry-point
group** — the same architecture as [model backends](model-backends.md). A
pip-installed plugin appears in the **Filter menu** (with an auto-generated
parameter dialog), works in the **CLI** as `--filter "name:key=val,..."`,
respects **selections and feathering**, participates in **actions** and
**smart-filter replay** — all from one class and one entry point.

Two built-ins ship in the box and double as living documentation:
**Sepia** (`sepia:amount=0..100`) and **Pixelate** (`pixelate:size=2..128`).

## The contract

```python
from photoslop.filters import Filter, ParamSpec

class MyFilter(Filter):
    name = "my-filter"          # kebab-case, unique — CLI + replay identity
    label = "My Filter"         # menu text
    params = (
        ParamSpec("amount", "Amount", "int", 0, 100, 50),
        #         key       label     type  min  max  default
    )

    def apply(self, image, params):   # QImage, dict -> edit in place
        ...
```

- `apply` edits the QImage **in place**; it receives a transient per-layer
  copy — never the resident buffer — so selections, feather blending, and
  undo happen outside the plugin (you write zero Qt UI and zero undo code).
- `params` arrives validated against your `ParamSpec`s: the GUI builds
  spinboxes from them, the CLI parses `key=val` against them, and both
  reject out-of-range values before your code runs.
- Buffers are **premultiplied ARGB32**; use
  `photoslop.npimage.view_u32(image)` for a zero-copy numpy view.

## Packaging

```toml
[project.entry-points."photoslop.filters"]
my-filter = "my_package:MyFilter"
```

A complete installable reference plugin lives in
[`examples/photoslop-invert-filter/`](https://github.com/CryptoJones/Photoslop/tree/main/examples/photoslop-invert-filter)
— `pip install .` in that directory and **Invert** appears in the Filter
menu and the CLI.

For quick experiments (or tests), skip packaging:

```python
from photoslop.filters import register_filter
register_filter(MyFilter)
```

## CLI

```bash
photoslop-cli in.png --filter "sepia:amount=100" --output toned.png
photoslop-cli in.png --select 0,0,400,300 --feather 8 \
                     --filter "pixelate:size=12" --output redacted.png
photoslop-cli in.png --filter sepia --output toned.png   # defaults
```

Unknown names exit 2 listing the installed filters; parameter errors name
the offending key and its valid range.

## Memory notes (DD-001)

The framework itself holds no image memory — the registry stores classes.
Each run costs the same transient copy every built-in filter already pays.
A plugin that allocates wildly is the plugin's bug, not the host's; keep
per-pixel work chunked (see `CHUNK_ROWS` in `photoslop/adjust.py` for the
house pattern).

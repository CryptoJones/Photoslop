# SPDX-License-Identifier: Apache-2.0
"""Standalone GEGL worker — runs in whatever python has gi + Gegl (often
the SYSTEM interpreter, not Photoslop's venv), so it must import nothing
beyond the stdlib and gi. Invoked as:

    python3 _gegl_helper.py in.png out.png gegl:operation '{"prop": 1.5}'

Exit 0 on success; error text on stderr otherwise."""

import json
import sys


def apply_gegl(src: str, dst: str, operation: str, props: dict) -> None:
    import gi

    gi.require_version("Gegl", "0.4")
    from gi.repository import Gegl

    Gegl.init(None)
    if operation not in set(Gegl.list_operations()):
        raise SystemExit(f"unknown GEGL operation: {operation}")
    graph = Gegl.Node()
    loader = graph.create_child("gegl:png-load")
    loader.set_property("path", src)
    op = graph.create_child(operation)
    for key, value in props.items():
        try:
            op.set_property(key, value)
        except Exception as exc:  # unknown/uncoercible property
            raise SystemExit(f"property {key!r}: {exc}") from exc
    saver = graph.create_child("gegl:png-save")
    saver.set_property("path", dst)
    saver.set_property("bitdepth", 8)
    loader.connect_to("output", op, "input")
    op.connect_to("output", saver, "input")
    saver.process()


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: _gegl_helper.py IN OUT OPERATION PROPS_JSON", file=sys.stderr)
        return 2
    src, dst, operation, props_json = sys.argv[1:]
    try:
        apply_gegl(src, dst, operation, json.loads(props_json))
    except SystemExit:
        raise
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

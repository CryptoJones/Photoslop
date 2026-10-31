# SPDX-License-Identifier: Apache-2.0
"""Adversarial inputs for every CLI op, every filter parameter and every format
decoder (#425).

The contract: an adversarial value never crashes the process, never hangs and
never allocates without bound. It either succeeds (with clamped parameters) or
is refused with a clean, classified error:

- at the CLI boundary, a ``SystemExit``/return with one of the documented exit
  codes **other than 1** — code 1 is ``internal_error``, which is what an
  unhandled ``IndexError``/``TypeError``/``ZeroDivisionError`` turns into, so
  it marks a leak;
- at the engine boundary (``apply_pipeline``, what the MCP server calls), a
  ``ValueError`` (``StructuredError`` and ``ResourceLimitError`` are both one)
  or an ``OSError``, never any other exception type;
- at a decoder, the same, for random bytes, truncated files, a valid magic
  number followed by garbage, and headers that declare absurd dimensions —
  those must be refused by ``validate_dimensions`` *before* any pixel buffer
  is allocated, which is the memory half of the contract.

Hangs are bounded by ``faulthandler``: a case that runs past ``HANG_SECONDS``
kills the test process with a traceback instead of waiting out the CI cap.
Slowness is bounded by ``SLOW_SECONDS`` per case on an 8×6 image.

Every op in ``cli.OPS`` and every filter in ``available_filters()`` is
enumerated from the registries, so a new op or filter is fuzzed the day it is
registered, with no catalogue to keep in step.
"""

from __future__ import annotations

import faulthandler
import io
import os
import random
import struct
import time
import zipfile
import zlib

import pytest
from PySide6.QtGui import QColor, QImage

from photoslop import cli, filters
from photoslop.services import FileService

HANG_SECONDS = 120
SLOW_SECONDS = 20

# Every classified exit code except 1 (internal_error): see cli._EXIT_CODES.
CLEAN_EXITS = {0, 2, 3, 4, 5, 6}

ADVERSARIAL_VALUES = (
    "",
    " ",
    "-1",
    "0",
    "1e9",
    "inf",
    "nan",
    "-inf",
    "1e308",
    "9" * 40,
    "0x0",
    "-1x-1",
    "1000000000x1000000000",
    "0,0,0,0",
    "-5,-5,-5,-5",
    "1,2,3,4,5,6,7,8,9,10,11,12",
    "nan,nan,nan",
    "\x00",
    "ünïcödé",
    "a" * 5000,
    '{"op":null}',
    "[]",
    "{}",
    "null",
    ":",
    ",,,,",
    "x",
)

# Values a numeric parameter might be handed, beyond the general list above.
NUMERIC_VALUES = ("-1", "0", "1e9", "inf", "nan", "-inf", "1e308", "9" * 40, "", "x", "1.5")


@pytest.fixture(autouse=True)
def _watchdog():
    """A hung case ends the process with a traceback rather than the CI cap."""
    faulthandler.dump_traceback_later(HANG_SECONDS, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()


def _tiny_png(tmp_path, name: str = "in.png", size=(8, 6)) -> str:
    img = QImage(size[0], size[1], QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(120, 90, 60))
    path = str(tmp_path / name)
    assert img.save(path)
    return path


def _run(argv) -> int:
    """Exit code of one CLI invocation, whether main returned it or raised SystemExit."""
    try:
        return cli.main([str(a) for a in argv])
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def _run_timed(argv) -> tuple[int, float]:
    started = time.perf_counter()
    code = _run(argv)
    return code, time.perf_counter() - started


# ----- CLI ops ----------------------------------------------------------------


@pytest.mark.parametrize("op", sorted(cli.OPS))
def test_every_cli_op_refuses_adversarial_values_cleanly(qapp, op, tmp_path, capsys):
    metavar = cli.OPS[op][0]
    values = ADVERSARIAL_VALUES if metavar is not None else ("",)
    src = _tiny_png(tmp_path)
    for value in values:
        out = tmp_path / "out.png"
        argv = [src, f"--{op}", *([value] if metavar is not None else []), "--output", out]
        code, elapsed = _run_timed(argv)
        err = capsys.readouterr().err
        assert code in CLEAN_EXITS, f"--{op} {value!r}: exit {code} (internal error leaked)\n{err}"
        assert elapsed < SLOW_SECONDS, f"--{op} {value!r} took {elapsed:.1f}s"
        if code != 0:
            assert not out.exists(), f"--{op} {value!r} failed with exit {code} but wrote output"
        else:
            out.unlink(missing_ok=True)


@pytest.mark.parametrize("op", sorted(cli.OPS))
def test_every_engine_op_raises_only_classified_errors(qapp, op, tmp_path):
    """The MCP server calls ``apply_pipeline``; anything but ValueError/OSError
    out of it becomes an ``internal_error`` tool result."""
    metavar = cli.OPS[op][0]
    values = ("", "-1", "nan", "1e9", "0,0,0,0", "x") if metavar is not None else ("",)
    for value in values:
        try:
            cli.apply_pipeline(
                new="8x6", operations=[(op, value)], output=str(tmp_path / f"{op}.png")
            )
        except (ValueError, OSError):
            pass
        except Exception as exc:  # noqa: BLE001 — the point is the type
            pytest.fail(f"{op} {value!r} leaked {type(exc).__name__}: {exc}")


def test_top_level_arguments_refuse_adversarial_values_cleanly(qapp, tmp_path, capsys):
    src = _tiny_png(tmp_path)
    out = tmp_path / "out.png"
    cases: list[list] = []
    for value in ADVERSARIAL_VALUES:
        cases.append(["--new", value, "--output", out])
        cases.append(["--new", "8x6", "--dpi", value, "--output", out])
        cases.append([src, "--sample", value])
    for value in ("0", "-1", "1000000000", "2401"):
        cases.append(["--new", "8x6", "--dpi", value, "--output", out])
    # Enormous documents are refused by the resource budget, not attempted.
    for spec in ("100000x100000", "1000000000x1", "1x1000000000", "0x0", "-8x6", "8x-6"):
        cases.append(["--new", spec, "--output", out])
    # Odd output targets: no extension, an unknown one, a directory, an empty name.
    for target in ("out", "out.", "out.xyz", "out.exe", tmp_path, ""):
        cases.append([src, "--output", target])
    cases.append([src, "--export-artboards", src])  # a file where a directory is wanted
    for argv in cases:
        code, elapsed = _run_timed(argv)
        err = capsys.readouterr().err
        assert code in CLEAN_EXITS, f"{argv!r}: exit {code} (internal error leaked)\n{err}"
        assert elapsed < SLOW_SECONDS, f"{argv!r} took {elapsed:.1f}s"
        out.unlink(missing_ok=True)


def test_degenerate_selections_and_layers_do_not_crash(qapp, tmp_path, capsys):
    """Empty and inverted rectangles, a selection off the canvas, a one-pixel
    document, filters and fills applied to each."""
    src = _tiny_png(tmp_path)
    one = _tiny_png(tmp_path, "one.png", size=(1, 1))
    out = tmp_path / "out.png"
    selections = ("0,0,0,0", "5,5,-3,-3", "100,100,10,10", "-10,-10,5,5", "0,0,1,1")
    follow_ups = (
        ["--filter", "sepia"],
        ["--fill-selection", "1,2,3"],
        ["--gaussian-blur", "2"],
        ["--clear"],
        ["--feather", "3"],
        ["--invert"],
        ["--crop", "0,0,0,0"],
        ["--content-aware-fill"],
    )
    for input_path in (src, one):
        for selection in selections:
            for follow_up in follow_ups:
                argv = [input_path, "--select", selection, *follow_up, "--output", out]
                code, elapsed = _run_timed(argv)
                err = capsys.readouterr().err
                assert code in CLEAN_EXITS, f"{argv!r}: exit {code}\n{err}"
                assert elapsed < SLOW_SECONDS, f"{argv!r} took {elapsed:.1f}s"
                out.unlink(missing_ok=True)


# ----- filters ------------------------------------------------------------------


def _safe_filters() -> list[tuple[str, type[filters.Filter]]]:
    return sorted(filters.available_filters().items())


def _param_id(value) -> str:
    return value if isinstance(value, str) else ""


@pytest.mark.parametrize(("name", "cls"), _safe_filters(), ids=_param_id)
def test_filter_parameters_reject_adversarial_text_as_value_errors(name, cls):
    texts = list(ADVERSARIAL_VALUES)
    for spec in cls.params:
        texts.extend(f"{spec.key}={value}" for value in NUMERIC_VALUES)
        texts.append(f"{spec.key}=")
        texts.append(f"{spec.key}={spec.key}")
    texts.append(",".join(f"{spec.key}=nan" for spec in cls.params))
    for text in texts:
        try:
            params = filters.parse_params(cls, text)
        except ValueError:
            continue
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{name}: parse_params({text!r}) leaked {type(exc).__name__}: {exc}")
        # Whatever parsed must be inside the declared range, or the apply below
        # inherits an unchecked value.
        for spec in cls.params:
            if spec.type in ("int", "float"):
                assert spec.minimum <= params[spec.key] <= spec.maximum, (name, text, spec.key)


def _boundary_params(cls: type[filters.Filter]) -> list[tuple[str, dict]]:
    picks = []
    for label, pick in (
        ("minimum", lambda p: p.minimum),
        ("maximum", lambda p: p.maximum),
        ("default", lambda p: p.default),
    ):
        params = {}
        for spec in cls.params:
            if spec.type == "choice":
                params[spec.key] = spec.choices[0] if label == "minimum" else spec.choices[-1]
            elif spec.type == "str":
                params[spec.key] = spec.default
            else:
                params[spec.key] = pick(spec)
        picks.append((label, params))
    return picks


@pytest.mark.parametrize(("name", "cls"), _safe_filters(), ids=_param_id)
def test_filter_apply_survives_boundary_params_on_tiny_and_odd_images(qapp, name, cls):
    sizes = ((1, 1), (2, 2), (3, 5), (1, 64), (64, 1), (33, 17))
    for label, params in _boundary_params(cls):
        for size in sizes:
            img = QImage(size[0], size[1], QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QColor(10, 200, 30, 128))
            started = time.perf_counter()
            try:
                cls().apply(img, dict(params))
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"{name} at {label} on {size[0]}x{size[1]}: {type(exc).__name__}: {exc}"
                )
            elapsed = time.perf_counter() - started
            assert elapsed < SLOW_SECONDS, f"{name} at {label} on {size} took {elapsed:.1f}s"
            assert img.width() == size[0] and img.height() == size[1], (name, label, size)


# ----- format decoders --------------------------------------------------------------


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _png_with_dims(width: int, height: int) -> bytes:
    """A well-formed PNG whose IHDR claims ``width``×``height`` and whose single
    IDAT holds one pixel row of nothing: the header decodes, the pixels do not."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b"\x00" * 5))
        + _png_chunk(b"IEND", b"")
    )


def _psd_with_dims(width: int, height: int, version: int = 1) -> bytes:
    header = b"8BPS" + struct.pack(">H", version) + b"\x00" * 6
    header += struct.pack(">HIIHH", 3, height, width, 8, 3)
    return header + b"\x00" * 64


def _ora_with_dims(width, height, *, layer_dims: tuple[int, int] = (1, 1)) -> bytes:
    """An OpenRaster archive whose stack.xml declares ``width``×``height`` (any
    text) over one tiny real layer, so only the declaration is adversarial."""
    stack = (
        f'<image w="{width}" h="{height}" xres="72" yres="72">'
        f'<stack><layer src="data/l.png" x="0" y="0"/></stack></image>'
    ).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("mimetype", "image/openraster")
        zf.writestr("stack.xml", stack)
        zf.writestr("data/l.png", _png_with_dims(*layer_dims))
    return buffer.getvalue()


def _svg_with_dims(width: str, height: str) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect x="0" y="0" width="1" height="1"/></svg>'
    ).encode()


MAGICS = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff\xe0",
    ".bmp": b"BM",
    ".webp": b"RIFF\x00\x00\x00\x00WEBP",
    ".tif": b"II*\x00",
    ".ora": b"PK\x03\x04",
    ".psd": b"8BPS\x00\x01",
    ".psb": b"8BPS\x00\x02",
    ".svg": b"<svg",
    ".dng": b"II*\x00",  # camera raw, decoded by LibRaw when rawpy is installed
}


def _genuine(tmp_path, ext: str) -> bytes | None:
    """A real file of this format written by the engine itself, or None."""
    src = _tiny_png(tmp_path, "genuine-src.png", size=(12, 9))
    out = tmp_path / f"genuine{ext}"
    code = _run([src, "--duplicate-layer", "--output", out])
    if code != 0 or not out.exists():
        return None
    return out.read_bytes()


def _decoder_payloads(tmp_path, ext: str) -> list[tuple[str, bytes]]:
    rng = random.Random(425)
    payloads = [
        ("empty", b""),
        ("one-byte", b"\x00"),
        ("random-16", rng.randbytes(16)),
        ("random-1k", rng.randbytes(1024)),
        ("random-64k", rng.randbytes(64 * 1024)),
        ("magic-then-zeros", MAGICS[ext] + b"\x00" * 256),
        ("magic-then-random", MAGICS[ext] + rng.randbytes(4096)),
        ("magic-then-ff", MAGICS[ext] + b"\xff" * 256),
    ]
    genuine = _genuine(tmp_path, ext)
    if genuine:
        for fraction in (0.3, 0.6, 0.95):
            cut = genuine[: int(len(genuine) * fraction)]
            payloads.append((f"truncated-{int(fraction * 100)}", cut))
        flipped = bytearray(genuine)
        for index in rng.sample(range(len(flipped)), min(32, len(flipped))):
            flipped[index] ^= 0xFF
        payloads.append(("bit-flipped", bytes(flipped)))
    if ext == ".png":
        payloads += [
            ("ihdr-100000x100000", _png_with_dims(100_000, 100_000)),
            ("ihdr-0x0", _png_with_dims(0, 0)),
            ("ihdr-max-u32", _png_with_dims(0xFFFFFFFF, 0xFFFFFFFF)),
        ]
    if ext in (".psd", ".psb"):
        version = 2 if ext == ".psb" else 1
        payloads += [
            ("header-200000x200000", _psd_with_dims(200_000, 200_000, version)),
            ("header-0x0", _psd_with_dims(0, 0, version)),
            ("header-max-u32", _psd_with_dims(0xFFFFFFFF, 0xFFFFFFFF, version)),
            ("header-1x1-no-body", _psd_with_dims(1, 1, version)[:26]),
        ]
    if ext == ".ora":
        payloads += [
            ("stack-1e9", _ora_with_dims(10**9, 10**9)),
            ("stack-0x0", _ora_with_dims(0, 0)),
            ("stack-negative", _ora_with_dims(-5, -5)),
            ("stack-nan", _ora_with_dims("nan", "inf")),
            ("stack-text", _ora_with_dims("wide", "")),
            ("stack-layer-larger-than-canvas", _ora_with_dims(2, 2, layer_dims=(4000, 4000))),
        ]
    if ext == ".svg":
        payloads += [
            ("dims-1e9", _svg_with_dims("1e9", "1e9")),
            ("dims-nan", _svg_with_dims("nan", "nan")),
            ("dims-negative", _svg_with_dims("-100", "-100")),
            ("dims-inf", _svg_with_dims("inf", "inf")),
            ("viewbox-huge", b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1e12 1e12"/>'),
            ("viewbox-garbage", b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="a b c d"/>'),
            ("not-xml", b"<svg><rect"),
        ]
    return payloads


@pytest.mark.parametrize("ext", sorted(MAGICS))
def test_decoders_refuse_corrupt_and_oversized_files_cleanly(qapp, ext, tmp_path, capsys):
    for label, payload in _decoder_payloads(tmp_path, ext):
        path = tmp_path / f"{label}{ext}"
        path.write_bytes(payload)
        # Engine boundary: a Document, or ValueError/OSError. Nothing else.
        started = time.perf_counter()
        try:
            FileService.load(str(path))
        except (ValueError, OSError):
            pass
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{ext} {label}: FileService.load leaked {type(exc).__name__}: {exc}")
        elapsed = time.perf_counter() - started
        assert elapsed < SLOW_SECONDS, f"{ext} {label}: load took {elapsed:.1f}s"
        # CLI boundary: a classified exit, never internal_error.
        code, elapsed = _run_timed([path, "--info"])
        err = capsys.readouterr().err
        assert code in CLEAN_EXITS, f"{ext} {label}: exit {code} (internal error leaked)\n{err}"
        assert elapsed < SLOW_SECONDS, f"{ext} {label}: CLI took {elapsed:.1f}s"


def test_oversized_headers_are_refused_before_allocation(qapp, tmp_path):
    """The memory half of the contract: a header that declares a 10-gigapixel
    canvas must be refused by the resource budget, not attempted."""
    from photoslop.resources import ResourceLimitError

    # No .psd here: without the PSD codec (#437) Qt has no reader for it and the
    # file is refused as unopenable, which is clean but not a budget decision.
    cases = {
        "huge.png": _png_with_dims(100_000, 100_000),
        "huge.ora": _ora_with_dims(10**9, 10**9),
        "huge.svg": _svg_with_dims("1e9", "1e9"),
    }
    for name, payload in cases.items():
        path = tmp_path / name
        path.write_bytes(payload)
        started = time.perf_counter()
        with pytest.raises(ResourceLimitError):
            FileService.load(str(path))
        elapsed = time.perf_counter() - started
        assert elapsed < 2.0, f"{name}: refusal took {elapsed:.1f}s (was something allocated?)"


def test_import_layer_from_corrupt_files_is_clean(qapp, tmp_path, capsys):
    src = _tiny_png(tmp_path)
    out = tmp_path / "out.png"
    rng = random.Random(4250)
    for ext, magic in MAGICS.items():
        for label, payload in (("random", rng.randbytes(2048)), ("magic", magic + b"\x00" * 128)):
            bad = tmp_path / f"import-{label}{ext}"
            bad.write_bytes(payload)
            code = _run([src, "--import-layer", bad, "--output", out])
            err = capsys.readouterr().err
            assert code in CLEAN_EXITS, f"--import-layer {bad.name}: exit {code}\n{err}"
            out.unlink(missing_ok=True)
    missing_dir = tmp_path / "nope" / "deeper" / "x.png"
    assert _run([src, "--import-layer", missing_dir, "--output", out]) in CLEAN_EXITS
    assert _run([src, "--import-layer", os.devnull, "--output", out]) in CLEAN_EXITS

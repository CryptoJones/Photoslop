# SPDX-License-Identifier: Apache-2.0

import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.app import _console_entry_point, _run_portable_smoke, main
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def test_portable_smoke_round_trips_qt_codec_and_pixels(qapp):
    window = MainWindow(recovery_enabled=False)
    window.add_document(Document.new(QSize(12, 8), 72, "smoke", QColor("white")))
    _run_portable_smoke(window)


def test_console_entry_points_reachable_through_the_bundled_executable(qapp, tmp_path):
    """A portable bundle is one executable, so --cli/--mcp are the only route
    to the console scripts pyproject.toml declares (#187)."""
    output = tmp_path / "cli.png"
    assert main(["photoslop", "--cli", "--new", "8x8", "--output", str(output)]) == 0
    assert output.is_file() and output.stat().st_size > 0

    with pytest.raises(SystemExit) as exit_info:
        main(["photoslop", "--mcp", "--help"])
    assert exit_info.value.code == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["photoslop"],
        ["photoslop", "picture.png"],
        # a file genuinely named --cli must open, not dispatch
        ["photoslop", "picture.png", "--cli"],
    ],
)
def test_selector_is_ignored_unless_it_leads(argv):
    assert _console_entry_point(argv) is None


def test_selector_passes_remaining_arguments_through(monkeypatch):
    seen = {}

    def fake_server_main():
        seen["argv"] = list(sys.argv)

    monkeypatch.setattr("photoslop.server.main", fake_server_main)
    delegate = _console_entry_point(["photoslop", "--mcp", "--root", "/tmp", "--allow-overwrite"])
    assert delegate() == 0
    assert seen["argv"] == ["photoslop-mcp", "--root", "/tmp", "--allow-overwrite"]


# --- #409: informational flags must never bring up the GUI ------------------

_NO_GUI_PROBE = """
import sys
from {module} import main
sys.argv = {argv!r}
try:
    # photoslop-mcp's main() reads sys.argv; the other two take argv.
    rc = main() if {module!r} == "photoslop.server" else main({call_argv!r})
except SystemExit as exc:
    rc = exc.code
assert "photoslop.mainwindow" not in sys.modules, "editor window was imported"
if "PySide6.QtCore" in sys.modules:
    from PySide6.QtCore import QCoreApplication
    assert QCoreApplication.instance() is None, "a Qt application was created"
sys.exit(rc)
"""


def _run_without_gui(module: str, argv: list[str]):
    """Run one entry point in a fresh interpreter, so no qapp fixture hides a
    QApplication the code under test created."""
    import subprocess

    call_argv = argv[1:] if module == "photoslop.cli" else argv
    code = _NO_GUI_PROBE.format(module=module, argv=argv, call_argv=call_argv)
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )


@pytest.mark.parametrize(
    ("module", "argv", "expected"),
    [
        ("photoslop.app", ["photoslop", "--help"], "usage: photoslop [FILE ...]"),
        ("photoslop.app", ["photoslop", "-h"], "usage: photoslop [FILE ...]"),
        ("photoslop.app", ["photoslop", "--version"], "photoslop "),
        ("photoslop.app", ["photoslop", "--cli", "--help"], "usage: photoslop-cli"),
        ("photoslop.app", ["photoslop", "--mcp", "--version"], "photoslop-mcp "),
        ("photoslop.cli", ["photoslop-cli", "--help"], "usage: photoslop-cli"),
        ("photoslop.cli", ["photoslop-cli", "--version"], "photoslop-cli "),
        ("photoslop.server", ["photoslop-mcp", "--help"], "usage: photoslop-mcp"),
        ("photoslop.server", ["photoslop-mcp", "--version"], "photoslop-mcp "),
    ],
)
def test_help_and_version_print_without_starting_qt(module, argv, expected):
    result = _run_without_gui(module, argv)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(expected)


def test_cli_usage_error_does_not_start_qt():
    result = _run_without_gui("photoslop.cli", ["photoslop-cli"])
    assert result.returncode == 2, result.stderr
    assert "give an input file" in result.stderr


def test_version_reports_the_package_version():
    # In a subprocess: were --version to regress into the GUI path, an
    # in-process call would sit in the Qt event loop and hang the suite.
    from photoslop import __version__

    result = _run_without_gui("photoslop.app", ["photoslop", "--version"])
    assert result.stdout == f"photoslop {__version__}\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["photoslop"],
        ["photoslop", "picture.png"],
        # a file genuinely named --help must open, not print usage
        ["photoslop", "picture.png", "--help"],
    ],
)
def test_info_flags_are_ignored_unless_they_lead(argv):
    from photoslop.app import _info_entry_point

    assert _info_entry_point(argv) is None

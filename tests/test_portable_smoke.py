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

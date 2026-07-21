# SPDX-License-Identifier: Apache-2.0
"""One release version drives packaging, runtime, docs, and bundles."""

import importlib.metadata
import subprocess
import sys
from pathlib import Path

from photoslop import __version__

ROOT = Path(__file__).resolve().parent.parent


def _check(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/check-version.py", *args],
        cwd=ROOT, capture_output=True, text=True, check=False)


def test_runtime_distribution_and_release_declarations_agree():
    result = _check("--tag", f"v{__version__}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == __version__
    assert importlib.metadata.version("photoslop") == __version__


def test_release_gate_rejects_wrong_tag():
    result = _check("--tag", "v0.0.0")
    assert result.returncode != 0
    assert "does not match" in result.stderr


def test_release_permissions_are_confined_to_tag_upload_jobs():
    portable = (ROOT / ".github/workflows/portable.yml").read_text()
    ipados = (ROOT / ".github/workflows/ipados.yml").read_text()
    for source in (portable, ipados):
        assert "permissions:\n  contents: read" in source
        assert source.count("contents: write") == 1
        assert "if: startsWith(github.ref, 'refs/tags/v')" in source

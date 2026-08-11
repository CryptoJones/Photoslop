# SPDX-License-Identifier: Apache-2.0
"""The documentation library is a second view of the engine, and drifts from it
silently. These tests pin the claims that are mechanically checkable.

Every feature ships with a CLI mirror and a docs update; nothing here can catch
a missing prose section, but a stale option table or a hand-counted operation
total is exactly the kind of rot that shipped `54`, `58`, and the real number
all in the same release.
"""

import re
from pathlib import Path

import pytest

from photoslop import cli
from photoslop.__about__ import __version__

DOCS = Path(__file__).resolve().parents[1] / "docs" / "v1"
README = Path(__file__).resolve().parents[1] / "README.md"


def _cli_doc() -> str:
    return (DOCS / "cli.md").read_text(encoding="utf-8")


def test_cli_reference_documents_every_operation_and_no_ghosts():
    documented = set(re.findall(r"^\| `--([a-z0-9-]+)`", _cli_doc(), re.M))
    assert documented == set(cli.OPS), (
        "docs/v1/cli.md and the CLI op table drifted apart — "
        f"undocumented: {sorted(set(cli.OPS) - documented)}; "
        f"documented but gone: {sorted(documented - set(cli.OPS))}"
    )


@pytest.mark.parametrize(
    "pattern",
    [
        r"\*\*(\d+) shared engine ops\*\*",
        r"All (\d+) operations are shared",
    ],
)
def test_feature_parity_operation_counts_match_the_engine(pattern):
    text = (DOCS / "feature-parity.md").read_text(encoding="utf-8")
    claimed = re.findall(pattern, text)
    assert claimed, f"the claim matching {pattern!r} disappeared from feature-parity.md"
    for value in claimed:
        assert int(value) == len(cli.OPS), (
            f"feature-parity.md claims {value} operations; the engine has {len(cli.OPS)}"
        )


def test_documented_version_claims_track_the_package():
    """feature-parity.md compares a specific Photoslop release against the
    field; the header and the versions table have to name the same one."""
    text = (DOCS / "feature-parity.md").read_text(encoding="utf-8")
    header = re.search(r"comparison of \*\*Photoslop v([0-9.]+)\*\*", text)
    assert header and header.group(1) == __version__
    row = re.search(r"^\| \*\*Photoslop\*\* \| ([0-9.]+) \|", text, re.M)
    assert row and row.group(1) == __version__


def test_readme_version_badge_tracks_the_package():
    badge = re.search(r"badge/version-v([0-9.]+)-", README.read_text(encoding="utf-8"))
    assert badge and badge.group(1) == __version__


def test_every_doc_carries_the_project_footer():
    """Every Markdown doc ends with the project signature; the README carries
    the centred banner form instead."""
    missing = [
        path.name
        for path in sorted(DOCS.glob("*.md"))
        if "Proudly Made in Nebraska" not in path.read_text(encoding="utf-8")
    ]
    assert not missing, f"docs without the Nebraska footer: {missing}"

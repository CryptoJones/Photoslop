# SPDX-License-Identifier: Apache-2.0

import json
import subprocess
import sys
from pathlib import Path

from photoslop import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_bundle_metadata_is_valid_deterministic_and_complete(tmp_path):
    command = [
        sys.executable,
        "scripts/generate-bundle-metadata.py",
        "--output-dir",
        str(tmp_path),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    first = (tmp_path / "photoslop.cdx.json").read_bytes()
    subprocess.run(command, cwd=ROOT, check=True)
    assert (tmp_path / "photoslop.cdx.json").read_bytes() == first

    sbom = json.loads(first)
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["metadata"]["component"]["version"] == __version__
    component_names = {item["name"].casefold() for item in sbom["components"]}
    assert {"pyside6", "numpy", "defusedxml"} <= component_names
    identity = json.loads((tmp_path / "BUILD-IDENTITY.json").read_text(encoding="utf-8"))
    assert identity["version"] == __version__
    assert len(identity["dependency_inventory_sha256"]) == 64
    notices = (tmp_path / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Tabler Icons" in notices and "Bundled Python packages" in notices

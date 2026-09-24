# SPDX-License-Identifier: Apache-2.0
"""The iOS privacy strings live in the XcodeGen spec, not only in the plist.

`ipados/Photoslop/Info.plist` is generated: every build runs
`xcodegen generate`, which rewrites it from `ipados/project.yml`. A key added
to the plist alone looks right in the source tree and is gone from every
build, which is what happened to `NSPhotoLibraryAddUsageDescription` in #391:
the committed plist carried it, the spec did not, and CI and TestFlight builds
went on asking for the whole photo library on export.
"""

import plistlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLIST = ROOT / "ipados/Photoslop/Info.plist"
SPEC = ROOT / "ipados/project.yml"


def _usage_descriptions() -> dict[str, str]:
    with PLIST.open("rb") as handle:
        info = plistlib.load(handle)
    return {key: value for key, value in info.items() if key.endswith("UsageDescription")}


def test_the_export_prompt_asks_to_add_not_to_read():
    assert "NSPhotoLibraryAddUsageDescription" in _usage_descriptions()


def test_every_usage_description_survives_xcodegen():
    spec = SPEC.read_text(encoding="utf-8")
    for key, text in _usage_descriptions().items():
        match = re.search(rf"^\s+{key}:\s*(.+)$", spec, re.MULTILINE)
        assert match, f"{key} is in Info.plist but not project.yml; xcodegen drops it"
        assert match.group(1).strip() == text, f"{key} differs between Info.plist and project.yml"

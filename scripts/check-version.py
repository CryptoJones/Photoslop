#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail when release-facing version declarations disagree."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _match(path: str, pattern: str) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(pattern, source)
    if match is None:
        raise SystemExit(f"{path}: version declaration not found")
    return match.group(1)


def _check_release_inputs() -> None:
    for workflow in sorted((ROOT / ".github/workflows").glob("*.yml")):
        source = workflow.read_text(encoding="utf-8")
        for action, ref in re.findall(r"\buses:\s*([^@\s]+)@([^\s#]+)", source):
            if action.startswith("./"):
                continue
            if FULL_SHA.fullmatch(ref) is None:
                raise SystemExit(
                    f"{workflow.relative_to(ROOT)}: {action} must use a full commit SHA"
                )

    for relative in (
        "scripts/build-portable-macos.sh",
        "scripts/build-portable-windows.ps1",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        required = (
            "uv sync",
            "--extra build",
            "--locked",
            "--portable-smoke",
            "photoslop.cdx.json",
            "BUILD-IDENTITY.json",
            "THIRD_PARTY_NOTICES.md",
        )
        missing = [token for token in required if token not in source]
        if missing:
            raise SystemExit(f"{relative}: missing release inputs: {', '.join(missing)}")
        if "uv pip install" in source:
            raise SystemExit(f"{relative}: portable build bypasses the locked environment")

    ipados = (ROOT / ".github/workflows/ipados.yml").read_text(encoding="utf-8")
    if "XcodeGen/releases/download/2.46.0/xcodegen.zip" not in ipados:
        raise SystemExit("iPad workflow must use the reviewed XcodeGen version")
    if not re.search(r"[0-9a-f]{64}\s+\$archive", ipados):
        raise SystemExit("iPad workflow must verify the XcodeGen archive checksum")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Expected release tag, for example v1.30.0")
    args = parser.parse_args()

    version = _match("photoslop/__about__.py", r'__version__ = "([^"]+)"')
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if 'dynamic = ["version"]' not in project:
        raise SystemExit("pyproject.toml must derive its version dynamically")
    if 'path = "photoslop/__about__.py"' not in project:
        raise SystemExit("Hatch version source is not photoslop/__about__.py")

    declarations = {
        "ipados/project.yml": _match("ipados/project.yml", r'MARKETING_VERSION: "([^"]+)"'),
        "README.md": _match("README.md", r"version-v([0-9.]+)-orange"),
        "docs/v1/README.md": _match("docs/v1/README.md", r"as of \*\*v([0-9.]+)"),
        "docs/v1/ipados.md": _match("docs/v1/ipados.md", r"v([0-9.]+)"),
        "docs/v1/feature-parity.md": _match("docs/v1/feature-parity.md", r"Photoslop v([0-9.]+)"),
        "CHANGELOG.md": _match("CHANGELOG.md", r"## \[([0-9.]+)\]"),
    }
    mismatches = {path: value for path, value in declarations.items() if value != version}
    if mismatches:
        details = ", ".join(f"{path}={value}" for path, value in mismatches.items())
        raise SystemExit(f"version {version} disagrees with {details}")

    major, minor, patch = (int(part) for part in version.split("."))
    expected_build = str(major * 10000 + minor * 100 + patch)
    actual_build = _match("ipados/project.yml", r'CURRENT_PROJECT_VERSION: "([0-9]+)"')
    if actual_build != expected_build:
        raise SystemExit(f"iPad build {actual_build} should be {expected_build} for {version}")

    _check_release_inputs()

    tag = args.tag
    if tag is None and os.environ.get("GITHUB_REF_TYPE") == "tag":
        tag = os.environ.get("GITHUB_REF_NAME")
    if tag is not None and tag != f"v{version}":
        raise SystemExit(f"tag {tag} does not match v{version}")
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

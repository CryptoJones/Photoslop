#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate deterministic notices, CycloneDX SBOM, and build identity files."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import uuid
from pathlib import Path

from photoslop import __version__

_LICENSE_NAME = re.compile(r"(^|/)(licen[cs]e|copying|notice)([._-].*)?$", re.I)


def _packages() -> list[dict[str, object]]:
    packages: list[dict[str, object]] = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name or name.casefold() == "photoslop":
            continue
        license_expression = (
            distribution.metadata.get("License-Expression")
            or distribution.metadata.get("License")
            or "NOASSERTION"
        ).strip()
        homepage = distribution.metadata.get("Home-page") or ""
        if not homepage:
            for entry in distribution.metadata.get_all("Project-URL") or []:
                if "," in entry:
                    _label, homepage = entry.split(",", 1)
                    homepage = homepage.strip()
                    break
        packages.append({
            "name": name,
            "version": distribution.version,
            "license": license_expression,
            "homepage": homepage,
            "distribution": distribution,
        })
    packages.sort(key=lambda item: str(item["name"]).casefold())
    return packages


def _license_texts(distribution) -> list[tuple[str, str]]:
    texts = []
    for entry in distribution.files or []:
        relative = str(entry).replace("\\", "/")
        if not _LICENSE_NAME.search(relative):
            continue
        path = Path(distribution.locate_file(entry))
        try:
            if path.stat().st_size > 256 * 1024:
                continue
            content = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if content:
            texts.append((relative, content))
    return texts


def _write_notices(path: Path, base: Path, packages: list[dict[str, object]]) -> None:
    lines = [base.read_text(encoding="utf-8").rstrip(), "", "## Bundled Python packages", ""]
    lines.extend([
        "This section is generated from the exact build environment. License",
        "identifiers are package metadata supplied by each upstream project.",
        "A compliance owner must review this inventory before public release.",
        "",
    ])
    for package in packages:
        link = f" — {package['homepage']}" if package["homepage"] else ""
        lines.append(
            f"### {package['name']} {package['version']} — {package['license']}{link}")
        texts = _license_texts(package["distribution"])
        if not texts:
            lines.extend(["", "No license file was exposed by the installed distribution.", ""])
            continue
        for relative, content in texts:
            lines.extend(["", f"Source file: `{relative}`", "", "```text", content, "```", ""])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_sbom(path: Path, packages: list[dict[str, object]]) -> None:
    components = [{
        "type": "library",
        "name": str(package["name"]),
        "version": str(package["version"]),
        "purl": f"pkg:pypi/{str(package['name']).lower().replace('_', '-')}@{package['version']}",
        "licenses": [{"license": {"name": str(package["license"])}}],
    } for package in packages]
    fingerprint = json.dumps(components, sort_keys=True, separators=(",", ":"))
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"photoslop:{__version__}:{fingerprint}")
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {"component": {
            "type": "application", "name": "Photoslop", "version": __version__,
            "licenses": [{"license": {"id": "Apache-2.0"}}],
        }},
        "components": components,
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_identity(path: Path, packages: list[dict[str, object]]) -> None:
    inventory = [f"{item['name']}=={item['version']}" for item in packages]
    identity = {
        "version": __version__,
        "commit": os.environ.get("GITHUB_SHA", "unknown"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependency_inventory_sha256": hashlib.sha256(
            "\n".join(inventory).encode()).hexdigest(),
        "dependencies": inventory,
    }
    path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-notices", type=Path, default=Path("THIRD_PARTY_NOTICES.md"))
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    packages = _packages()
    _write_notices(
        args.output_dir / "THIRD_PARTY_NOTICES.md", args.base_notices, packages)
    _write_sbom(args.output_dir / "photoslop.cdx.json", packages)
    _write_identity(args.output_dir / "BUILD-IDENTITY.json", packages)
    return 0


if __name__ == "__main__":
    sys.exit(main())

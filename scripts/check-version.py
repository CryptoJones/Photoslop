#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail when release-facing version declarations disagree."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _match(path: str, pattern: str) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(pattern, source)
    if match is None:
        raise SystemExit(f"{path}: version declaration not found")
    return match.group(1)


def _base_version(base_ref: str) -> str | None:
    """The version declared on the branch this one will merge into.

    Returns None when the ref simply is not reachable — a shallow clone, a
    fork without the base fetched, a local checkout with no remote. A missing
    base is not a policy violation and must not fail the build; only a base
    that IS readable and NOT lower than ours is.
    """
    for ref in (base_ref, f"origin/{base_ref}"):
        try:
            source = subprocess.run(
                ["git", "show", f"{ref}:photoslop/__about__.py"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (subprocess.CalledProcessError, OSError):
            continue
        match = re.search(r'__version__ = "([^"]+)"', source)
        if match is not None:
            return match.group(1)
    return None


def _check_version_was_bumped(version: str, base_ref: str) -> None:
    """Every pull request raises the version — at minimum the patch.

    Two builds that report the same number are indistinguishable, so a change
    that ships without a bump cannot be identified once it is running: the
    title bar, About box and `photoslop-cli --version` all name a release that
    no longer describes the binary. The release commit still owns the tag and
    the CHANGELOG date; this only owns the number going up.
    """
    base = _base_version(base_ref)
    if base is None:
        print(f"version {version}: base {base_ref} unreadable, bump check skipped")
        return
    ours = tuple(int(part) for part in version.split("."))
    theirs = tuple(int(part) for part in base.split("."))
    if ours <= theirs:
        raise SystemExit(
            f"version {version} does not advance {base_ref}'s {base} — every PR bumps "
            "at least the patch. Update photoslop/__about__.py and the declarations "
            "that track it (CHANGELOG heading, README badge, docs/v1/README.md, "
            "docs/v1/ipados.md, docs/v1/feature-parity.md, ipados/project.yml "
            "MARKETING_VERSION and CURRENT_PROJECT_VERSION)."
        )


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
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("GITHUB_BASE_REF"),
        help="Branch this change merges into; its version must be lower than ours. "
        "Defaults to $GITHUB_BASE_REF, which GitHub sets only on pull requests.",
    )
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

    if args.base_ref:
        _check_version_was_bumped(version, args.base_ref)

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

# SPDX-License-Identifier: Apache-2.0
"""One release version drives packaging, runtime, docs, and bundles."""

import importlib.metadata
import re
import subprocess
import sys
from pathlib import Path

from photoslop import __version__

ROOT = Path(__file__).resolve().parent.parent


# Actions must be pinned to a full commit SHA, never a mutable tag. The pin
# value itself is deliberately not asserted: hard-coding it made a routine
# dependabot bump red-light main with a test failure that named nothing real.
_PINNED = re.compile(r"@[0-9a-f]{40}\b")
_CHECKOUT = re.compile(r"actions/checkout@[0-9a-f]{40}\b")


def _workflow_jobs(text: str) -> dict[str, str]:
    """Split a workflow into job name -> job body. Jobs are indented two spaces."""
    jobs: dict[str, str] = {}
    name: str | None = None
    lines: list[str] = []
    for line in text.split("\njobs:\n", 1)[1].splitlines():
        header = re.fullmatch(r"  ([A-Za-z0-9_-]+):", line)
        if header:
            if name is not None:
                jobs[name] = "\n".join(lines)
            name, lines = header.group(1), []
        elif name is not None:
            lines.append(line)
    if name is not None:
        jobs[name] = "\n".join(lines)
    return jobs


def _assert_pinned_checkouts(portable: str) -> None:
    """Every job that checks out does so exactly once, from one pinned revision.

    A global count cannot tell "three jobs check out once each" apart from "one
    job checks out twice and another not at all" — and the release job losing
    its checkout is precisely the regression #181 fixed.
    """
    pins = set(_CHECKOUT.findall(portable))
    assert len(pins) == 1, f"portable.yml must pin one checkout revision, found {pins}"
    jobs = _workflow_jobs(portable)
    for job in ("macos", "windows", "release"):
        found = _CHECKOUT.findall(jobs[job])
        assert len(found) == 1, f"job {job!r} needs exactly one pinned checkout, found {found}"
    release = jobs["release"]
    checkout_at = _CHECKOUT.search(release).start()
    assert checkout_at < release.index("actions/download-artifact"), (
        "the release job must check out before downloading artifacts"
    )
    # The credential the checkout would persist is never used; gh uses GH_TOKEN.
    assert release.count("persist-credentials: false") == 1


def _check(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/check-version.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


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
    assert "permissions:\n  contents: read" in portable
    assert portable.count("contents: write") == 1
    _assert_pinned_checkouts(portable)
    assert "if: startsWith(github.ref, 'refs/tags/v')" in portable
    assert portable.count("PHOTOSLOP_REQUIRE_SIGNING") == 2
    assert portable.count("PHOTOSLOP_ARTIFACT_QUALIFIER") == 2

    # Every signing waiver names the tags it applies to, so a new tag is
    # fail-closed by default and a widened exception shows up in the diff.
    #
    # macOS: only v1.30.0, which shipped before notary credentials existed.
    assert portable.count("github.ref_name != 'v1.30.0'") == 1
    assert "&& 'SIGNED-NOT-NOTARIZED' || ''" in portable
    assert portable.count("github.ref_name == 'v1.30.0' && 'SIGNED-NOT-NOTARIZED' || ''") == 1
    assert portable.count("github.ref_name == 'v1.30.0' && '-SIGNED-NOT-NOTARIZED' || ''") == 2

    # Windows: no Authenticode certificate exists, so requiring one on a tag can
    # only fail the release. Every tagged Windows archive says UNSIGNED in its
    # name instead. Deliberately not a per-tag allowlist — that shape shipped
    # once and broke on the very next tag, because a list only covers the
    # versions someone remembered to add.
    assert portable.count('PHOTOSLOP_REQUIRE_SIGNING: "0"') == 1
    assert portable.count("startsWith(github.ref, 'refs/tags/v') && 'UNSIGNED' || ''") == 1
    assert portable.count("startsWith(github.ref, 'refs/tags/v') && '-UNSIGNED' || ''") == 2
    assert "fromJSON(" not in portable, "a per-tag signing allowlist came back"

    # Tagging is the only manual release step: the job creates the release when
    # it is missing. Uploading to a release nobody made discards a build that
    # already succeeded, which is how v2.0.2 lost its assets on the first try.
    assert 'gh release view "${GITHUB_REF_NAME}"' in portable
    assert 'gh release create "${GITHUB_REF_NAME}"' in portable
    assert "--verify-tag" in portable
    assert "scripts/import-macos-signing-certificate.sh" in portable
    assert "MACOS_CERTIFICATE_P12" in portable
    assert "verify_macos_signing" in portable
    assert "Attest signed portable archives" not in portable
    assert "Attest portable archive provenance" in portable
    for platform in ("macOS", "Windows"):
        assert f"Photoslop-{platform}.cdx.json" in portable
        assert f"Photoslop-{platform}-BUILD-IDENTITY.json" in portable
        assert f"Photoslop-{platform}-THIRD_PARTY_NOTICES.md" in portable
    assert _PINNED.search(portable[portable.index("attest-build-provenance") :])

    assert "permissions:\n  contents: read" in ipados
    assert "contents: write" not in ipados
    assert "gh release upload" not in ipados
    assert "unsigned-validation-only" in ipados


def test_external_workflow_actions_are_pinned_to_full_commit_shas():
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        for action, ref in re.findall(r"\buses:\s*([^@\s]+)@([^\s#]+)", workflow.read_text()):
            if not action.startswith("./"):
                assert re.fullmatch(r"[0-9a-f]{40}", ref), (workflow, action, ref)


def test_external_ipados_and_portable_build_inputs_are_locked():
    ipados = (ROOT / ".github/workflows/ipados.yml").read_text()
    assert "XcodeGen/releases/download/2.46.0/xcodegen.zip" in ipados
    assert re.search(r"[0-9a-f]{64}\s+\$archive", ipados)
    ipados_script = (ROOT / "scripts/build-ipados.sh").read_text()
    assert 'XCODEGEN_BIN="${XCODEGEN:-}"' in ipados_script
    assert '"$XCODEGEN_BIN" generate' in ipados_script

    for name in ("build-portable-macos.sh", "build-portable-windows.ps1"):
        source = (ROOT / "scripts" / name).read_text()
        assert "uv sync" in source
        assert "--extra build" in source
        assert "--locked" in source
        assert "uv pip install" not in source
        for required in (
            "--portable-smoke",
            "PHOTOSLOP_ARTIFACT_QUALIFIER",
            "photoslop.cdx.json",
            "BUILD-IDENTITY.json",
            "THIRD_PARTY_NOTICES.md",
        ):
            assert required in source

    macos_source = (ROOT / "scripts/build-portable-macos.sh").read_text()
    assert 'cd "$OUT_DIR"' in macos_source
    assert 'shasum -a 256 "$(basename "$ZIP")"' in macos_source


def test_every_linux_qt_workflow_installs_runtime_libraries():
    ci = (ROOT / ".github/workflows/test.yml").read_text()
    performance = (ROOT / ".github/workflows/performance.yml").read_text()
    assert ci.count("scripts/install-ci-qt-linux.sh") == 7
    assert performance.count("scripts/install-ci-qt-linux.sh") == 1


def test_mcp_requirement_matches_the_api_the_code_uses():
    """The pin has to track the API `photoslop/server.py` actually imports.

    `pip install "photoslop[mcp]"` ignores the lockfile, so the requirement is
    what a fresh install resolves against. The 1.x line exposes
    `mcp.server.fastmcp.FastMCP` and the 2.x line replaces it with
    `mcp.server.mcpserver.MCPServer`; a requirement that admits the major the
    code does not use breaks `photoslop-mcp` for every new installer while our
    own CI, which builds from the lockfile, reports all-clear. This is why
    dependabot's "relax the ceiling" pull requests are declined rather than
    merged: the ceiling moves when the import moves. See issue #182.
    """
    server_source = (ROOT / "photoslop/server.py").read_text()
    uses_v2 = "mcp.server.mcpserver" in server_source
    uses_v1 = "mcp.server.fastmcp" in server_source
    assert uses_v1 != uses_v2, "server.py must import exactly one of the two server APIs"

    pyproject = (ROOT / "pyproject.toml").read_text()
    requirements = re.findall(r'"(mcp[<>=!,\d. ]*)"', pyproject)
    assert requirements, "no mcp requirement found in pyproject.toml"
    expected_floor, expected_ceiling = (">=2", "<3") if uses_v2 else (">=1", "<2")
    for requirement in requirements:
        assert expected_ceiling in requirement, (
            f"{requirement!r} must be capped {expected_ceiling} for the API server.py imports"
        )
        assert expected_floor in requirement, (
            f"{requirement!r} needs a {expected_floor} floor so a fresh install cannot "
            "resolve onto the major the code no longer supports"
        )

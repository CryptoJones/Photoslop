# SPDX-License-Identifier: Apache-2.0
"""One release version drives packaging, runtime, docs, and bundles."""

import importlib.metadata
import re
import subprocess
import sys
from pathlib import Path

from photoslop import __version__

ROOT = Path(__file__).resolve().parent.parent


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
    assert "if: startsWith(github.ref, 'refs/tags/v')" in portable
    assert portable.count("PHOTOSLOP_REQUIRE_SIGNING") == 2
    assert portable.count("github.ref_name != 'v1.30.0'") == 2
    assert portable.count("PHOTOSLOP_ARTIFACT_QUALIFIER") == 2
    assert portable.count("github.ref_name == 'v1.30.0' && 'UNSIGNED' || ''") == 1
    assert portable.count("github.ref_name == 'v1.30.0' && '-UNSIGNED' || ''") == 2
    assert "&& 'SIGNED-NOT-NOTARIZED' || ''" in portable
    assert portable.count("github.ref_name == 'v1.30.0' && '-SIGNED-NOT-NOTARIZED' || ''") == 2
    assert "scripts/import-macos-signing-certificate.sh" in portable
    assert "MACOS_CERTIFICATE_P12" in portable
    assert "verify_macos_signing" in portable
    assert "Attest signed portable archives" not in portable
    assert "Attest portable archive provenance" in portable
    for platform in ("macOS", "Windows"):
        assert f"Photoslop-{platform}.cdx.json" in portable
        assert f"Photoslop-{platform}-BUILD-IDENTITY.json" in portable
        assert f"Photoslop-{platform}-THIRD_PARTY_NOTICES.md" in portable
    assert "attest-build-provenance@e8998f949152" in portable

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
    assert ci.count("scripts/install-ci-qt-linux.sh") == 6
    assert performance.count("scripts/install-ci-qt-linux.sh") == 1

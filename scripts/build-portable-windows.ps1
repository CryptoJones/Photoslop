# Photoslop — portable Windows build.
#
# Produces a self-contained "Photoslop" folder via PyInstaller: bundled
# Python interpreter + PySide6/Qt runtime + all dependencies. Copy the
# resulting folder anywhere (a thumbdrive, another PC) and run Photoslop.exe
# with no install, no Python, no network required.
#
# Usage:
#   pwsh ./scripts/build-portable-windows.ps1
#
# Output: dist\portable-windows\Photoslop\Photoslop.exe (+ a zip alongside it)
#
# SPDX-License-Identifier: Apache-2.0
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path "$PSScriptRoot/..").Path
Set-Location $Root

$Version = (Select-String -Path "photoslop\__about__.py" -Pattern '^__version__ = "(.*)"' | Select-Object -First 1).Matches.Groups[1].Value
if (-not $Version) { $Version = "0.0.0" }
$Qualifier = $env:PHOTOSLOP_ARTIFACT_QUALIFIER
if ($Qualifier -and $Qualifier -notmatch '^[A-Za-z0-9._-]+$') {
    throw "build-portable-windows.ps1: invalid artifact qualifier: $Qualifier"
}
$QualifierSuffix = if ($Qualifier) { "-$Qualifier" } else { "" }

$OutDir = Join-Path $Root "dist\portable-windows"
Remove-Item -Recurse -Force $OutDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Root "build\portable-windows") -ErrorAction SilentlyContinue

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "build-portable-windows.ps1: 'uv' not found - install it from https://astral.sh/uv"
}

Write-Host "Syncing locked dependencies (core + formats/raw/build)..."
uv sync --extra formats --extra raw --extra build --locked

$MetadataDir = Join-Path $Root "build\portable-windows-metadata"
uv run python scripts/generate-bundle-metadata.py --output-dir $MetadataDir

Write-Host "Building Photoslop.exe (v$Version) with PyInstaller..."
uv run pyinstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name Photoslop `
    --distpath $OutDir `
    --workpath (Join-Path $Root "build\portable-windows") `
    --specpath (Join-Path $Root "build\portable-windows") `
    --add-data "$Root\LICENSE;." `
    --add-data "$MetadataDir\THIRD_PARTY_NOTICES.md;." `
    --add-data "$MetadataDir\photoslop.cdx.json;." `
    --add-data "$MetadataDir\BUILD-IDENTITY.json;." `
    photoslop/app.py

$AppDir = Join-Path $OutDir "Photoslop"
$Exe = Join-Path $AppDir "Photoslop.exe"
if (-not (Test-Path $Exe)) {
    throw "build-portable-windows.ps1: expected executable was not produced: $Exe"
}

Write-Host "Running packaged Qt/codec/import/export smoke test..."
$env:QT_QPA_PLATFORM = "offscreen"
& $Exe --portable-smoke
if ($LASTEXITCODE -ne 0) { throw "Packaged smoke test failed with exit code $LASTEXITCODE" }

$CertificatePath = $null
try {
    if ($env:PHOTOSLOP_WINDOWS_CERT_BASE64) {
        $CertificatePath = Join-Path $env:RUNNER_TEMP "photoslop-signing.pfx"
        [IO.File]::WriteAllBytes(
            $CertificatePath,
            [Convert]::FromBase64String($env:PHOTOSLOP_WINDOWS_CERT_BASE64)
        )
        $SignTool = (Get-Command signtool.exe -ErrorAction Stop).Source
        & $SignTool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com `
            /f $CertificatePath /p $env:PHOTOSLOP_WINDOWS_CERT_PASSWORD $Exe
        if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed" }
        & $SignTool verify /pa /v $Exe
        if ($LASTEXITCODE -ne 0) { throw "Authenticode verification failed" }
    } elseif ($env:PHOTOSLOP_REQUIRE_SIGNING -eq "1") {
        throw "Tagged portable release requires Windows signing credentials"
    } else {
        Write-Host "Signing certificate absent; producing an explicitly unsigned validation artifact."
    }
} finally {
    if ($CertificatePath -and (Test-Path $CertificatePath)) {
        Remove-Item -Force $CertificatePath
    }
}

$Zip = Join-Path $OutDir "Photoslop-Windows-portable$QualifierSuffix-v$Version.zip"
Compress-Archive -Path $AppDir -DestinationPath $Zip -Force
$Hash = (Get-FileHash -Algorithm SHA256 $Zip).Hash.ToLowerInvariant()
"$Hash  $([IO.Path]::GetFileName($Zip))" | Set-Content -Encoding ascii "$Zip.sha256"
Copy-Item "$MetadataDir\photoslop.cdx.json" $OutDir
Copy-Item "$MetadataDir\BUILD-IDENTITY.json" $OutDir
Copy-Item "$MetadataDir\THIRD_PARTY_NOTICES.md" $OutDir

Write-Host "Portable Windows build ready:"
Write-Host "  Folder: $AppDir"
Write-Host "  Zip: $Zip"
Write-Host "  Checksum: $Zip.sha256"

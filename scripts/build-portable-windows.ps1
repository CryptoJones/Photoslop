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

$Version = (Select-String -Path "pyproject.toml" -Pattern '^version = "(.*)"' | Select-Object -First 1).Matches.Groups[1].Value
if (-not $Version) { $Version = "0.0.0" }

$OutDir = Join-Path $Root "dist\portable-windows"
Remove-Item -Recurse -Force $OutDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Root "build\portable-windows") -ErrorAction SilentlyContinue

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "build-portable-windows.ps1: 'uv' not found - install it from https://astral.sh/uv"
}

Write-Host "Syncing dependencies (dev extra, includes pyinstaller)..."
uv sync --extra dev --extra formats --extra raw

Write-Host "Building Photoslop.exe (v$Version) with PyInstaller..."
uv run pyinstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name Photoslop `
    --distpath $OutDir `
    --workpath (Join-Path $Root "build\portable-windows") `
    --specpath (Join-Path $Root "build\portable-windows") `
    photoslop/app.py

$AppDir = Join-Path $OutDir "Photoslop"
$Exe = Join-Path $AppDir "Photoslop.exe"
if (-not (Test-Path $Exe)) {
    throw "build-portable-windows.ps1: expected executable was not produced: $Exe"
}

$Zip = Join-Path $OutDir "Photoslop-Windows-portable-v$Version.zip"
Compress-Archive -Path $AppDir -DestinationPath $Zip -Force

Write-Host "Portable Windows build ready:"
Write-Host "  Folder: $AppDir"
Write-Host "  Zip: $Zip"

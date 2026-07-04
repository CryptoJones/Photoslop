@echo off
REM Photoslop launcher for humans (Windows).
REM
REM Bootstraps uv if it's missing, then starts the app. Any arguments are
REM passed straight through to photoslop -- e.g. run.cmd path\to\image.png
REM
REM SPDX-License-Identifier: Apache-2.0
setlocal EnableExtensions

REM Run from the repo root no matter where this was invoked from.
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo run.cmd: 'uv' not found -- installing it from https://astral.sh/uv ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

REM `uv run` creates/syncs the project venv on demand.
uv run photoslop %*

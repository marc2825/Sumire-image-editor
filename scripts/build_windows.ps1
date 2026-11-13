# Build the Windows distribution: a PyInstaller folder (onedir) packed into
# dist\Sumire-v<version>-win64.zip. Run from a copy of the source on Windows:
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#
# -PythonExecutable  a Python 3.12 (64-bit) to create the build environment from
# -SkipTests         do not run the test suite first
param(
    [string]$PythonExecutable = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
# Output contains non-ASCII names (Sumīre); a Japanese console would fail to print them.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($env:OS -ne "Windows_NT") { throw "Run this script on Windows. Cross-compiling is not supported." }
if ($PythonExecutable) {
    & (Resolve-Path $PythonExecutable).Path -m venv .venv-windows
} else {
    py -3.12 -m venv .venv-windows
}
if ($LASTEXITCODE -ne 0) { throw "Could not create the Python 3.12 environment." }
$python = Join-Path $PWD ".venv-windows\Scripts\python.exe"
# The exact versions of the published build; Qt comes from the PySide6-Essentials wheel.
& $python -m pip install --disable-pip-version-check -r scripts/windows-build-requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
if (-not $SkipTests) {
    & $python -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; build cancelled." }
}
& $python -m scripts.prepare_release
if ($LASTEXITCODE -ne 0) { throw "Could not prepare the icon and version information." }
# onedir keeps Qt, PySide6 and the other libraries as separate files in _internal,
# so they can be replaced (QT_REPLACEMENT.md). UPX is off: the DLLs stay unmodified.
& $python -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --name sumire `
    --contents-directory _internal --icon assets/sumire.ico --version-file build/sumire-version.txt `
    --add-data "build/build-info.json;." --collect-data sumire --collect-all PIL `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module pillow_heif --exclude-module pi_heif run_sumire.py
if ($LASTEXITCODE -ne 0) { throw "Build failed." }
& $python -m scripts.package_windows
if ($LASTEXITCODE -ne 0) { throw "Could not package the Windows release." }

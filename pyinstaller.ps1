# pyinstaller.ps1 — Windows build script for SSH Client Manager
# Usage: .\pyinstaller.ps1
#
# Produces: dist\SSHClientManager\SSHClientManager.exe
# Zip that folder to distribute — no Python installation required.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "🚀 Building SSH Client Manager PyInstaller bundle..." -ForegroundColor Cyan

# ── Sanity check ─────────────────────────────────────────────────────────────
if (-not (Test-Path "ssh-client-manager.spec")) {
    Write-Host "❌ Error: ssh-client-manager.spec not found. Please run this script from the project root directory." -ForegroundColor Red
    exit 1
}

# ── Locate Python ─────────────────────────────────────────────────────────────
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Host "❌ Python not found in PATH. Please install Python 3.11+ from https://python.org" -ForegroundColor Red
    exit 1
}
$PythonVersion = & python --version 2>&1
Write-Host "🐍 Using: $PythonVersion  ($($PythonCmd.Source))" -ForegroundColor Green

# ── Create / reuse isolated venv ──────────────────────────────────────────────
$VenvDir = ".venv-build"
if (-not (Test-Path $VenvDir)) {
    Write-Host "📦 Creating virtual environment at $VenvDir ..." -ForegroundColor Yellow
    python -m venv $VenvDir
    Write-Host "✅ Virtual environment created" -ForegroundColor Green

    Write-Host "📦 Installing build dependencies..." -ForegroundColor Yellow
    & "$VenvDir\Scripts\pip.exe" install --upgrade pip --quiet
    & "$VenvDir\Scripts\pip.exe" install PyInstaller --quiet
    & "$VenvDir\Scripts\pip.exe" install -r requirements-windows.txt --quiet
    Write-Host "✅ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "📦 Reusing existing virtual environment at $VenvDir" -ForegroundColor Yellow
}

# ── Run PyInstaller ───────────────────────────────────────────────────────────
Write-Host "🔨 Running PyInstaller..." -ForegroundColor Yellow
& "$VenvDir\Scripts\python.exe" -m PyInstaller --clean --noconfirm ssh-client-manager.spec

# ── Post-build check ──────────────────────────────────────────────────────────
$ExePath = "dist\SSHClientManager\SSHClientManager.exe"
if (-not (Test-Path $ExePath)) {
    Write-Host "❌ Build failed! Executable not found at $ExePath" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Build successful! Executable at: $(Resolve-Path $ExePath)" -ForegroundColor Green

# ── Create ZIP for distribution ───────────────────────────────────────────────
Write-Host "📦 Creating distribution ZIP..." -ForegroundColor Yellow

# Try to read version from pyproject.toml
$Version = $null
if (Test-Path "pyproject.toml") {
    $match = Select-String -Path "pyproject.toml" -Pattern 'version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match) {
        $Version = $match.Matches[0].Groups[1].Value
    }
}
if (-not $Version) {
    $Version = Get-Date -Format "yyyyMMdd"
}

$ZipName = "SSHClientManager-Windows-$Version.zip"
$ZipPath = "dist\$ZipName"

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

Compress-Archive -Path "dist\SSHClientManager" -DestinationPath $ZipPath
Write-Host ""
Write-Host "🎉 All done!" -ForegroundColor Cyan
Write-Host "📍 Folder : $(Resolve-Path 'dist\SSHClientManager')" -ForegroundColor White
Write-Host "📍 ZIP    : $(Resolve-Path $ZipPath)" -ForegroundColor White
Write-Host "🚀 Test   : dist\SSHClientManager\SSHClientManager.exe" -ForegroundColor White

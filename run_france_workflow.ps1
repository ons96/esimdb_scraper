# Ensures uv is used for venv + deps on PowerShell
param(
  [switch]$Headless
)

$ErrorActionPreference = "Stop"

Write-Host "==================================="
Write-Host "  eSIM Plan Analyzer for France (uv)"
Write-Host "==================================="

# Ensure uv is available
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "'uv' not found on PATH. Attempting to install via pip..."
  python -m pip install --upgrade pip | Out-Null
  python -m pip install --user uv
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "Could not find or install 'uv'. Install it then re-run: 'pipx install uv' or 'python -m pip install --user uv'"
  }
}

$VenvDir = ".venv"
$VenvPy = Join-Path $VenvDir "Scripts/python.exe"

if (-not (Test-Path $VenvDir)) {
  Write-Host "Creating virtual environment with uv..."
  uv venv $VenvDir
}

Write-Host "Installing/updating required packages with uv pip..."
uv pip install --python $VenvPy requests beautifulsoup4 pandas numpy

Write-Host "Starting France eSIM plan analysis..."
& $VenvPy workflow_france.py

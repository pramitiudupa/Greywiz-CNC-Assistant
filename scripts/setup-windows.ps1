# One-time setup on Windows: Python 3.12 virtual environment + frontend packages.
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root "backend\.venv"

if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Python 3.12 is required (py -3.12)." -ForegroundColor Red; exit 1 }
}
$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $root "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Host "Backend install failed." -ForegroundColor Red; exit 1 }

Push-Location (Join-Path $root "frontend")
npm install --legacy-peer-deps
Pop-Location

if (-not (Test-Path (Join-Path $root "backend\.env"))) {
    Copy-Item (Join-Path $root "backend\.env.example") (Join-Path $root "backend\.env")
    Write-Host "Created backend\.env - add your GOOGLE_API_KEY to it." -ForegroundColor Yellow
}
Write-Host "Setup complete. Start the app with scripts\dev-windows.ps1" -ForegroundColor Green

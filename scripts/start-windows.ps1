# Builds the frontend and serves the whole app from one server (for demos).
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File scripts\start-windows.ps1
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Backend environment not found. Run scripts\setup-windows.ps1 first." -ForegroundColor Red
    exit 1
}

Push-Location (Join-Path $root "frontend")
npm run build
$built = $LASTEXITCODE
Pop-Location
if ($built -ne 0) { Write-Host "Frontend build failed." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Greywiz: open http://127.0.0.1:8000  (Ctrl+C to stop)" -ForegroundColor Green
Push-Location (Join-Path $root "backend")
& $python -m uvicorn api:app --host 127.0.0.1 --port 8000
Pop-Location

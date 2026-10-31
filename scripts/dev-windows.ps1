# Starts the Greywiz backend (FastAPI) and frontend (Vite) on Windows.
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File scripts\dev-windows.ps1
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Backend environment not found. Run scripts\setup-windows.ps1 first." -ForegroundColor Red
    exit 1
}

$backend = Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "backend") -PassThru -NoNewWindow
$frontend = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev", "--", "--port", "5173" `
    -WorkingDirectory (Join-Path $root "frontend") -PassThru -NoNewWindow

Write-Host ""
Write-Host "Greywiz is starting:" -ForegroundColor Green
Write-Host "  App:      http://127.0.0.1:5173"
Write-Host "  API docs: http://127.0.0.1:8000/docs"
Write-Host "Press Ctrl+C to stop both."

try {
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    foreach ($p in @($backend, $frontend)) {
        if ($p -and -not $p.HasExited) { taskkill /PID $p.Id /T /F | Out-Null }
    }
}

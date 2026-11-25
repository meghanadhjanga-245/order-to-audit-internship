# One command to run the Order-to-Audit prototype on Windows PowerShell.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
    & .venv\Scripts\python -m pip install --quiet --upgrade pip
    & .venv\Scripts\python -m pip install --quiet -r requirements.txt
}

Write-Host "Applying migrations..."
& .venv\Scripts\python manage.py migrate --noinput

Write-Host "Loading benchmark data (skipped if already present)..."
& .venv\Scripts\python manage.py seed_benchmark

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host "  Open http://127.0.0.1:8000/ in your browser" -ForegroundColor Green
Write-Host "  Password for every demo login: benchmark123" -ForegroundColor Yellow
Write-Host "  1-Click Role Switcher & Benchmark Studio available on UI" -ForegroundColor Magenta
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host ""

& .venv\Scripts\python manage.py runserver 8000

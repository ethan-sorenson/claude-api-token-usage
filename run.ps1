if (-not (Test-Path "venv")) {
    Write-Host "Virtual environment not found!" -ForegroundColor Red
    Write-Host "Run setup first: .\scripts\setup.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "Activating virtual environment..." -ForegroundColor Cyan
.\venv\Scripts\Activate.ps1
Write-Host "Starting Flask server..." -ForegroundColor Green
python app.py

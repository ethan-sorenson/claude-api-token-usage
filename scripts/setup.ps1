Write-Host "Setting up Claude API Token Usage Demo..." -ForegroundColor Cyan
if (Test-Path "venv") {
    Write-Host "Virtual environment already exists" -ForegroundColor Green
} else {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
}
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
.\venv\Scripts\Activate.ps1
Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
Write-Host "Installing dependencies..." -ForegroundColor Yellow
python -m pip install -r requirements.txt
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "Run the app with: .\run.ps1" -ForegroundColor Cyan

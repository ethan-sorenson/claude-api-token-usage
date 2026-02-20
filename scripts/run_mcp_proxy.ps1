# Business Central MCP Proxy Launcher
# NOTE: The proxy now starts automatically with the Flask app.
# This script is only needed for standalone/manual testing.

Write-Host "Starting MCP Header Proxy (standalone mode)..." -ForegroundColor Green

# Activate virtual environment if it exists
if (Test-Path "venv\Scripts\Activate.ps1") {
    Write-Host "Activating virtual environment..." -ForegroundColor Cyan
    & "venv\Scripts\Activate.ps1"
}

$env:PROXY_PORT = "5001"

# Run the proxy
python proxy\bc_mcp_proxy.py

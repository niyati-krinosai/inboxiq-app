# Start InboxIQ locally for testing
# Usage: .\scripts\start-local.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "Starting Docker (Postgres + Redis + API)..." -ForegroundColor Cyan
Set-Location $Root
docker compose -f docker-compose.prod.yml up -d --build

Write-Host "Starting frontend on http://localhost:3000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$Root\frontend'; npm run dev"
)

Write-Host ""
Write-Host "InboxIQ is starting:" -ForegroundColor Green
Write-Host "  Backend:  http://localhost:8000"
Write-Host "  1. Open http://localhost:3000 (frontend)"
Write-Host "  2. Sign in with Gmail"
Write-Host "  3. Wait for newsletters to import"
Write-Host "  4. Ask a question in any mode"
Write-Host ""

# Run full InboxIQ stack in Docker (local dev)
# Usage: .\scripts\docker-up.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Starting InboxIQ (Postgres + Redis + API)..." -ForegroundColor Cyan
docker compose up -d --build

Write-Host ""
Write-Host "API:      http://localhost:8000" -ForegroundColor Green
Write-Host "Frontend: cd frontend && npm run dev  ->  http://localhost:3000" -ForegroundColor Green
